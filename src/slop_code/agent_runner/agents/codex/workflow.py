"""Configurable skill workflows for the Codex agent."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

_NAME_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_SKILL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LOCAL_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _HashWriter(Protocol):
    def update(self, data: bytes, /) -> None:
        """Add bytes to the hash state."""


class WorkflowLocalPackage(BaseModel):
    """A host package copied into the workflow image before installation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Path
    target: str
    exclude: tuple[str, ...] = ()

    @field_validator("target")
    @classmethod
    def _validate_target(cls, value: str) -> str:
        if not _LOCAL_TARGET_RE.fullmatch(value):
            raise ValueError(
                "local package target must be a single safe path component"
            )
        return value

    @field_validator("exclude")
    @classmethod
    def _validate_excludes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        invalid = any(
            not name or name in {".", ".."} or "/" in name or "\\" in name
            for name in value
        )
        if invalid:
            raise ValueError(
                "local package exclusions must be non-empty path names"
            )
        return value

    @property
    def context_path(self) -> str:
        """Return the package path inside the Docker build context."""
        return f"workflow-packages/{self.target}"

    @property
    def container_path(self) -> str:
        """Return the package path copied into the built image."""
        return f"/opt/workflow-packages/{self.target}"

    def resolved_source(self) -> Path:
        """Resolve and validate the configured host path."""
        source = self.source.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(
                f"Workflow local package does not exist: {source}"
            )
        return source

    def update_content_hash(self, digest: _HashWriter) -> None:
        """Add the package's relevant paths and contents to an image hash."""
        source = self.resolved_source()
        excluded = frozenset(self.exclude)
        digest.update(self.target.encode())
        digest.update(b"\0")
        digest.update("\0".join(self.exclude).encode())
        digest.update(b"\0")

        if source.is_file() or source.is_symlink():
            self._update_path_hash(digest, source, Path(source.name))
            return

        for root, dir_names, file_names in os.walk(source):
            root_path = Path(root)
            kept_dirs = []
            for dir_name in sorted(dir_names):
                if dir_name in excluded:
                    continue
                path = root_path / dir_name
                if path.is_symlink():
                    self._update_path_hash(
                        digest,
                        path,
                        path.relative_to(source),
                    )
                else:
                    kept_dirs.append(dir_name)
            dir_names[:] = kept_dirs
            for file_name in sorted(file_names):
                if file_name in excluded:
                    continue
                path = root_path / file_name
                self._update_path_hash(
                    digest,
                    path,
                    path.relative_to(source),
                )

    @staticmethod
    def _update_path_hash(
        digest: _HashWriter,
        path: Path,
        relative_path: Path,
    ) -> None:
        digest.update(relative_path.as_posix().encode())
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(str(path.readlink()).encode())
            digest.update(b"\0")
            return
        digest.update(b"file\0")
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")


