"""Tests for the credentials module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from slop_code.agent_runner.credentials import API_KEY_STORE
from slop_code.agent_runner.credentials import APIKeyStore
from slop_code.agent_runner.credentials import CredentialNotFoundError
from slop_code.agent_runner.credentials import CredentialSpec
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential


class TestAPIKeyStore:
    """Tests for APIKeyStore class."""

    def test_supported_providers_returns_all_providers(self):
        """Test that supported_providers returns both env var and file providers."""
        providers = APIKeyStore.supported_providers()
        # Check some known providers exist
        assert "anthropic" in providers
        assert "openai" in providers
        assert "codex_auth" in providers
        assert "opencode_auth" in providers
        # Should be sorted
        assert providers == tuple(sorted(providers))

    def test_get_credential_type_env_var(self):
        """Test credential type detection for env var providers."""
        assert APIKeyStore.get_credential_type("anthropic") == CredentialType.ENV_VAR
        assert APIKeyStore.get_credential_type("openai") == CredentialType.ENV_VAR
        assert APIKeyStore.get_credential_type("zhipu") == CredentialType.ENV_VAR

    def test_get_credential_type_file(self):
        """Test credential type detection for file providers."""
        assert APIKeyStore.get_credential_type("codex_auth") == CredentialType.FILE
        assert APIKeyStore.get_credential_type("opencode_auth") == CredentialType.FILE

    def test_get_credential_type_unknown_raises(self):
        """Test that unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            APIKeyStore.get_credential_type("unknown_provider")

    def test_get_env_var_name(self):
        """Test getting env var name for known providers."""
        assert APIKeyStore.get_env_var_name("anthropic") == "ANTHROPIC_API_KEY"
        assert APIKeyStore.get_env_var_name("openai") == "OPENAI_API_KEY"
        assert APIKeyStore.get_env_var_name("zhipu") == "ZHIPU_API_KEY"

    def test_get_env_var_name_file_provider_raises(self):
        """Test that file providers raise when asking for env var name."""
        with pytest.raises(ValueError, match="does not use environment variables"):
            APIKeyStore.get_env_var_name("codex_auth")

    def test_get_file_path(self):
        """Test getting file path for file providers."""
        codex_path = APIKeyStore.get_file_path("codex_auth")
        assert codex_path == Path.home() / ".codex" / "auth.json"

        opencode_path = APIKeyStore.get_file_path("opencode_auth")
        assert opencode_path == Path.home() / ".local/share/opencode/auth.json"

    def test_get_file_path_env_provider_raises(self):
        """Test that env providers raise when asking for file path."""
        with pytest.raises(ValueError, match="does not use file credentials"):
            APIKeyStore.get_file_path("anthropic")

    def test_resolve_env_var_success(self, monkeypatch):
        """Test resolving an env var credential."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key-123")
        store = APIKeyStore()

        cred = store.resolve("anthropic")

        assert cred.provider == "anthropic"
        assert cred.credential_type == CredentialType.ENV_VAR
        assert cred.value == "test-api-key-123"
        assert cred.source == "ANTHROPIC_API_KEY"

    def test_resolve_env_var_missing_raises(self, monkeypatch):
        """Test that missing env var raises CredentialNotFoundError."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        store = APIKeyStore()

        with pytest.raises(CredentialNotFoundError, match="not found"):
            store.resolve("anthropic")

    def test_resolve_file_success(self):
        """Test resolving a file credential."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"token": "secret"}')

            store = APIKeyStore()
            cred = store.resolve("codex_auth", file_path_override=auth_file)

            assert cred.provider == "codex_auth"
            assert cred.credential_type == CredentialType.FILE
            assert cred.value == '{"token": "secret"}'
            assert str(auth_file) in cred.source

    def test_resolve_file_missing_raises(self):
        """Test that missing file raises CredentialNotFoundError."""
        store = APIKeyStore()
        nonexistent = Path("/nonexistent/path/auth.json")

        with pytest.raises(CredentialNotFoundError, match="not found"):
            store.resolve("codex_auth", file_path_override=nonexistent)

    def test_resolve_caches_result(self, monkeypatch):
        """Test that resolved credentials are cached."""
        monkeypatch.setenv("OPENAI_API_KEY", "cached-key")
        store = APIKeyStore()

        cred1 = store.resolve("openai")
        cred2 = store.resolve("openai")

        assert cred1 is cred2  # Same object from cache

    def test_clear_cache(self, monkeypatch):
        """Test that clear_cache removes cached credentials."""
        monkeypatch.setenv("OPENAI_API_KEY", "original-key")
        store = APIKeyStore()

        cred1 = store.resolve("openai")
        store.clear_cache()
        monkeypatch.setenv("OPENAI_API_KEY", "new-key")
        cred2 = store.resolve("openai")

        assert cred1 is not cred2
        assert cred2.value == "new-key"

    def test_has_credential_true(self, monkeypatch):
        """Test has_credential returns True when credential exists."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "exists")
        store = APIKeyStore()

        assert store.has_credential("anthropic") is True

    def test_has_credential_false(self, monkeypatch):
        """Test has_credential returns False when credential missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        store = APIKeyStore()

        assert store.has_credential("anthropic") is False

    def test_has_credential_unknown_provider(self):
        """Test has_credential returns False for unknown provider."""
        store = APIKeyStore()
        assert store.has_credential("unknown_provider") is False


class TestCredentialSpec:
    """Tests for CredentialSpec model."""

    def test_basic_spec_creation(self):
        """Test creating a basic credential spec."""
        spec = CredentialSpec(provider="anthropic")
        assert spec.provider == "anthropic"
        assert spec.file_path is None
        assert spec.destination_key is None

    def test_spec_with_all_fields(self):
        """Test creating a spec with all optional fields."""
        spec = CredentialSpec(
            provider="zhipu",
            file_path=Path("/custom/path"),
            destination_key="ANTHROPIC_API_KEY",
        )
        assert spec.provider == "zhipu"
        assert spec.file_path == Path("/custom/path")
        assert spec.destination_key == "ANTHROPIC_API_KEY"

    def test_resolve_delegates_to_store(self, monkeypatch):
        """Test that resolve() delegates to the store."""
        monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
        spec = CredentialSpec(provider="zhipu")
        store = APIKeyStore()

        cred = spec.resolve(store)

        assert cred.value == "zhipu-key"
        assert cred.provider == "zhipu"

    def test_get_destination_key_explicit(self):
        """Test get_destination_key returns explicit value when set."""
        spec = CredentialSpec(
            provider="zhipu",
            destination_key="CUSTOM_KEY",
        )
        assert spec.get_destination_key() == "CUSTOM_KEY"

    def test_get_destination_key_default_env_provider(self):
        """Test get_destination_key returns provider's env var for env providers."""
        spec = CredentialSpec(provider="anthropic")
        assert spec.get_destination_key() == "ANTHROPIC_API_KEY"

        spec2 = CredentialSpec(provider="openai")
        assert spec2.get_destination_key() == "OPENAI_API_KEY"

    def test_get_destination_key_file_provider_raises(self):
        """Test get_destination_key raises for file providers without explicit key."""
        spec = CredentialSpec(provider="codex_auth")
        with pytest.raises(ValueError, match="requires explicit 'destination_key'"):
            spec.get_destination_key()


