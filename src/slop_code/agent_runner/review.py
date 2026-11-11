"""Code review as a verification layer.

One reviewer serves two uses, so the in-loop number and the shadow number
measure the same thing:

- In loop (``review.enabled``): after the agent finishes a checkpoint, a fresh
  model call reviews the workspace against every specification so far. A
  rejection goes back to the same agent session as a follow-up message, at most
  ``max_rounds`` times.
- Shadow: ``Reviewer.review`` on a finished snapshot from a script, with
  nothing sent back, so a run without a reviewer still yields what a reviewer
  would have said. Comparing that with the hidden tests gives the reviewer's
  precision and recall.

The reviewer reads code and does not run it: it is the cheapest layer that is
independent of the author's context.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError

from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import TokenUsage
from slop_code.logging import get_logger

logger = get_logger(__name__)

_EXCLUDED_PARTS = {
    "__pycache__",
    ".venv",
    "venv",
    ".git",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
_TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".yaml",
    ".yml",
    ".sh",
    ".sql",
}
_MAX_FILE_CHARS = 60_000
_MAX_TOTAL_CHARS = 400_000

REVIEW_SYSTEM_PROMPT = """You review code another engineer wrote, before it ships. You are adversarial: your job is to find what is wrong, not to be agreeable. You did not write this code and owe it nothing.

The engineer was given the specifications below, one per iteration, and the code must satisfy all of them as they now stand (a later specification can change an earlier one). Hidden tests will exercise the program exactly as the specifications describe it.

Reject when you find at least one defect worth sending the work back for:
- correctness: an input the specifications cover on which the program would behave wrongly, crash, or print the wrong output or format;
- spec: required behavior that is missing or contradicts the specifications;
- quality: a structural problem serious enough that the next iteration will be materially harder to build (duplicated logic that must change in step, a god function that every feature lands in, dead code paths). Do not reject for style or taste.

Approve when you find nothing in those categories. Never reject for something you cannot point to in the code. When you are unsure whether a behavior is required, the specifications decide.

Report through the submit_review tool, exactly once, as the last thing you do."""

_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_review",
    "description": "Submit the review verdict and its findings.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": ["approve", "reject"]},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["correctness", "spec", "quality"],
                        },
                        "location": {
                            "type": "string",
                            "description": "File and function or line.",
                        },
                        "problem": {"type": "string"},
                        "evidence": {
                            "type": "string",
                            "description": "The spec text or input that shows it.",
                        },
                    },
                    "required": ["category", "location", "problem", "evidence"],
                },
            },
        },
        "required": ["verdict", "findings"],
    },
}


class ReviewConfig(BaseModel):
    """Run-config block for the in-loop reviewer (the adversarial-review arm)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    max_rounds: int = Field(default=2, ge=1)
    effort: str | None = Field(
        default=None,
        description="Reviewer effort; defaults to the run's thinking preset.",
    )
    max_tokens: int = 32_000


class ReviewFinding(BaseModel):
    category: Literal["correctness", "spec", "quality"]
    location: str
    problem: str
    evidence: str = ""


