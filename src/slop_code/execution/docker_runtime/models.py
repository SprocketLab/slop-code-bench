from __future__ import annotations

import os
import platform
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.execution.models import EnvironmentSpec
from slop_code.logging import get_logger

logger = get_logger(__name__)

IMAGE_NAME_PREFIX = "slop-code"


class DockerConfig(BaseModel):
    """Docker-specific configuration for container execution.

    Attributes:
        image: Container image used for execution
        binary: Docker CLI binary used to launch containers
        workdir: Working directory inside the container
        mount_workspace: Whether to bind-mount workspace into container
        extra_mounts: Additional host-to-container mount mappings
        network: Docker network to attach the container to
        user: User specifier for docker run (e.g. '1000:1000')
        keep_container_after_clean: Prevents container removal after cleanup
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str = Field(
        description="Base container image used for execution.",
    )
    binary: str = Field(
        default="docker",
        description="Docker CLI binary used to launch containers.",
    )
    workdir: str = Field(
        default="/workspace",
        description="Working directory inside the container.",
    )
    mount_workspace: bool = Field(
        default=True,
        description="Whether to bind-mount workspace into container.",
    )
    extra_mounts: dict[str, str | dict[str, str]] = Field(
        default_factory=dict,
        description="Additional host-to-container mount mappings.",
    )
    network: str | None = Field(
        default=None,
        description="Docker network to attach the container to.",
    )
    user: str | None = Field(
        default=None,
        description="User specifier for docker run (e.g. '1000:1000').",
    )


class DockerEnvironmentSpec(EnvironmentSpec):
    """Container-based execution configuration.

    Attributes:
        docker: Docker-specific configuration (image, workdir, mounts, etc.)
    """

    type: Literal["docker"] = "docker"  # type: ignore[assignment]
    docker: DockerConfig

    def get_eval_user(self) -> str:
        if self.docker.user:
            return self.docker.user
        return "1000:1000"

    def get_actual_user(self) -> str:
        """Resolve the user to run as outside evaluation contexts."""
        if self.docker.user:
            return self.docker.user
        uid = os.getenv("HUID")
        gid = os.getenv("HGID")
        if uid and gid:
            return f"{uid}:{gid}"
        return "0:0"

    def get_effective_address(self, address: str) -> str:
        """Get the address to pass to commands inside the container.

        When using ``bridge`` networking and the caller requests a loopback
        address, we bind to all interfaces (``0.0.0.0``) so that the service is
        reachable via port mapping from the host.
        """
        if self.effective_network_mode() == "bridge" and address in (
            "127.0.0.1",
            "localhost",
        ):
            return "0.0.0.0"
        return address

    def effective_network_mode(self) -> str:
        desired = (
            self.docker.network if self.docker.network is not None else "bridge"
        )
        if desired == "host" and platform.system() != "Linux":
            logger.warning(
                "Host network mode unsupported on this platform; using bridge",
                platform=platform.system(),
            )
            return "bridge"
        return desired

    def get_base_image(self) -> str:
        return f"{IMAGE_NAME_PREFIX}:{self.name}"