class TestProviderCredential:
    """Tests for ProviderCredential model."""

    def test_credential_creation(self):
        """Test creating a provider credential."""
        cred = ProviderCredential(
            provider="anthropic",
            credential_type=CredentialType.ENV_VAR,
            value="secret-key",
            source="ANTHROPIC_API_KEY",
            destination_key="ANTHROPIC_API_KEY",
        )
        assert cred.provider == "anthropic"
        assert cred.credential_type == CredentialType.ENV_VAR
        assert cred.value == "secret-key"
        assert cred.source == "ANTHROPIC_API_KEY"
        assert cred.destination_key == "ANTHROPIC_API_KEY"


class TestAPIKeyStoreConstant:
    """Tests for the API_KEY_STORE module constant."""

    def test_api_key_store_is_instance(self):
        """Test that API_KEY_STORE is an APIKeyStore instance."""
        assert isinstance(API_KEY_STORE, APIKeyStore)

    def test_api_key_store_is_frozen(self):
        """Test that API_KEY_STORE cannot have attributes set."""
        with pytest.raises(AttributeError, match="frozen"):
            API_KEY_STORE.new_attr = "value"

    def test_api_key_store_cannot_delete_attrs(self):
        """Test that API_KEY_STORE attributes cannot be deleted."""
        with pytest.raises(AttributeError, match="frozen"):
            del API_KEY_STORE._frozen


class TestAPIKeyStoreFrozen:
    """Tests for the frozen behavior of APIKeyStore."""

    def test_new_store_is_frozen(self):
        """Test that a new APIKeyStore instance is frozen."""
        store = APIKeyStore()
        with pytest.raises(AttributeError, match="frozen"):
            store.new_attr = "value"

    def test_frozen_allows_cache_modification(self, monkeypatch):
        """Test that the internal cache can still be modified for caching."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        store = APIKeyStore()

        # Cache should be modified internally during resolve
        assert store._cache == {}
        store.resolve("anthropic")
        assert "anthropic:default:default_env" in store._cache

    def test_frozen_allows_clear_cache(self, monkeypatch):
        """Test that clear_cache still works on frozen store."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        store = APIKeyStore()

        store.resolve("anthropic")
        assert len(store._cache) > 0

        store.clear_cache()
        assert store._cache == {}
