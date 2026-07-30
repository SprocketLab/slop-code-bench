from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import time
from collections.abc import Iterator
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

import httpx
import typer

from slop_code.logging import get_logger

logger = get_logger(__name__)

_GITHUB_API_ROOT = "https://api.github.com/repos/gabeorlanski/scb-problems"
_LATEST_RELEASE_URL = f"{_GITHUB_API_ROOT}/releases/latest"
_RELEASE_TAGS_URL = f"{_GITHUB_API_ROOT}/releases/tags"
_COMMITS_URL = f"{_GITHUB_API_ROOT}/commits"
_PROBLEMS_DIRNAME = "problems"
_PROBLEMS_PATH_ENV_VAR = "SCBENCH_PROBLEMS_PATH"
_MANIFEST_FILENAME = "manifest.json"
_RUN_CATALOG_FILENAME = "problem_catalog.json"
_INSTALL_LOCK_FILENAME = ".catalog-install.lock"
_HTTP_TIMEOUT_SECONDS = 30.0
_LOCK_TIMEOUT_SECONDS = 120.0
_LOCK_POLL_SECONDS = 0.1
_OVERRIDE_MANIFEST_VERSION = "env-override"


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Return whether a value is a mapping with string keys."""
    return isinstance(value, Mapping) and all(
        isinstance(key, str) for key in value
    )


class CatalogError(RuntimeError):
    """Raised when the managed problem catalog cannot be resolved."""


@dataclass(frozen=True)
class CatalogManifest:
    version: str
    commit: str

    @classmethod
    def from_payload(cls, payload: object) -> CatalogManifest | None:
        if not _is_string_mapping(payload):
            return None
        version = payload.get("version")
        commit = payload.get("commit")
        if not isinstance(version, str) or not isinstance(commit, str):
            return None
        if not version.strip() or not commit.strip():
            return None
        return cls(version=version, commit=commit)

    def to_payload(self) -> dict[str, str]:
        return {"version": self.version, "commit": self.commit}


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    commit: str
    tarball_url: str


def get_scbench_home() -> Path:
    override = os.getenv("SCBENCH_HOME")
    if override:
        return Path(override).expanduser()
    return Path("~/.cache/scbench").expanduser()


def get_override_problem_root() -> Path | None:
    override = os.getenv(_PROBLEMS_PATH_ENV_VAR)
    if not override:
        return None
    return Path(override).expanduser()


def get_catalog_root(home: Path) -> Path:
    return home / _PROBLEMS_DIRNAME


def get_manifest_path(home: Path) -> Path:
    return home / _MANIFEST_FILENAME


def get_run_catalog_path(run_dir: Path) -> Path:
    return run_dir / _RUN_CATALOG_FILENAME


def load_manifest(home: Path) -> CatalogManifest | None:
    path = get_manifest_path(home)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to parse catalog manifest",
            manifest_path=str(path),
            error=str(exc),
        )
        return None
    return CatalogManifest.from_payload(payload)


def save_manifest(home: Path, manifest: CatalogManifest) -> None:
    home.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(get_manifest_path(home), manifest.to_payload())


def load_run_catalog_manifest(run_dir: Path) -> CatalogManifest | None:
    path = get_run_catalog_path(run_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return CatalogManifest.from_payload(payload)


def save_run_catalog_manifest(run_dir: Path, manifest: CatalogManifest) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(get_run_catalog_path(run_dir), manifest.to_payload())


def resolve_latest_release() -> ReleaseInfo:
    payload = _get_json(_LATEST_RELEASE_URL)
    return _build_release(payload)


def resolve_release(version: str) -> ReleaseInfo:
    payload = _get_json(f"{_RELEASE_TAGS_URL}/{version}")
    return _build_release(payload)


def sync_catalog(home: Path, version: str | None) -> CatalogManifest:
    home = home.expanduser()
    with _install_lock(home):
        release = (
            resolve_latest_release()
            if version is None
            else resolve_release(version)
        )
        current = load_manifest(home)
        catalog_root = get_catalog_root(home)
        if (
            current is not None
            and current == CatalogManifest(release.version, release.commit)
            and _is_catalog_install_valid(catalog_root)
        ):
            logger.info(
                "Catalog already current",
                version=current.version,
                commit=current.commit,
            )
            return current

        return _install_release(home, release)


def ensure_catalog_installed(home: Path) -> CatalogManifest:
    override_root = _get_validated_override_root()
    if override_root is not None:
        return _build_override_manifest(override_root)

    home = home.expanduser()
    catalog_root = get_catalog_root(home)
    manifest_path = get_manifest_path(home)
    is_first_install = not catalog_root.exists() and not manifest_path.exists()

    manifest = load_manifest(home)
    if manifest is not None and _is_catalog_install_valid(catalog_root):
        return manifest

    try:
        installed = sync_catalog(home, None)
    except CatalogError as exc:
        raise CatalogError(
            "Problem catalog could not be installed automatically. "
            "Run `slop-code sync` to retry.\n"
            f"Original error: {exc}"
        ) from exc
    if is_first_install:
        _print_install_metadata(installed, catalog_root, first_bootstrap=True)
    return installed


def get_problem_root(home: Path, *, bootstrap: bool) -> Path:
    override_root = _get_validated_override_root()
    if override_root is not None:
        return override_root

    if bootstrap:
        ensure_catalog_installed(home)
    catalog_root = get_catalog_root(home)
    manifest = load_manifest(home)
    if manifest is None or not _is_catalog_install_valid(catalog_root):
        raise CatalogError(
            "Problem catalog is not installed. Run `slop-code sync`."
        )
    return catalog_root


def discover_problem_dirs(problem_root: Path) -> list[Path]:
    if not problem_root.exists() or not problem_root.is_dir():
        return []
    problems = [
        child
        for child in problem_root.iterdir()
        if child.is_dir() and (child / "config.yaml").is_file()
    ]
    return sorted(problems, key=lambda path: path.name)


def validate_resume_catalog(run_dir: Path, home: Path) -> CatalogManifest:
    expected = load_run_catalog_manifest(run_dir)
    if expected is None:
        raise CatalogError(
            f"Run is missing {get_run_catalog_path(run_dir).name}; "
            "cannot verify reproducibility for --resume."
        )

    override_root = _get_validated_override_root()
    if override_root is not None:
        override_manifest = _build_override_manifest(override_root)
        if override_manifest.commit != expected.commit:
            raise CatalogError(
                _format_resume_mismatch(expected, override_manifest)
            )
        return override_manifest

    installed = load_manifest(home)
    if installed is None or not _is_catalog_install_valid(
        get_catalog_root(home)
    ):
        raise CatalogError(_format_resume_mismatch(expected, None))

    if installed.commit != expected.commit:
        raise CatalogError(_format_resume_mismatch(expected, installed))

    return installed


def _format_resume_mismatch(
    expected: CatalogManifest,
    installed: CatalogManifest | None,
) -> str:
    if installed is None:
        installed_version = "<none>"
        installed_commit = "<none>"
    else:
        installed_version = installed.version
        installed_commit = installed.commit
    if expected.version == _OVERRIDE_MANIFEST_VERSION:
        guidance = (
            f"Set {_PROBLEMS_PATH_ENV_VAR} to the same flat problems "
            "directory used for this run and retry."
        )
    else:
        guidance = f"Run `slop-code sync {expected.version}` and retry."

    return (
        "Catalog mismatch for --resume.\n"
        f"Run expects version {expected.version} at commit {expected.commit}.\n"
        f"Installed catalog is version {installed_version} at commit {installed_commit}.\n"
        f"{guidance}"
    )


def _build_override_manifest(problem_root: Path) -> CatalogManifest:
    return CatalogManifest(
        version=_OVERRIDE_MANIFEST_VERSION,
        commit=str(problem_root.resolve()),
    )


def _get_validated_override_root() -> Path | None:
    override_root = get_override_problem_root()
    if override_root is None:
        return None
    _validate_override_problem_root(override_root)
    return override_root


def _validate_override_problem_root(problem_root: Path) -> None:
    if not problem_root.exists() or not problem_root.is_dir():
        raise CatalogError(
            f"{_PROBLEMS_PATH_ENV_VAR} must point to an existing directory: "
            f"{problem_root}"
        )
    if not discover_problem_dirs(problem_root):
        raise CatalogError(
            f"{_PROBLEMS_PATH_ENV_VAR} must point to a flat directory of "
            "problems (each direct child must contain config.yaml)."
        )


def _build_release(payload: dict[str, object]) -> ReleaseInfo:
    tag_name = payload.get("tag_name")
    tarball_url = payload.get("tarball_url")
    if not isinstance(tag_name, str) or not tag_name:
        raise CatalogError("GitHub release response missing tag_name")
    if not isinstance(tarball_url, str) or not tarball_url:
        raise CatalogError("GitHub release response missing tarball_url")
    return ReleaseInfo(
        version=tag_name,
        commit=_resolve_commit_sha(tag_name),
        tarball_url=tarball_url,
    )


def _resolve_commit_sha(version: str) -> str:
    payload = _get_json(f"{_COMMITS_URL}/{version}")
    sha = payload.get("sha")
    if not isinstance(sha, str) or not sha:
        raise CatalogError(f"GitHub commit lookup failed for {version}")
    return sha


def _get_json(url: str) -> dict[str, object]:
    try:
        response = httpx.get(
            url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise CatalogError(f"GitHub request failed for {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError(f"Unexpected GitHub response shape for {url}")
    return payload


def _download_release_tarball(url: str, destination: Path) -> None:
    try:
        response = httpx.get(
            url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        destination.write_bytes(response.content)
    except Exception as exc:  # noqa: BLE001
        raise CatalogError(
            f"Failed to download release tarball: {exc}"
        ) from exc


def _install_release(home: Path, release: ReleaseInfo) -> CatalogManifest:
    home.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="catalog-sync-", dir=home
    ) as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        tarball_path = tmp_dir / "release.tar.gz"
        extracted_path = tmp_dir / "extract"
        staged_catalog = tmp_dir / "problems"
        staged_manifest = tmp_dir / _MANIFEST_FILENAME

        _download_release_tarball(release.tarball_url, tarball_path)
        extracted_path.mkdir(parents=True, exist_ok=True)
        _extract_tarball(tarball_path, extracted_path)

        release_root = _resolve_extracted_root(extracted_path)
        problem_dirs = discover_problem_dirs(release_root)
        if not problem_dirs:
            raise CatalogError(
                "Release tarball did not contain any flat problem directories "
                "with config.yaml at the repo root."
            )

        staged_catalog.mkdir(parents=True, exist_ok=True)
        for problem_dir in problem_dirs:
            shutil.copytree(
                problem_dir,
                staged_catalog / problem_dir.name,
            )

        manifest = CatalogManifest(
            version=release.version,
            commit=release.commit,
        )
        _write_json_atomic(staged_manifest, manifest.to_payload())
        _promote_install(home, staged_catalog, staged_manifest)
        return manifest


def _extract_tarball(tarball_path: Path, extract_to: Path) -> None:
    try:
        with tarfile.open(tarball_path, "r:gz") as archive:
            archive.extractall(path=extract_to, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise CatalogError(f"Failed to extract release tarball: {exc}") from exc


def _resolve_extracted_root(extracted_path: Path) -> Path:
    dirs = [path for path in extracted_path.iterdir() if path.is_dir()]
    if len(dirs) != 1:
        raise CatalogError(
            "Expected exactly one top-level directory in release tarball."
        )
    return dirs[0]


def _promote_install(
    home: Path,
    staged_catalog: Path,
    staged_manifest: Path,
) -> None:
    catalog_root = get_catalog_root(home)
    manifest_path = get_manifest_path(home)

    stamp = f"{os.getpid()}-{time.time_ns()}"
    catalog_backup = home / f".problems.backup.{stamp}"
    manifest_backup = home / f".manifest.backup.{stamp}.json"
    had_catalog = catalog_root.exists()
    had_manifest = manifest_path.exists()

    try:
        if had_catalog:
            catalog_root.replace(catalog_backup)
        staged_catalog.replace(catalog_root)

        if had_manifest:
            manifest_path.replace(manifest_backup)
        staged_manifest.replace(manifest_path)
    except Exception as exc:  # noqa: BLE001
        _rollback_promotion(
            catalog_root=catalog_root,
            manifest_path=manifest_path,
            had_catalog=had_catalog,
            had_manifest=had_manifest,
            catalog_backup=catalog_backup,
            manifest_backup=manifest_backup,
        )
        raise CatalogError(
            f"Failed to promote staged catalog install: {exc}"
        ) from exc

    if catalog_backup.exists():
        shutil.rmtree(catalog_backup, ignore_errors=True)
    if manifest_backup.exists():
        manifest_backup.unlink(missing_ok=True)


def _rollback_promotion(
    *,
    catalog_root: Path,
    manifest_path: Path,
    had_catalog: bool,
    had_manifest: bool,
    catalog_backup: Path,
    manifest_backup: Path,
) -> None:
    if catalog_root.exists() and not had_catalog:
        shutil.rmtree(catalog_root, ignore_errors=True)
    if catalog_root.exists() and had_catalog:
        shutil.rmtree(catalog_root, ignore_errors=True)
    if had_catalog and catalog_backup.exists():
        catalog_backup.replace(catalog_root)

    if manifest_path.exists() and not had_manifest:
        manifest_path.unlink(missing_ok=True)
    if manifest_path.exists() and had_manifest:
        manifest_path.unlink(missing_ok=True)
    if had_manifest and manifest_backup.exists():
        manifest_backup.replace(manifest_path)


def _is_catalog_install_valid(catalog_root: Path) -> bool:
    return bool(discover_problem_dirs(catalog_root))


def _write_json_atomic(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(payload, tmp)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _print_install_metadata(
    manifest: CatalogManifest,
    catalog_root: Path,
    *,
    first_bootstrap: bool,
) -> None:
    typer.echo(
        f"Installed catalog version: {manifest.version}\n"
        f"Resolved commit: {manifest.commit}\n"
        f"Catalog path: {catalog_root}"
    )
    if first_bootstrap:
        typer.echo("Use `slop-code sync` to update the catalog later.")


@contextmanager
def _install_lock(home: Path) -> Iterator[None]:
    home.mkdir(parents=True, exist_ok=True)
    lock_path = home / _INSTALL_LOCK_FILENAME
    start = time.monotonic()
    fd: int | None = None

    while fd is None:
        try:
            fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            if time.monotonic() - start > _LOCK_TIMEOUT_SECONDS:
                raise CatalogError(
                    f"Timed out waiting for catalog lock: {lock_path}"
                )
            time.sleep(_LOCK_POLL_SECONDS)

    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
        yield
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)
