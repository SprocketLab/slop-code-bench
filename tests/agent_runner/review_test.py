"""Tests for the verification-layers reviewer and the in-loop review hook."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code.agent_runner import runner
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.review import ReviewConfig
from slop_code.agent_runner.review import ReviewFinding
from slop_code.agent_runner.review import ReviewResult
from slop_code.agent_runner.review import Reviewer
from slop_code.agent_runner.review import collect_workspace
from slop_code.agent_runner.review import feedback_prompt
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition


def _model_def() -> ModelDefinition:
    return ModelDefinition(
        internal_name="claude-sonnet-5",
        provider="anthropic",
        pricing=APIPricing(input=3, output=15, cache_read=0.3, cache_write=3.75),
        thinking_style="effort",
    )


def _credential(provider: str = "anthropic") -> ProviderCredential:
    return ProviderCredential(
        provider=provider,
        value="key",
        source="ENV",
        destination_key="ANTHROPIC_API_KEY",
        credential_type=CredentialType.ENV_VAR,
    )


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _FakeClient:
    def __init__(self, message):
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._message = message

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStream(self._message)


def _message(content, stop_reason="tool_use"):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _tool_call(payload):
    return SimpleNamespace(type="tool_use", name="submit_review", input=payload)


def test_collect_workspace_skips_venv_and_binaries(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('hi')")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("junk")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01")
    block, truncated = collect_workspace(tmp_path)
    assert 'path="main.py"' in block
    assert "junk" not in block
    assert "blob.bin" not in block
    assert truncated == []


def test_reviewer_parses_rejection_and_costs_it(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('hi')")
    reviewer = Reviewer(
        ReviewConfig(enabled=True), _model_def(), _credential(), "medium"
    )
    finding = {
        "category": "correctness",
        "location": "main.py",
        "problem": "prints hi, spec says hello",
        "evidence": "checkpoint_1: print hello",
    }
    reviewer._client = _FakeClient(
        _message([_tool_call({"verdict": "reject", "findings": [finding]})])
    )
    result = reviewer.review([("checkpoint_1", "print hello")], tmp_path)

    assert result.rejected
    assert result.findings[0].location == "main.py"
    assert result.cost == pytest.approx(3.0)
    call = reviewer._client.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert call["extra_body"]["output_config"] == {"effort": "medium"}
    assert "print hello" in call["messages"][0]["content"]


def test_reviewer_without_tool_call_is_an_error_not_a_verdict(tmp_path: Path):
    reviewer = Reviewer(ReviewConfig(enabled=True), _model_def(), _credential(), None)
    reviewer._client = _FakeClient(
        _message([SimpleNamespace(type="text", text="looks fine")], "end_turn")
    )
    result = reviewer.review([("checkpoint_1", "spec")], tmp_path)
    assert result.verdict == "error"
    assert not result.rejected


class _ScriptedReviewer:
    def __init__(self, verdicts: list[str], max_rounds: int = 2):
        self.config = ReviewConfig(enabled=True, max_rounds=max_rounds)
        self._verdicts = list(verdicts)
        self.calls = 0

    def review(self, specs, workspace):
        self.calls += 1
        verdict = self._verdicts.pop(0)
        findings = (
            [ReviewFinding(category="spec", location="a.py", problem="p", evidence="e")]
            if verdict == "reject"
            else []
        )
        return ReviewResult(verdict=verdict, findings=findings, model="m", cost=0.5)


class _RecordingAgent:
    def __init__(self):
        self.follow_ups: list[str] = []

    def continue_with(self, prompt: str) -> None:
        self.follow_ups.append(prompt)


@pytest.mark.parametrize(
    ("verdicts", "max_rounds", "reviews", "send_backs"),
    [
        (["approve"], 2, 1, 0),
        (["reject", "approve"], 2, 2, 1),
        # After the last allowed send-back there is no further review.
        (["reject", "reject"], 2, 2, 2),
        (["reject"], 1, 1, 1),
        (["error"], 2, 1, 0),
    ],
)
def test_review_loop_rounds(tmp_path, verdicts, max_rounds, reviews, send_backs):
    reviewer = _ScriptedReviewer(verdicts, max_rounds)
    agent = _RecordingAgent()
    runner._run_review_loop(
        agent=agent,
        reviewer=reviewer,
        specs=[("checkpoint_1", "spec")],
        workspace=tmp_path,
        save_dir=tmp_path / "out",
        checkpoint_name="checkpoint_1",
    )
    saved = json.loads((tmp_path / "out" / "review.json").read_text())
    assert reviewer.calls == reviews
    assert len(agent.follow_ups) == send_backs
    assert len(saved["rounds"]) == reviews
    assert saved["review_cost"] == pytest.approx(0.5 * reviews)
    if send_backs:
        assert "a.py" in agent.follow_ups[0]


def test_feedback_prompt_lists_every_finding():
    result = ReviewResult(
        verdict="reject",
        model="m",
        findings=[
            ReviewFinding(category="correctness", location="x.py", problem="p1", evidence="e1"),
            ReviewFinding(category="quality", location="y.py", problem="p2", evidence="e2"),
        ],
    )
    text = feedback_prompt(result)
    assert "x.py" in text and "y.py" in text
