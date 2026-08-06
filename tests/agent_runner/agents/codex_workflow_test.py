"""Tests for declarative Codex skill workflows."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from pydantic import ValidationError

from slop_code.agent_runner.agents.codex.workflow import WorkflowConfig


def _workflow(**overrides: object) -> WorkflowConfig:
    values: dict[str, object] = {
        "type": "openspec",
        "version": "1.7.0",
        "install_commands": [
            ["npm", "install", "-g", "@fission-ai/openspec@1.7.0"]
        ],
        "init_commands": [["openspec", "init", ".", "--force"]],
        "env": {"CI": "true"},
        "skills": [
            {
                "name": "openspec-propose",
                "arguments": ["{task}", "Create every proposal artifact."],
            },
            {"name": "openspec-apply-change"},
            {
                "name": "openspec-archive-change",
                "arguments": ["Archive this change:", "{change_id}"],
            },
        ],
    }
    values.update(overrides)
    return WorkflowConfig.model_validate(values)


def test_workflow_setup_is_fully_declarative() -> None:
    workflow = _workflow()

    assert workflow.install_commands == (
        ("npm", "install", "-g", "@fission-ai/openspec@1.7.0"),
    )
    assert workflow.init_commands == (("openspec", "init", ".", "--force"),)
    assert workflow.env == {"CI": "true"}
    assert workflow.env_from_host == ()


def test_host_environment_variable_names_are_declarative() -> None:
    workflow = _workflow(
        env_from_host=["EMBEDDING_API_KEY", "NEO4J_PASSWORD"]
    )

    assert workflow.env_from_host == (
        "EMBEDDING_API_KEY",
        "NEO4J_PASSWORD",
    )
    assert "EMBEDDING_API_KEY" not in workflow.env


def test_resource_pool_assigns_values_in_problem_order() -> None:
    workflow = _workflow(
        resource_pool={
            "env_var": "ARTNET_NEO4J_URI",
            "values": [
                "bolt://neo4j:7687",
                "bolt://neo4j-exp1:7687",
                "bolt://neo4j-exp2:7687",
            ],
        }
    )

    assigned = workflow.allocate_problem_resources(["problem-b", "problem-a"])

    assert assigned.resource_assignments == {
        "problem-b": "bolt://neo4j:7687",
        "problem-a": "bolt://neo4j-exp1:7687",
    }
    assert assigned.resource_environment("problem-a") == {
        "ARTNET_NEO4J_URI": "bolt://neo4j-exp1:7687"
    }
    assert "resource_assignments" not in assigned.model_dump()


def test_resource_pool_rejects_more_problems_than_values() -> None:
    workflow = _workflow(
        resource_pool={
            "env_var": "ARTNET_NEO4J_URI",
            "values": ["bolt://neo4j:7687"],
        }
    )

    with pytest.raises(ValueError, match="1 values but 2 problems"):
        workflow.allocate_problem_resources(["problem-a", "problem-b"])


def test_resource_pool_has_no_fixed_size_limit_and_survives_pickling() -> None:
    values = [f"bolt://neo4j-{index}:7687" for index in range(6)]
    problems = [f"problem-{index}" for index in range(6)]
    workflow = _workflow(
        resource_pool={
            "env_var": "ARTNET_NEO4J_URI",
            "values": values,
        }
    ).allocate_problem_resources(problems)

    restored = pickle.loads(pickle.dumps(workflow))  # noqa: S301

    assert restored.resource_assignments == dict(
        zip(problems, values, strict=True)
    )


def test_resource_pool_requires_assignment_before_use() -> None:
    workflow = _workflow(
        resource_pool={
            "env_var": "ARTNET_NEO4J_URI",
            "values": ["bolt://neo4j:7687"],
        }
    )

    with pytest.raises(ValueError, match="No workflow resource assigned"):
        workflow.resource_environment("problem-a")


def test_local_package_hash_tracks_included_content(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    source = package / "index.js"
    source.write_text("export const value = 1;\n")
    ignored = package / "node_modules"
    ignored.mkdir()
    ignored_file = ignored / "dependency.js"
    ignored_file.write_text("ignored\n")
    workflow = _workflow(
        local_packages=[
            {
                "source": package,
                "target": "local-cli",
                "exclude": ["node_modules"],
            }
        ]
    )

    initial_hash = workflow.local_packages_hash()
    ignored_file.write_text("still ignored\n")

    assert workflow.local_packages_hash() == initial_hash

    source.write_text("export const value = 2;\n")

    assert workflow.local_packages_hash() != initial_hash
    local_package = workflow.local_packages[0]
    assert local_package.context_path == "workflow-packages/local-cli"
    assert local_package.container_path == (
        "/opt/workflow-packages/local-cli"
    )


def test_local_package_has_no_default_exclusions(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    modules = package / "node_modules"
    modules.mkdir()
    dependency = modules / "dependency.js"
    dependency.write_text("first\n")
    workflow = _workflow(
        local_packages=[{"source": package, "target": "local-cli"}]
    )

    initial_hash = workflow.local_packages_hash()
    dependency.write_text("second\n")

    assert workflow.local_packages[0].exclude == ()
    assert workflow.local_packages_hash() != initial_hash


def test_missing_local_package_is_rejected_when_image_is_resolved(
    tmp_path: Path,
) -> None:
    workflow = _workflow(
        local_packages=[
            {"source": tmp_path / "missing", "target": "local-cli"}
        ]
    )

    with pytest.raises(FileNotFoundError, match="does not exist"):
        workflow.local_packages_hash()


def test_nodes_only_receive_their_configured_argument() -> None:
    workflow = _workflow()
    propose, apply, archive = workflow.skills
    checkpoint = "Checkpoint 2 requires a searchable document index."

    propose_prompt = workflow.build_prompt(propose, checkpoint)
    apply_prompt = workflow.build_prompt(apply, checkpoint)
    archive_prompt = workflow.build_prompt(
        archive,
        checkpoint,
        "change-two",
    )

    assert propose_prompt.startswith("$openspec-propose\n")
    assert checkpoint in propose_prompt
    assert propose_prompt.index(checkpoint) < propose_prompt.index(
        "Create every proposal artifact."
    )
    assert apply_prompt.startswith("$openspec-apply-change\n")
    assert checkpoint not in apply_prompt
    assert archive_prompt.startswith("$openspec-archive-change\n")
    assert "change-two" in archive_prompt
    assert archive_prompt.index("Archive this change:") < archive_prompt.index(
        "change-two"
    )
    assert checkpoint not in archive_prompt
    assert all(
        "Never ask the user a question" in prompt
        for prompt in (propose_prompt, apply_prompt, archive_prompt)
    )
    assert all(
        "Complete only this workflow node" in prompt
        for prompt in (propose_prompt, apply_prompt, archive_prompt)
    )


def test_change_id_argument_is_required() -> None:
    workflow = _workflow()

    with pytest.raises(ValueError, match="change_id is required"):
        workflow.build_prompt(workflow.skills[-1], "task")


def test_required_skill_paths_follow_configuration() -> None:
    paths = _workflow().required_skill_paths(Path("/repo"))

    assert paths == (
        Path("/repo/.codex/skills/openspec-propose/SKILL.md"),
        Path("/repo/.codex/skills/openspec-apply-change/SKILL.md"),
        Path("/repo/.codex/skills/openspec-archive-change/SKILL.md"),
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"skills": []}, "at least one skill"),
        (
            {
                "skills": [
                    {"name": "same-skill"},
                    {"name": "same-skill"},
                ]
            },
            "must be unique",
        ),
        (
            {"init_commands": [[]]},
            "commands must contain non-empty arguments",
        ),
        (
            {"install_commands": [["npm", ""]]},
            "commands must contain non-empty arguments",
        ),
        (
            {"skills": [{"name": "valid-skill", "arguments": [""]}]},
            "workflow arguments must not be empty",
        ),
        (
            {"skills": [{"name": "Bad Name"}]},
            "lowercase kebab-case",
        ),
        (
            {
                "local_packages": [
                    {"source": ".", "target": "../unsafe"}
                ]
            },
            "single safe path component",
        ),
        (
            {
                "local_packages": [
                    {"source": ".", "target": "same"},
                    {"source": ".", "target": "same"},
                ]
            },
            "targets must be unique",
        ),
        (
            {"env_from_host": ["INVALID-NAME"]},
            "must be valid identifiers",
        ),
        (
            {"env_from_host": ["API_KEY", "API_KEY"]},
            "must be unique",
        ),
        (
            {
                "env": {"API_KEY": "literal"},
                "env_from_host": ["API_KEY"],
            },
            "cannot be configured in both",
        ),
        (
            {
                "env": {"ARTNET_NEO4J_URI": "literal"},
                "resource_pool": {
                    "env_var": "ARTNET_NEO4J_URI",
                    "values": ["bolt://neo4j:7687"],
                },
            },
            "resource pool env_var cannot also be configured",
        ),
        (
            {
                "resource_pool": {
                    "env_var": "ARTNET_NEO4J_URI",
                    "values": [
                        "bolt://neo4j:7687",
                        "bolt://neo4j:7687",
                    ],
                },
            },
            "resource pool values must be unique",
        ),
    ],
)
def test_invalid_workflow_configuration_is_rejected(
    override: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _workflow(**override)