class WorkflowNode(BaseModel):
    """One skill invocation and its ordered prompt arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arguments: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _SKILL_RE.fullmatch(value):
            raise ValueError("skill names must be lowercase kebab-case")
        return value

    @field_validator("arguments")
    @classmethod
    def _validate_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not argument.strip() for argument in value):
            raise ValueError("workflow arguments must not be empty")
        return value

    @property
    def needs_change_id(self) -> bool:
        return any("{change_id}" in argument for argument in self.arguments)


class WorkflowResourcePool(BaseModel):
    """A pool whose values are assigned exclusively per problem."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env_var: str
    values: tuple[str, ...]

    @field_validator("env_var")
    @classmethod
    def _validate_env_var(cls, value: str) -> str:
        if not _ENV_NAME_RE.fullmatch(value):
            raise ValueError("resource pool env_var must be a valid identifier")
        return value

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("resource pool values must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("resource pool values must be unique")
        return value


class WorkflowConfig(BaseModel):
    """Declarative setup and independently executed skill nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    version: str
    install_commands: tuple[tuple[str, ...], ...] = ()
    local_packages: tuple[WorkflowLocalPackage, ...] = ()
    init_commands: tuple[tuple[str, ...], ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    env_from_host: tuple[str, ...] = ()
    resource_pool: WorkflowResourcePool | None = None
    resource_assignments: dict[str, str] = Field(
        default_factory=dict,
        exclude=True,
        repr=False,
    )
    skills: tuple[WorkflowNode, ...]

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError(
                "workflow type must contain lowercase letters, numbers, dots, "
                "or hyphens"
            )
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workflow version must not be empty")
        return value

    @field_validator("install_commands", "init_commands")
    @classmethod
    def _validate_commands(
        cls,
        value: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[str, ...], ...]:
        invalid = any(
            not command or any(not argument for argument in command)
            for command in value
        )
        if invalid:
            raise ValueError("commands must contain non-empty arguments")
        return value

    @field_validator("env_from_host")
    @classmethod
    def _validate_env_from_host(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _ENV_NAME_RE.fullmatch(name) for name in value):
            raise ValueError(
                "host environment variable names must be valid identifiers"
            )
        if len(value) != len(set(value)):
            raise ValueError(
                "host environment variable names must be unique"
            )
        return value

    @model_validator(mode="after")
    def _validate_environment_sources(self) -> WorkflowConfig:
        overlap = sorted(set(self.env) & set(self.env_from_host))
        if overlap:
            names = ", ".join(overlap)
            raise ValueError(
                "workflow environment variables cannot be configured in both "
                f"env and env_from_host: {names}"
            )
        if self.resource_pool is not None:
            env_var = self.resource_pool.env_var
            if env_var in self.env or env_var in self.env_from_host:
                raise ValueError(
                    "resource pool env_var cannot also be configured in env "
                    "or env_from_host"
                )
        return self

    @field_validator("skills")
    @classmethod
    def _validate_skills(
        cls,
        value: tuple[WorkflowNode, ...],
    ) -> tuple[WorkflowNode, ...]:
        if not value:
            raise ValueError("a workflow must configure at least one skill")
        names = [node.name for node in value]
        if len(names) != len(set(names)):
            raise ValueError("workflow skill names must be unique")
        return value

    @field_validator("local_packages")
    @classmethod
    def _validate_local_packages(
        cls,
        value: tuple[WorkflowLocalPackage, ...],
    ) -> tuple[WorkflowLocalPackage, ...]:
        targets = [package.target for package in value]
        if len(targets) != len(set(targets)):
            raise ValueError("workflow local package targets must be unique")
        return value

    def local_packages_hash(self) -> str | None:
        """Return a stable digest for local content included in the image."""
        if not self.local_packages:
            return None
        digest = hashlib.sha256()
        for package in self.local_packages:
            package.update_content_hash(digest)
        return digest.hexdigest()[:12]

    def allocate_problem_resources(
        self,
        problem_names: list[str],
    ) -> WorkflowConfig:
        """Assign one distinct pool value to every problem for this run."""
        pool = self.resource_pool
        if pool is None:
            return self

        names = list(dict.fromkeys(problem_names))
        if len(names) != len(problem_names):
            raise ValueError("problem names for resource allocation must be unique")
        if len(names) > len(pool.values):
            raise ValueError(
                f"Workflow resource pool has {len(pool.values)} values but "
                f"{len(names)} problems were requested"
            )

        assignments = dict(zip(names, pool.values, strict=False))
        return self.model_copy(
            update={"resource_assignments": assignments},
        )

    def resource_environment(self, problem_name: str) -> dict[str, str]:
        """Return the resource environment assigned to one problem."""
        pool = self.resource_pool
        if pool is None:
            return {}
        try:
            value = self.resource_assignments[problem_name]
        except KeyError as exc:
            raise ValueError(
                f"No workflow resource assigned to problem '{problem_name}'"
            ) from exc
        return {pool.env_var: value}

    def build_prompt(
        self,
        node: WorkflowNode,
        task: str,
        change_id: str | None = None,
    ) -> str:
        """Build one independent, unattended Codex node prompt."""
        sections = [f"${node.name}"]
        for argument in node.arguments:
            if "{change_id}" in argument and change_id is None:
                raise ValueError("change_id is required for this workflow node")
            rendered = argument.replace("{task}", task)
            if change_id is not None:
                rendered = rendered.replace("{change_id}", change_id)
            sections.append(rendered)
        sections.append(
            """This is unattended. Complete only this workflow node; do not invoke or
execute later workflow nodes. Never ask the user a question, request
confirmation, or wait for input. If a skill suggests doing so, make the
smallest reasonable decision from the task, repository, and existing workflow
artifacts, then finish this node."""
        )
        return "\n\n".join(sections) + "\n"

    def required_skill_paths(self, workspace: Path) -> tuple[Path, ...]:
        """Return skill files that initialization must make available."""
        return tuple(
            workspace / ".codex" / "skills" / node.name / "SKILL.md"
            for node in self.skills
        )
