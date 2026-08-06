from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from docker.errors import BuildError
from docker.errors import ImageNotFound
from jinja2 import Template

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.docker_runtime.context import DockerContextEntry
from slop_code.execution.docker_runtime.models import IMAGE_NAME_PREFIX
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import EnvironmentSpec
from slop_code.logging import get_logger

logger = get_logger(__name__)

BASE_IMAGE_TEMPLATE = Path(__file__).parent / "setup_base.docker.j2"
AGENT_USER = "1000:1000"
BASE_IMAGE_HASH_LABEL = "io.slop-code.base-image-hash"

if TYPE_CHECKING:
    import docker
    from docker.models.images import Image


def _make_docker_context(
    docker_file: str,
    extra_arcs: Mapping[str, Path | DockerContextEntry] | None = None,
) -> io.BytesIO:
    logger.debug(
        "Making docker context", docker_file=docker_file, extra_arcs=extra_arcs
    )

    context_tar = io.BytesIO()
    with tarfile.open(fileobj=context_tar, mode="w") as tar:
        # Add Dockerfile
        dockerfile_data = docker_file.encode("utf-8")
        dockerfile_tarinfo = tarfile.TarInfo(name="Dockerfile")
        dockerfile_tarinfo.size = len(dockerfile_data)
        tar.addfile(
            dockerfile_tarinfo,
            io.BytesIO(dockerfile_data),
        )

        for arc_name, arc_value in (extra_arcs or {}).items():
            entry = (
                arc_value
                if isinstance(arc_value, DockerContextEntry)
                else DockerContextEntry(source=arc_value)
            )
            logger.debug(
                "Adding extra arc",
                arc_name=arc_name,
                arc_path=entry.source,
                excluded_names=entry.excluded_names,
            )
            tar.add(
                str(entry.source),
                arcname=arc_name,
                recursive=True,
                filter=_exclude_context_names(entry.excluded_names),
            )

    context_tar.seek(0)

    return context_tar


