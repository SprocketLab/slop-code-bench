"""Tests for Docker image build caching."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from docker.errors import ImageNotFound

from slop_code.execution.docker_runtime.context import DockerContextEntry
from slop_code.execution.docker_runtime.images import BASE_IMAGE_HASH_LABEL
from slop_code.execution.docker_runtime.images import _build_image
from slop_code.execution.docker_runtime.images import _get_base_image_hash
from slop_code.execution.docker_runtime.images import _make_docker_context
from slop_code.execution.docker_runtime.images import build_base_image
from slop_code.execution.docker_runtime.images import build_submission_image
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec


def _mock_image(hash_value: str | None) -> MagicMock:
    image = MagicMock()
    labels = {} if hash_value is None else {BASE_IMAGE_HASH_LABEL: hash_value}
    image.attrs = {"Config": {"Labels": labels}}
    return image


def test_build_base_image_reuses_current_image(
    docker_spec: DockerEnvironmentSpec,
) -> None:
    client = MagicMock()
    current_hash = _get_base_image_hash(docker_spec)
    current_image = _mock_image(current_hash)

    with (
        patch(
            "slop_code.execution.docker_runtime.images._find_image",
            return_value=current_image,
        ),
        patch(
            "slop_code.execution.docker_runtime.images._build_image"
        ) as build,
    ):
        result = build_base_image(client, docker_spec)

    assert result is current_image
    build.assert_not_called()


def test_build_base_image_rebuilds_stale_image(
    docker_spec: DockerEnvironmentSpec,
) -> None:
    client = MagicMock()
    stale_image = _mock_image(None)
    rebuilt_image = MagicMock()

    with (
        patch(
            "slop_code.execution.docker_runtime.images._find_image",
            return_value=stale_image,
        ),
        patch(
            "slop_code.execution.docker_runtime.images._build_image",
            return_value=rebuilt_image,
        ) as build,
    ):
        result = build_base_image(client, docker_spec)

    assert result is rebuilt_image
    build.assert_called_once()


def test_build_submission_image_rebuilds_stale_base_image(
    docker_spec: DockerEnvironmentSpec,
    tmp_path: Path,
) -> None:
    client = MagicMock()
    submission_path = tmp_path / "submission"
    submission_path.mkdir()
    (submission_path / "solution.py").write_text("print('ok')\n")

    stale_base_image = _mock_image(None)
    submission_image = MagicMock()

    with (
        patch(
            "slop_code.execution.docker_runtime.images._find_image",
            side_effect=[stale_base_image, None],
        ),
        patch(
            "slop_code.execution.docker_runtime.images.build_base_image",
            return_value=MagicMock(),
        ) as build_base,
        patch(
            "slop_code.execution.docker_runtime.images._build_image",
            return_value=submission_image,
        ),
    ):
        image_name, built_image = build_submission_image(
            client,
            submission_path,
            docker_spec,
            {},
            build_base=False,
        )

    assert image_name.startswith("slop-code:submission-")
    assert built_image is submission_image
    build_base.assert_called_once_with(
        client,
        docker_spec,
        force_build=True,
    )


def test_build_image_falls_back_to_tag_lookup_after_sdk_image_not_found() -> (
    None
):
    client = MagicMock()
    tagged_image = MagicMock()
    client.images.build.side_effect = ImageNotFound("missing")
    client.images.get.return_value = tagged_image

    result = _build_image(
        "slop-code:test-image",
        client,
        io.BytesIO(b"docker context"),
    )

    assert result is tagged_image
    client.images.get.assert_called_once_with("slop-code:test-image")


def test_docker_context_excludes_local_package_development_files(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text("{}\n")
    modules = package / "node_modules"
    modules.mkdir()
    (modules / "dependency.js").write_text("large dependency\n")

    context = _make_docker_context(
        "FROM scratch\n",
        {
            "workflow-packages/package": DockerContextEntry(
                source=package,
                excluded_names=frozenset({"node_modules"}),
            )
        },
    )

    with tarfile.open(fileobj=context, mode="r") as archive:
        names = archive.getnames()

    assert "Dockerfile" in names
    assert "workflow-packages/package/package.json" in names
    assert all("node_modules" not in name for name in names)
