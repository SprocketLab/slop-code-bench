"""Unified credential store for API keys and authentication files."""

from __future__ import annotations

import os
import typing as tp
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Final

from pydantic import BaseModel
from pydantic import Field

ApiFormat = tp.Literal["openai", "anthropic"]


class EndpointDefinition(BaseModel):
    """API endpoint configuration for a provider.

    Endpoints allow providers to define multiple API access points with
    different base URLs and API formats. This is useful for providers
    like Zhipu that offer both OpenAI-compatible and Anthropic-compatible
    endpoints.

    Attributes:
        api_base: Base URL for the API endpoint
        api_format: API format - "openai" or "anthropic"
    """

    api_base: str
    api_format: ApiFormat = "openai"


class CredentialType(str, Enum):
    """Type of credential storage."""

    ENV_VAR = "env_var"
    FILE = "file"


class ProviderCredential(BaseModel):
    """Resolved credential for a provider.

    Attributes:
        provider: The provider name (e.g., 'anthropic', 'openai')
        credential_type: Whether this is an env var or file credential
        value: The actual API key or file contents
        source: Where the credential came from (env var name or file path)
        destination_key: The environment variable name to export as
    """

    provider: str
    credential_type: CredentialType
    value: str
    source: str
    destination_key: str


class CredentialNotFoundError(Exception):
    """Raised when a credential cannot be resolved."""

    pass


class ProviderDefinition(BaseModel):
    """Definition of a credential provider.

    Attributes:
        name: Provider identifier (e.g., 'anthropic', 'openai')
        credential_type: Whether this uses env var or file
        env_var: Environment variable name (for env_var type)
        file_path: Default file path (for file type)
        description: Human-readable description for discoverability
        endpoints: Named API endpoints for this provider
    """

    name: str
    credential_type: CredentialType
    env_var: str | None = None
    file_path: str | None = None
    description: str = ""
    endpoints: dict[str, EndpointDefinition] = Field(default_factory=dict)

    def get_endpoint(self, name: str) -> EndpointDefinition | None:
        """Get endpoint by name.

        Args:
            name: Endpoint name to look up

        Returns:
            EndpointDefinition if found, None otherwise
        """
        return self.endpoints.get(name)


class ProviderCatalog:
    """Registry of providers loaded from YAML.

    This class provides centralized access to provider definitions,
    enabling both APIKeyStore and users to discover available providers
    and their credential requirements.

    Providers are loaded from configs/providers.yaml.

    Example:
        >>> provider = ProviderCatalog.get("anthropic")
        >>> print(provider.env_var)  # "ANTHROPIC_API_KEY"
    """

    _providers: ClassVar[dict[str, ProviderDefinition]] = {}
    _loaded: ClassVar[bool] = False

    @classmethod
    def register(cls, provider: ProviderDefinition) -> None:
        """Register a provider definition."""
        cls._providers[provider.name] = provider

    @classmethod
    def get(cls, name: str) -> ProviderDefinition | None:
        """Get provider by name.

        Args:
            name: Provider name to look up

        Returns:
            ProviderDefinition if found, None otherwise
        """
        cls.ensure_loaded()
        return cls._providers.get(name)

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names.

        Returns:
            Sorted list of provider names
        """
        cls.ensure_loaded()
        return sorted(cls._providers.keys())

    @classmethod
    def load_from_file(cls, providers_file: Path) -> None:
        """Load provider definitions from YAML file.

        Args:
            providers_file: Path to providers YAML file
        """
        import yaml

        if not providers_file.exists():
            return

        data = yaml.safe_load(providers_file.read_text())
        if not data or "providers" not in data:
            return

        for name, config in data["providers"].items():
            # Parse endpoints if present
            endpoints: dict[str, EndpointDefinition] = {}
            if "endpoints" in config:
                for ep_name, ep_config in config["endpoints"].items():
                    endpoints[ep_name] = EndpointDefinition(
                        api_base=ep_config["api_base"],
                        api_format=ep_config.get("api_format", "openai"),
                    )

            provider = ProviderDefinition(
                name=name,
                credential_type=CredentialType(config["type"]),
                env_var=config.get("env_var"),
                file_path=config.get("file_path"),
                description=config.get("description", ""),
                endpoints=endpoints,
            )
            cls.register(provider)

    @classmethod
    def ensure_loaded(cls, providers_file: Path | None = None) -> None:
        """Ensure providers are loaded from YAML file (idempotent).

        Args:
            providers_file: Optional path to providers file. If None, uses
                the default configs/providers.yaml relative to project root.
        """
        if cls._loaded:
            return

        if providers_file is None:
            providers_file = (
                Path(__file__).parents[3] / "configs" / "providers.yaml"
            )

        cls.load_from_file(providers_file)
        cls._loaded = True

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers. Useful for testing."""
        cls._providers.clear()
        cls._loaded = False