def _exclude_context_names(
    excluded_names: frozenset[str],
):
    """Build a tar filter that drops matching path components."""
    if not excluded_names:
        return None

    def include(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if any(part in excluded_names for part in Path(member.name).parts):
            return None
        return member

    return include


def _find_image(image_name: str, client: docker.DockerClient) -> Image | None:
    logger.info("Checking if image exists", image_name=image_name)
    try:
        found_image = client.images.get(image_name)
    except ImageNotFound:
        logger.info("Image does not exist", image_name=image_name)
        return None
    logger.debug(
        "Found image", image_name=image_name, found_image=found_image.id
    )
    return found_image


def _build_image(
    image_name: str, client: docker.DockerClient, context_tar: io.BytesIO
) -> Image:
    logger.info("Building image", image_name=image_name)
    try:
        image, build_logs = client.images.build(
            fileobj=context_tar,
            custom_context=True,
            tag=image_name,
            rm=True,
        )
    except ImageNotFound:
        logger.warning(
            "Docker SDK could not inspect the built image by id; "
            "falling back to tag lookup",
            image_name=image_name,
        )
        return client.images.get(image_name)
    except BuildError as e:
        logger.error("Failed to build image", image_name=image_name, error=e)
        raise e
    for msg in build_logs:
        logger.debug(msg)
    logger.info(
        "Finished building image", image_name=image_name, image_id=image.id
    )
    return image


def get_submission_image_name(submission_path: Path) -> str:
    hashed_submission = hashlib.sha256(
        submission_path.as_posix().encode("utf-8")
    ).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    return f"{IMAGE_NAME_PREFIX}:submission-{hashed_submission}-{timestamp}"


def _render_base_image(environment_spec: DockerEnvironmentSpec) -> str:
    return Template(BASE_IMAGE_TEMPLATE.read_text()).render(
        base_image=environment_spec.docker.image,
        env=environment_spec.environment.env,
    )


def _get_base_image_hash(environment_spec: DockerEnvironmentSpec) -> str:
    dockerfile = _render_base_image(environment_spec)
    return hashlib.sha256(dockerfile.encode("utf-8")).hexdigest()[:12]


def _get_image_labels(image: Image) -> dict[str, str]:
    attrs = getattr(image, "attrs", {})
    if not isinstance(attrs, dict):
        return {}
    config = attrs.get("Config")
    if not isinstance(config, dict):
        return {}
    labels = config.get("Labels")
    if not isinstance(labels, dict):
        return {}
    return {str(key): str(value) for key, value in labels.items()}


def _base_image_is_current(
    image: Image,
    environment_spec: DockerEnvironmentSpec,
) -> bool:
    labels = _get_image_labels(image)
    return labels.get(BASE_IMAGE_HASH_LABEL) == _get_base_image_hash(
        environment_spec
    )


def make_base_image(environment_spec: DockerEnvironmentSpec) -> str:
    dockerfile = _render_base_image(environment_spec).rstrip()
    return (
        f'{dockerfile}\n\nLABEL {BASE_IMAGE_HASH_LABEL}="'
        f'{_get_base_image_hash(environment_spec)}"\n'
    )


def make_submission_docker_file(
    env_spec: DockerEnvironmentSpec,
    base_image: str,
    static_assets: dict[str, ResolvedStaticAsset],
) -> str:
    lines = [
        f"FROM {base_image}",
        "",
        "# Set up workspace directory",
        f"RUN mkdir -p {env_spec.docker.workdir}",
    ]

    lines.append("# Copy static assets")
    if static_assets:
        lines.append("RUN mkdir -p /static")
        for asset in static_assets.values():
            lines.append(
                f"COPY --chown={AGENT_USER} {asset.save_path} /static/{str(asset.save_path)}"
            )

    lines.append("")
    lines.append("# Copy submission")
    lines.append(f"COPY --chown={AGENT_USER} submission submission")
    lines.append("ENV SUBMISSION_PATH=/submission")
    lines.append("WORKDIR /submission")

    lines.append(
        f"RUN {' && '.join(env_spec.get_setup_commands(is_evaluation=True))}"
    )

    lines.append(f"RUN chown -R {AGENT_USER} /submission")
    lines.append(f"WORKDIR {env_spec.docker.workdir}")
    lines.append(f"RUN chown -R {AGENT_USER} {env_spec.docker.workdir}")
    lines.append(f"RUN chown -R {AGENT_USER} /tmp")
    lines.append(f"USER {AGENT_USER}")

    return "\n".join(lines)


def build_base_image(
    client: docker.DockerClient,
    environment_spec: EnvironmentSpec,
    force_build: bool = False,  # noqa: FBT001, FBT002
) -> Image:
    if not isinstance(environment_spec, DockerEnvironmentSpec):
        raise ValueError("Environment spec must be a DockerEnvironmentSpec")

    image_name = environment_spec.get_base_image()
    logger.info(
        f"Building base image for environment '{environment_spec.name}'",
        image_name=image_name,
        base_image=environment_spec.docker.image,
    )
    found_image = _find_image(image_name, client)

    if found_image is not None and not force_build:
        if _base_image_is_current(found_image, environment_spec):
            logger.info("Found current image and not forcing build")
            return found_image
        logger.info(
            "Found stale image; rebuilding",
            image_name=image_name,
        )

    context_tar = _make_docker_context(make_base_image(environment_spec))
    return _build_image(image_name, client, context_tar)


def build_submission_image(
    client: docker.DockerClient,
    submission_path: Path,
    environment_spec: EnvironmentSpec,
    static_assets: dict[str, ResolvedStaticAsset],
    use_name: str | None = None,
    *,
    build_base: bool = False,
    force_build: bool = False,
) -> tuple[str, Image]:
    if not isinstance(environment_spec, DockerEnvironmentSpec):
        raise ValueError("Environment spec must be a DockerEnvironmentSpec")

    logger.info(
        f"Building submission image for {environment_spec.name}",
        submission_path=submission_path,
        static_assets=list(static_assets.keys()),
        build_base=build_base,
    )
    base_image = environment_spec.get_base_image()

    found_base_image = _find_image(base_image, client)
    if found_base_image is None:
        if not build_base and not force_build:
            raise ValueError(f"Base image {base_image} does not exist")
        build_base_image(client, environment_spec, force_build=force_build)
    elif force_build or not _base_image_is_current(
        found_base_image, environment_spec
    ):
        build_base_image(client, environment_spec, force_build=True)

    image_name = use_name or get_submission_image_name(submission_path)
    found_image = _find_image(image_name, client)
    if found_image is not None and not force_build:
        logger.info("Found submission image and not forcing build")
        return image_name, found_image

    dockerfile = make_submission_docker_file(
        environment_spec, base_image, static_assets
    )
    context_tar = _make_docker_context(
        dockerfile,
        {
            "submission": submission_path,
            **{
                str(asset.save_path): asset.absolute_path
                for asset in static_assets.values()
            },
        },
    )
    return image_name, _build_image(image_name, client, context_tar)


def build_image_from_str(
    client: docker.DockerClient,
    image_name: str,
    dockerfile: str,
    *,
    force_build: bool = False,
    extra_arcs: Mapping[str, Path | DockerContextEntry] | None = None,
) -> Image:
    found_image = _find_image(image_name, client)
    if found_image is not None and not force_build:
        logger.info("Found image and not forcing build")
        return found_image

    context_tar = _make_docker_context(dockerfile, extra_arcs)
    return _build_image(image_name, client, context_tar)
