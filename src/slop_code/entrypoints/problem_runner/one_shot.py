from __future__ import annotations

from jinja2 import Template

from slop_code.entrypoints.config.run_config import OneShotConfig
from slop_code.evaluation import ProblemConfig


def apply_one_shot_mode(
    problem_config: ProblemConfig, one_shot: OneShotConfig
) -> ProblemConfig:
    """Return a problem config transformed for one-shot execution if enabled.

    When enabled, this collapses the problem into a single checkpoint using
    the final checkpoint's evaluation config but with a combined specification
    joined in checkpoint order.
    """
    if not one_shot.enabled:
        return problem_config

    checkpoints = list(problem_config.iterate_checkpoint_items())
    if len(checkpoints) <= 1:
        return problem_config

    prefix_template = Template(one_shot.prefix or "")
    combined_parts: list[str] = []
    for idx, (_, checkpoint) in enumerate(checkpoints, start=1):
        should_add_prefix = one_shot.include_first_prefix or idx > 1
        if should_add_prefix:
            rendered_prefix = prefix_template.render(idx=idx)
            separator = f"{rendered_prefix}\n" if rendered_prefix else "\n"
            combined_parts.append(separator)
        combined_parts.append(checkpoint.get_spec_text())

    combined_spec = "".join(combined_parts)

    last_name, last_checkpoint = checkpoints[-1]
    combined_checkpoint = last_checkpoint.model_copy(deep=True)
    combined_checkpoint.order = 1
    combined_checkpoint.spec_override = combined_spec

    return problem_config.model_copy(
        deep=True, update={"checkpoints": {last_name: combined_checkpoint}}
    )