class CredentialSpec(BaseModel):
    """Specification for credentials in agent configs.

    This model is used in agent configuration files to specify which
    provider credentials to use.

    Examples:
        # Simple provider reference
        credentials:
          provider: anthropic

        # File provider with custom path
        credentials:
          provider: codex_auth
          file_path: ~/custom/auth.json

        # With destination key override (for CLI agents)
        credentials:
          provider: zhipu
          destination_key: ANTHROPIC_API_KEY

    Attributes:
        provider: Provider name (e.g., 'anthropic', 'openai', 'codex_auth')
        file_path: Override default file path for file-based providers
        destination_key: Env var name to export the credential as
    """

    provider: str = Field(
        description="Provider name (e.g., 'anthropic', 'openai', 'codex_auth')"
    )
    file_path: Path | None = Field(
        default=None,
        description="Override default file path for file-based providers",
    )
    destination_key: str | None = Field(
        default=None,
        description="Env var name to export the credential as (for CLI agents)",
    )

    def resolve(
        self,
        store: APIKeyStore,
        *,
        env_var_override: str | None = None,
    ) -> ProviderCredential:
        """Resolve this credential spec using the given store.

        Args:
            store: The APIKeyStore to resolve credentials from
            env_var_override: Optional override for env var providers

        Returns:
            ProviderCredential with the resolved value

        Raises:
            CredentialNotFoundError: If the credential cannot be resolved
        """
        return store.resolve(
            self.provider,
            file_path_override=self.file_path,
            env_var_override=env_var_override,
        )

    def get_destination_key(self) -> str:
        """Get the destination environment variable name.

        Returns the explicit destination_key if set, otherwise falls back
        to the standard env var name for env var providers.

        Returns:
            The environment variable name to export the credential as

        Raises:
            ValueError: If provider is file-based and no destination_key set,
                or if provider is unknown
        """
        if self.destination_key is not None:
            return self.destination_key

        # Look up provider in catalog
        provider_def = ProviderCatalog.get(self.provider)
        if provider_def is None:
            raise ValueError(f"Unknown provider '{self.provider}'")

        # For env var providers, default to their standard name
        if provider_def.credential_type == CredentialType.ENV_VAR:
            return provider_def.env_var  # type: ignore[return-value]

        # For file providers, there's no default - must be explicit
        raise ValueError(
            f"File-based provider '{self.provider}' requires explicit 'destination_key'"
        )


