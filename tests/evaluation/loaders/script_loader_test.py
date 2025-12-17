from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.evaluation.adapters.cli import CLIAdapterConfig
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.loaders import script_loader
from slop_code.evaluation.loaders.loader_protocol import LoaderError
from slop_code.protocol_loader import ProtocolLoadError


def _build_problem_and_checkpoint(tmp_path: Path) -> tuple[ProblemConfig, CheckpointConfig]:
    problem_dir = tmp_path / "script-problem"
    checkpoint_dir = problem_dir / "checkpoint-current"
    problem_dir.mkdir()
    checkpoint_dir.mkdir(parents=True)

    loader_path = problem_dir / "loader.py"
    loader_path.write_text("class Loader:\n    ...\n")
    entry_file = problem_dir / "entry.py"
    entry_file.write_text("print('hello')\n")

    group = GroupConfig(name="alpha")
    checkpoint_config = CheckpointConfig(
        version=1,
        order=1,
        path=checkpoint_dir,
        groups={group.name: group},
        constant_files=set(),
        specification="spec.md",
        state="Draft",
    )

    problem_config = ProblemConfig(
        name="ScriptProblem",
        path=problem_dir,
        version=1,
        description="demo",
        tags=["demo"],
        checkpoints={"checkpoint-current": checkpoint_config},
        entry_file=entry_file.name,
        loader_script=loader_path.name,
        loader_entrypoint="Loader",
        adapter=CLIAdapterConfig(),
    )

    return problem_config, checkpoint_config


class DummyLoader:
    def __init__(self, problem: ProblemConfig, checkpoint: CheckpointConfig, *, use_placeholders: bool = False):
        self.problem = problem
        self.checkpoint = checkpoint
        self.use_placeholders = use_placeholders

    def initialize_store(self):
        return object()

    def __call__(self, group, store):
        yield from ()


def test_get_script_loader_returns_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path)

    captured: dict[str, object] = {}

    def fake_load_protocol_entrypoint(protocol, module_path, entrypoint_name):
        captured["protocol"] = protocol
        captured["module_path"] = module_path
        captured["entrypoint_name"] = entrypoint_name
        return DummyLoader

    monkeypatch.setattr(
        script_loader,
        "load_protocol_entrypoint",
        fake_load_protocol_entrypoint,
    )

    loader = script_loader.get_script_loader(problem, checkpoint)

    assert isinstance(loader, DummyLoader)
    assert loader.problem is problem
    assert loader.checkpoint is checkpoint
    assert captured["protocol"].__name__ == "GroupLoader"
    assert captured["module_path"] == problem.path / problem.loader_script
    assert captured["entrypoint_name"] == problem.loader_entrypoint


def test_get_group_loader_source_files_returns_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path)

    monkeypatch.setattr(
        script_loader,
        "load_protocol_entrypoint",
        lambda protocol, module_path, entrypoint_name: DummyLoader,
    )

    load_results: dict[str, object] = {}

    def fake_get_source_files(*, module_path: Path, load_function):
        load_results["module_path"] = module_path
        loader_instance = load_function()
        load_results["loader_type"] = type(loader_instance)
        return {"loader.py": "print('ok')\n"}

    monkeypatch.setattr(script_loader, "get_source_files", fake_get_source_files)

    sources = script_loader.get_group_loader_source_files(problem, checkpoint)

    assert sources == {"loader.py": "print('ok')\n"}
    assert load_results["module_path"] == problem.path / problem.loader_script
    assert load_results["loader_type"] is DummyLoader


def test_get_group_loader_source_files_wraps_protocol_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path)

    def raise_protocol_error(*args, **kwargs):
        raise ProtocolLoadError("boom")

    monkeypatch.setattr(script_loader, "get_source_files", raise_protocol_error)

    with pytest.raises(LoaderError) as exc:
        script_loader.get_group_loader_source_files(problem, checkpoint)

    assert "Failed to get source files" in str(exc.value)
