"""AST-grep based pattern detection metrics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import yaml

from slop_code.logging import get_logger
from slop_code.metrics.models import AstGrepMetrics
from slop_code.metrics.models import AstGrepViolation

logger = get_logger(__name__)

RuleLookup = dict[str, dict[str, str | int]]

# Default rules directory (relative to project root)
AST_GREP_RULES_DIR = Path(__file__).parents[5] / "configs" / "ast-grep-rules"


def _is_sg_available() -> bool:
    """Check if ast-grep (sg) is available on the system."""
    return shutil.which("sg") is not None


def _get_ast_grep_rules_dir() -> Path:
    """Get the AST-grep rules directory, with env var override."""
    override = os.environ.get("AST_GREP_RULES_DIR")
    if override:
        return Path(override)
    return AST_GREP_RULES_DIR


def _count_rules_in_file(rule_file: Path) -> int:
    """Return the number of AST-grep rules in a (possibly multi-doc) file."""
    try:
        with rule_file.open(encoding="utf-8") as handle:
            return sum(1 for doc in yaml.safe_load_all(handle) if doc)
    except (OSError, yaml.YAMLError) as exc:
        logger.debug(
            "Failed to read AST-grep rule file",
            rule_file=str(rule_file),
            error=str(exc),
        )
        return 0


def calculate_ast_grep_metrics(source: Path) -> AstGrepMetrics:
    """Calculate AST-grep metrics using ast-grep rules.

    Runs ast-grep scan with rules from the ast-grep-rules directory
    and parses the JSON output to produce AstGrepMetrics.

    Args:
        source: Path to the Python source file.

    Returns:
        AstGrepMetrics with violations found, or empty metrics if sg
        unavailable.
    """
    if not _is_sg_available():
        logger.debug("ast-grep (sg) not available, skipping ast-grep metrics")
        return AstGrepMetrics(
            violations=[], total_violations=0, counts={}, rules_checked=0
        )

    rules_dir = _get_ast_grep_rules_dir()
    if not rules_dir.exists():
        logger.warning(
            "AST-grep rules directory not found",
            rules_dir=str(rules_dir),
        )
        return AstGrepMetrics(
            violations=[], total_violations=0, counts={}, rules_checked=0
        )

    # Count available rules (support grouped multi-document files)
    rule_files = sorted(rules_dir.glob("*.yaml"))
    rule_counts = {path: _count_rules_in_file(path) for path in rule_files}
    rules_checked = sum(rule_counts.values())

    if rules_checked == 0:
        return AstGrepMetrics(
            violations=[], total_violations=0, counts={}, rules_checked=0
        )

    # Build lookup to get correct category/subcategory/weight from rule files
    # (ast-grep's JSON output doesn't include rule metadata)
    rules_lookup = build_ast_grep_rules_lookup()

    violations: list[AstGrepViolation] = []
    counts: Counter[str] = Counter()
    logger.debug("Running ast-grep rules", rule_files=rule_files)

    # Run each rules file (may contain multiple rules separated by ---)
    for rule_file in rule_files:
        if rule_counts.get(rule_file, 0) == 0:
            continue
        try:
            result = subprocess.run(
                [
                    "sg",
                    "scan",
                    "--json=stream",
                    "-r",
                    str(rule_file),
                    str(source.absolute()),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as e:
            logger.debug(
                "Failed to run ast-grep rule",
                rule=rule_file.stem,
                error=str(e),
            )
            continue
        if result.returncode != 0:
            logger.warning(
                "Failed to run ast-grep rule",
                rule=rule_file.stem,
                error=result.stderr,
            )
            continue
        # Parse JSON stream output (one JSON object per line)
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                match = json.loads(line)
                rule_id = match.get("ruleId", rule_file.stem)
                rule_info = rules_lookup.get(rule_id, {})
                violation = AstGrepViolation(
                    rule_id=rule_id,
                    severity=match.get("severity", "warning"),
                    category=rule_info.get("category", rule_file.stem),
                    subcategory=rule_info.get("subcategory", "unknown"),
                    weight=rule_info.get("weight", 1),
                    line=match["range"]["start"]["line"],
                    column=match["range"]["start"]["column"],
                    end_line=match["range"]["end"]["line"],
                    end_column=match["range"]["end"]["column"],
                )
                violations.append(violation)
                counts[violation.rule_id] += 1
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    "Failed to parse ast-grep output",
                    line=line,
                    error=str(e),
                )
                continue

    return AstGrepMetrics(
        violations=violations,
        total_violations=len(violations),
        counts=dict(counts),
        rules_checked=rules_checked,
    )


def build_ast_grep_rules_lookup() -> RuleLookup:
    """Build lookup table mapping rule_id to category/subcategory/weight.

    Parses all YAML files in the ast-grep-rules directory and extracts
    metadata for each rule. This is used for backfilling ast_grep.jsonl
    files with correct category/subcategory information.

    Returns:
        Dict mapping rule_id to {"category": str, "subcategory": str,
        "weight": int} where category is derived from the filename and
        subcategory from the rule's metadata.category field.
    """
    rules_dir = _get_ast_grep_rules_dir()
    if not rules_dir.exists():
        logger.warning(
            "AST-grep rules directory not found",
            rules_dir=str(rules_dir),
        )
        return {}

    lookup: RuleLookup = {}
    rule_files = sorted(rules_dir.glob("*.yaml"))

    for rule_file in rule_files:
        category = rule_file.stem
        try:
            with rule_file.open(encoding="utf-8") as handle:
                for doc in yaml.safe_load_all(handle):
                    if not doc:
                        continue
                    rule_id = doc.get("id")
                    if not rule_id:
                        continue
                    metadata = doc.get("metadata", {})
                    lookup[rule_id] = {
                        "category": category,
                        "subcategory": metadata.get("category", category),
                        "weight": metadata.get("weight", 1),
                    }
        except (OSError, yaml.YAMLError) as exc:
            logger.warning(
                "Failed to parse AST-grep rule file for lookup",
                rule_file=str(rule_file),
                error=str(exc),
            )
            continue

    logger.debug(
        "Built AST-grep rules lookup",
        rules_count=len(lookup),
    )
    return lookup