class APIKeyStore:
    """Unified credential store mapping provider names to their credentials.

    This class provides a single interface for resolving API credentials
    regardless of whether they come from environment variables or files.

    Provider definitions are loaded from configs/providers.yaml via
    ProviderCatalog. This allows agent configs to use simple provider names
    like 'anthropic' instead of environment variable names like
    'ANTHROPIC_API_KEY'.

    See configs/providers.yaml for the full list of supported providers.

    Example:
        >>> store = APIKeyStore()
        >>> cred = store.resolve("anthropic")
        >>> print(cred.value)  # The actual API key
        >>> print(cred.source)  # "ANTHROPIC_API_KEY"
    """

    def __init__(self) -> None:
        """Initialize the credential store.

        The store is frozen after initialization - only the internal cache
        can be modified (to support single-read semantics for credentials).
        """
        object.__setattr__(self, "_cache", {})
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent modification of store attributes after initialization."""
        if getattr(self, "_frozen", False) and name != "_cache":
            raise AttributeError(f"APIKeyStore is frozen, cannot set '{name}'")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Prevent deletion of store attributes after initialization."""
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"APIKeyStore is frozen, cannot delete '{name}'"
            )
        object.__delattr__(self, name)

    @classmethod
    def supported_providers(cls) -> tuple[str, ...]:
        """Return all supported provider names.

        Returns:
            Tuple of all supported provider names, sorted alphabetically
        """
        return tuple(ProviderCatalog.list_providers())

    @classmethod
    def get_credential_type(cls, provider: str) -> CredentialType:
        """Determine the credential type for a provider.

        Args:
            provider: The provider name

        Returns:
            CredentialType.ENV_VAR or CredentialType.FILE

        Raises:
            ValueError: If provider is unknown
        """
        provider_def = ProviderCatalog.get(provider)
        if provider_def is None:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Supported providers: {', '.join(cls.supported_providers())}"
            )
        return provider_def.credential_type

    @classmethod
    def get_env_var_name(cls, provider: str) -> str:
        """Get the environment variable name for a provider.

        Args:
            provider: The provider name

        Returns:
            The environment variable name (e.g., 'ANTHROPIC_API_KEY')

        Raises:
            ValueError: If provider is not an env var provider
        """
        provider_def = ProviderCatalog.get(provider)
        if (
            provider_def is None
            or provider_def.credential_type != CredentialType.ENV_VAR
        ):
            ProviderCatalog.ensure_loaded()
            env_providers = [
                p.name
                for p in ProviderCatalog._providers.values()
                if p.credential_type == CredentialType.ENV_VAR
            ]
            raise ValueError(
                f"Provider '{provider}' does not use environment variables. "
                f"Env var providers: {', '.join(sorted(env_providers))}"
            )
        return provider_def.env_var  # type: ignore[return-value]

    @classmethod
    def get_file_path(cls, provider: str) -> Path:
        """Get the default file path for a file-based provider.

        Args:
            provider: The provider name

        Returns:
            The default file path, with ~ expanded

        Raises:
            ValueError: If provider is not a file-based provider
        """
        provider_def = ProviderCatalog.get(provider)
        if (
            provider_def is None
            or provider_def.credential_type != CredentialType.FILE
        ):
            ProviderCatalog.ensure_loaded()
            file_providers = [
                p.name
                for p in ProviderCatalog._providers.values()
                if p.credential_type == CredentialType.FILE
            ]
            raise ValueError(
                f"Provider '{provider}' does not use file credentials. "
                f"File providers: {', '.join(sorted(file_providers))}"
            )
        return Path(provider_def.file_path).expanduser()  # type: ignore[arg-type]

    def resolve(
        self,
        provider: str,
        *,
        file_path_override: Path | None = None,
        env_var_override: str | None = None,
    ) -> ProviderCredential:
        """Resolve credentials for a provider.

        Args:
            provider: The provider name (e.g., 'anthropic', 'codex_auth')
            file_path_override: Optional override for file-based providers
            env_var_override: Optional override for env-var providers

        Returns:
            ProviderCredential with the resolved value

        Raises:
            ValueError: If provider is unknown
            CredentialNotFoundError: If credential cannot be resolved
        """
        cache_key = (
            f"{provider}:{file_path_override or 'default'}:"
            f"{env_var_override or 'default_env'}"
        )
        if cache_key in self._cache:
            return self._cache[cache_key]

        credential_type = self.get_credential_type(provider)

        if credential_type == CredentialType.ENV_VAR:
            credential = self._resolve_env_var(
                provider, env_var_override=env_var_override
            )
        else:
            file_path = file_path_override or self.get_file_path(provider)
            credential = self._resolve_file(provider, file_path)

        self._cache[cache_key] = credential
        return credential

    def _resolve_env_var(
        self,
        provider: str,
        *,
        env_var_override: str | None = None,
    ) -> ProviderCredential:
        """Resolve an environment variable credential.

        Args:
            provider: The provider name
            env_var_override: Optional override for the env var name

        Returns:
            ProviderCredential with the resolved value

        Raises:
            CredentialNotFoundError: If env var is not set
        """
        provider_def = ProviderCatalog.get(provider)
        if provider_def is None or provider_def.env_var is None:
            raise ValueError(f"Unknown env var provider: {provider}")
        if provider_def.credential_type != CredentialType.ENV_VAR:
            raise ValueError(
                f"Provider '{provider}' does not use environment variables"
            )

        env_var_name = env_var_override or provider_def.env_var
        value = os.environ.get(env_var_name)

        if value is None:
            raise CredentialNotFoundError(
                f"Environment variable '{env_var_name}' not found "
                f"for provider '{provider}'"
            )

        return ProviderCredential(
            provider=provider,
            credential_type=CredentialType.ENV_VAR,
            value=value,
            source=provider_def.env_var,
            destination_key=provider_def.env_var,
        )

    def _resolve_file(
        self, provider: str, file_path: Path
    ) -> ProviderCredential:
        """Resolve a file-based credential.

        Args:
            provider: The provider name
            file_path: Path to the credential file

        Returns:
            ProviderCredential with the file contents

        Raises:
            CredentialNotFoundError: If file does not exist
        """
        expanded_path = file_path.expanduser().absolute()

        if not expanded_path.exists():
            raise CredentialNotFoundError(
                f"Credential file not found for provider '{provider}': {expanded_path}"
            )

        value = expanded_path.read_text()

        return ProviderCredential(
            provider=provider,
            credential_type=CredentialType.FILE,
            value=value,
            source=str(expanded_path),
            # File providers require explicit destination_key from CredentialSpec
            destination_key="",
        )

    def has_credential(
        self,
        provider: str,
        *,
        file_path_override: Path | None = None,
    ) -> bool:
        """Check if a credential is available without raising.

        Args:
            provider: The provider name
            file_path_override: Optional override for file-based providers

        Returns:
            True if the credential can be resolved, False otherwise
        """
        try:
            self.resolve(provider, file_path_override=file_path_override)
            return True
        except (ValueError, CredentialNotFoundError):
            return False

    def clear_cache(self) -> None:
        """Clear the credential cache."""
        self._cache.clear()


# Module-level credential store (frozen after initialization)
API_KEY_STORE: Final[APIKeyStore] = APIKeyStore()
