"""Adapter implementations for invoking submissions under evaluation.

The evaluation runner delegates to adapters to start processes, manage
temporary working directories, and capture structured results. Adapters are
pluggable so new execution strategies (CLI, API, browser automation) can be
added without changing the higher-level orchestration code.

New adapters can be created by:
1. Subclassing BaseAdapter[CaseT, ResultT, ConfigT]
2. Implementing _execute_case()
3. Registering with @ADAPTER_REGISTRY.register("type_name")
"""

from typing import Annotated

from pydantic import Field

# Import adapter modules to trigger @register decorators
from slop_code.evaluation.adapters import api  # noqa: F401 - registers "api"
from slop_code.evaluation.adapters import cli  # noqa: F401 - registers "cli"
from slop_code.evaluation.adapters import (
    playwright,  # noqa: F401 - registers "playwright"
)
from slop_code.evaluation.adapters.api import APIAdapterConfig
from slop_code.evaluation.adapters.api import APICase
from slop_code.evaluation.adapters.api import APIResult
from slop_code.evaluation.adapters.base import ADAPTER_REGISTRY
from slop_code.evaluation.adapters.base import Adapter
from slop_code.evaluation.adapters.base import AdapterConfig
from slop_code.evaluation.adapters.base import AdapterError
from slop_code.evaluation.adapters.base import BaseAdapter
from slop_code.evaluation.adapters.cli import CLIAdapterConfig
from slop_code.evaluation.adapters.cli import CLICase
from slop_code.evaluation.adapters.cli import CLIResult
from slop_code.evaluation.adapters.models import DEFAULT_GROUP_TYPE
from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import CaseResult
from slop_code.evaluation.adapters.models import CaseResultError
from slop_code.evaluation.adapters.models import GroupType

AdapterConfigType = Annotated[
    CLIAdapterConfig | APIAdapterConfig,
    Field(discriminator="type"),
]