class ReviewResult(BaseModel):
    verdict: Literal["approve", "reject", "error"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    error: str | None = None
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float = 0.0
    truncated_files: list[str] = Field(default_factory=list)
    skipped_findings: int = 0

    @property
    def rejected(self) -> bool:
        return self.verdict == "reject"


def parse_findings(raw: Any) -> tuple[list[ReviewFinding], int]:
    """Read the findings of a ``submit_review`` call, tolerating bad items.

    The tool schema is a request, not a guarantee: a model sometimes returns a
    finding as a bare string or leaves a field out. One malformed finding must
    not end the problem, so it is skipped and counted instead. A finding
    without ``evidence`` is kept, with the evidence left empty.

    Returns the findings that parsed and the number that were skipped.
    """
    if not isinstance(raw, list):
        return [], 0 if raw is None else 1
    findings: list[ReviewFinding] = []
    skipped = 0
    for item in raw:
        if not isinstance(item, dict):
            skipped += 1
            continue
        try:
            findings.append(ReviewFinding(**item))
        except (ValidationError, TypeError):
            skipped += 1
    return findings, skipped


def collect_workspace(root: Path) -> tuple[str, list[str]]:
    """Render the workspace's text files as one prompt block.

    Returns the block and the files that were cut to fit.
    """
    parts: list[str] = []
    truncated: list[str] = []
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_dir() or _EXCLUDED_PARTS.intersection(rel.parts):
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if len(text) > _MAX_FILE_CHARS or total + len(text) > _MAX_TOTAL_CHARS:
            truncated.append(str(rel))
            text = text[: max(0, min(_MAX_FILE_CHARS, _MAX_TOTAL_CHARS - total))]
        total += len(text)
        parts.append(f'<file path="{rel}">\n{text}\n</file>')
    return "\n\n".join(parts), truncated


def render_review_request(specs: list[tuple[str, str]], workspace: str) -> str:
    spec_blocks = "\n\n".join(
        f'<specification iteration="{i}" name="{name}">\n{text.strip()}\n</specification>'
        for i, (name, text) in enumerate(specs, start=1)
    )
    return (
        f"{spec_blocks}\n\n<workspace>\n{workspace}\n</workspace>\n\n"
        "Review the workspace against the specifications, then call submit_review."
    )


def feedback_prompt(result: ReviewResult) -> str:
    """The follow-up the implementer gets when its work is rejected."""
    lines = [
        "A reviewer read your code against the specification and sent it back. "
        "Fix each real defect below. If one is wrong, leave the code as it is "
        "and say why in one sentence. Then finish as you normally would.",
        "",
    ]
    for finding in result.findings:
        line = f"- [{finding.category}] {finding.location}: {finding.problem}"
        if finding.evidence:
            line += f" (evidence: {finding.evidence})"
        lines.append(line)
    return "\n".join(lines)


class Reviewer:
    """Calls one model through the run's own provider and credential."""

    def __init__(
        self,
        config: ReviewConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
        thinking_preset: str | None,
    ) -> None:
        self.config = config
        self.model_def = model_def
        self.credential = credential
        self.model = model_def.get_model_slug(credential.provider)
        self.effort = config.effort or (
            thinking_preset
            if thinking_preset in {"low", "medium", "high", "xhigh", "max"}
            else None
        )
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        provider = self.credential.provider
        if provider == "vertex":
            from anthropic import AnthropicVertex

            os.environ.setdefault(
                "GOOGLE_APPLICATION_CREDENTIALS", self.credential.value
            )
            self._client = AnthropicVertex(
                project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
                region=os.environ.get("CLOUD_ML_REGION", "global"),
            )
        elif provider == "anthropic":
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.credential.value)
        else:
            raise ValueError(
                f"Reviewer supports the vertex and anthropic providers, not {provider}"
            )
        return self._client

    def review(
        self, specs: list[tuple[str, str]], workspace_dir: Path
    ) -> ReviewResult:
        workspace, truncated = collect_workspace(workspace_dir)
        extra_body: dict[str, Any] = {"thinking": {"type": "adaptive"}}
        if self.effort:
            extra_body["output_config"] = {"effort": self.effort}
        try:
            with self._get_client().messages.stream(
                model=self.model,
                max_tokens=self.config.max_tokens,
                system=REVIEW_SYSTEM_PROMPT,
                tools=[_REVIEW_TOOL],
                messages=[
                    {
                        "role": "user",
                        "content": render_review_request(specs, workspace),
                    }
                ],
                extra_body=extra_body,
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - a failed review is data, not a crash
            logger.error("review.call_failed", error=str(exc), model=self.model)
            return ReviewResult(
                verdict="error",
                error=f"{type(exc).__name__}: {exc}",
                model=self.model,
                truncated_files=truncated,
            )

        usage = TokenUsage(
            input=message.usage.input_tokens or 0,
            output=message.usage.output_tokens or 0,
            cache_read=getattr(message.usage, "cache_read_input_tokens", 0)
            or 0,
            cache_write=getattr(message.usage, "cache_creation_input_tokens", 0)
            or 0,
        )
        cost = (
            self.model_def.pricing.get_cost(usage)
            if self.model_def.pricing
            else 0.0
        )
        call = next(
            (
                block
                for block in message.content
                if block.type == "tool_use" and block.name == "submit_review"
            ),
            None,
        )
        if call is None:
            return ReviewResult(
                verdict="error",
                error=f"no submit_review call (stop_reason={message.stop_reason})",
                model=self.model,
                usage=usage,
                cost=cost,
                truncated_files=truncated,
            )
        payload = call.input if isinstance(call.input, dict) else json.loads(call.input)
        findings, skipped = parse_findings(payload.get("findings"))
        if skipped:
            logger.warning(
                "review.findings_skipped",
                skipped=skipped,
                kept=len(findings),
                model=self.model,
            )
        return ReviewResult(
            verdict=payload["verdict"],
            findings=findings,
            model=self.model,
            usage=usage,
            cost=cost,
            truncated_files=truncated,
            skipped_findings=skipped,
        )


def specs_through(problem: Any, checkpoint_name: str) -> list[tuple[str, str]]:
    """Every checkpoint specification up to and including ``checkpoint_name``."""
    specs: list[tuple[str, str]] = []
    for name, _ in problem.iterate_checkpoint_items():
        specs.append((name, problem.get_checkpoint_spec(name)))
        if name == checkpoint_name:
            break
    return specs
