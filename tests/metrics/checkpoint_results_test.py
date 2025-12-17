"""Tests for checkpoint metric extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_code.common import AST_GREP_QUALITY_SAVENAME
from slop_code.common import FILES_QUALITY_SAVENAME
from slop_code.common import QUALITY_DIR
from slop_code.common import QUALITY_METRIC_SAVENAME
from slop_code.common import SYMBOLS_QUALITY_SAVENAME
from slop_code.metrics.checkpoint_results import compute_checkpoint_delta
from slop_code.metrics.checkpoint_results import get_checkpoint_metrics
from slop_code.metrics.checkpoint_results import get_evaluation_metrics
from slop_code.metrics.checkpoint_results import get_quality_metrics
from slop_code.metrics.checkpoint_results import get_rubric_metrics


class TestGetEvaluationMetrics:
    """Tests for get_evaluation_metrics function."""

    @pytest.fixture
    def sample_eval_file(self, tmp_path: Path) -> Path:
        data = {
            "pass_counts": {
                "Core": 3,
                "Functionality": 2,
                "Error": 1,
                "Regression": 0,
            },
            "total_counts": {
                "Core": 3,
                "Functionality": 3,
                "Error": 2,
                "Regression": 1,
            },
            "duration": 5.5,
        }
        eval_file = tmp_path / "evaluation.json"
        eval_file.write_text(json.dumps(data))
        return tmp_path

    def test_returns_flat_tests(self, sample_eval_file: Path):
        result = get_evaluation_metrics(sample_eval_file)

        assert result["total_tests"] == 9
        assert result["passed_tests"] == 6
        assert result["core_total"] == 3
        assert result["core_passed"] == 3
        assert result["functionality_total"] == 3
        assert result["functionality_passed"] == 2
        assert result["error_total"] == 2
        assert result["error_passed"] == 1
        assert result["regression_total"] == 1
        assert result["regression_passed"] == 0

    def test_pass_rates(self, sample_eval_file: Path):
        result = get_evaluation_metrics(sample_eval_file)

        assert result["pass_rate"] == 6 / 9
        assert result["core_pass_rate"] == 1.0
        # checkpoint_pass_rate excludes regression
        assert result["checkpoint_pass_rate"] == 6 / 8

    def test_duration(self, sample_eval_file: Path):
        result = get_evaluation_metrics(sample_eval_file)
        assert result["duration"] == 5.5

    def test_missing_file(self, tmp_path: Path):
        result = get_evaluation_metrics(tmp_path)
        assert result == {}


def _create_quality_test_files(tmp_path: Path, files_data: dict) -> Path:
    """Helper to create quality_analysis directory with flat files.

    Creates files matching the new flat file structure:
    - quality_analysis/overall_quality.json
    - quality_analysis/files.jsonl (flat file metrics)
    - quality_analysis/symbols.jsonl (flat symbol metrics)
    - quality_analysis/ast_grep.jsonl (flat AST-grep violations)
    """
    # Compute aggregates from file data
    file_count = len(files_data)
    total_lines = sum(f["lines"]["total_lines"] for f in files_data.values())
    total_loc = sum(f["lines"]["loc"] for f in files_data.values())
    total_comments = sum(
        f["lines"]["single_comment"] + f["lines"]["multi_comment"]
        for f in files_data.values()
    )
    total_single_comments = sum(
        f["lines"]["single_comment"] for f in files_data.values()
    )
    total_multi_comments = sum(
        f["lines"]["multi_comment"] for f in files_data.values()
    )
    total_lint_errors = sum(f["lint"]["errors"] for f in files_data.values())
    total_lint_fixable = sum(f["lint"]["fixable"] for f in files_data.values())

    # Symbol aggregates
    total_symbols = 0
    function_count = 0
    method_count = 0
    class_count = 0
    variable_count = 0
    type_alias_count = 0
    total_statements = 0
    total_expressions_top_level = 0
    total_expressions = 0
    cc_sum = 0
    cc_max = 0
    num_complex = 0
    cc_ratings = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
    mi_ratings = {"A": 0, "B": 0, "C": 0}
    mi_sum = 0.0
    mi_min = float("inf")

    # Lists for FunctionAggregates and ClassAggregates
    func_lines: list[int] = []
    func_control_blocks: list[int] = []
    func_depths: list[int] = []
    func_branches: list[int] = []
    func_complexity: list[int] = []
    class_method_counts: list[int] = []
    class_attribute_counts: list[int] = []

    for fm in files_data.values():
        mi_sum += fm["mi"]
        mi_min = min(mi_min, fm["mi"])
        if fm["mi"] >= 19:
            mi_ratings["A"] += 1
        elif fm["mi"] > 9:
            mi_ratings["B"] += 1
        else:
            mi_ratings["C"] += 1

        for s in fm["symbols"]:
            total_symbols += 1
            total_statements += s.get("statements", 0)
            total_expressions_top_level += s.get("expressions_top_level", 0)
            total_expressions += s.get("expressions_total", 0)

            cc = s["complexity"]
            cc_sum += cc
            cc_max = max(cc_max, cc)
            if cc > 10:
                num_complex += 1

            # CC rating
            if cc <= 5:
                cc_ratings["A"] += 1
            elif cc <= 10:
                cc_ratings["B"] += 1
            elif cc <= 20:
                cc_ratings["C"] += 1
            elif cc <= 30:
                cc_ratings["D"] += 1
            elif cc <= 40:
                cc_ratings["E"] += 1
            else:
                cc_ratings["F"] += 1

            sym_type = s["type"]
            if sym_type == "function":
                function_count += 1
                func_complexity.append(cc)
                if "lines" in s:
                    func_lines.append(s["lines"])
                if "control_blocks" in s:
                    func_control_blocks.append(s["control_blocks"])
                if "max_nesting_depth" in s:
                    func_depths.append(s["max_nesting_depth"])
                if "branches" in s:
                    func_branches.append(s["branches"])
            elif sym_type == "method":
                method_count += 1
                func_complexity.append(cc)
                if "lines" in s:
                    func_lines.append(s["lines"])
                if "control_blocks" in s:
                    func_control_blocks.append(s["control_blocks"])
                if "max_nesting_depth" in s:
                    func_depths.append(s["max_nesting_depth"])
                if "branches" in s:
                    func_branches.append(s["branches"])
            elif sym_type == "class":
                class_count += 1
                if s.get("method_count") is not None:
                    class_method_counts.append(s["method_count"])
                if s.get("attribute_count") is not None:
                    class_attribute_counts.append(s["attribute_count"])
            elif sym_type == "variable":
                variable_count += 1
            elif sym_type == "type_alias":
                type_alias_count += 1

    # Waste/redundancy/ast_grep aggregates
    total_single_use_functions = sum(
        f.get("waste", {}).get("single_use_count", 0)
        for f in files_data.values()
    )
    total_trivial_wrappers = sum(
        f.get("waste", {}).get("trivial_wrapper_count", 0)
        for f in files_data.values()
    )
    total_single_method_classes = sum(
        f.get("waste", {}).get("single_method_class_count", 0)
        for f in files_data.values()
    )
    total_clone_instances = sum(
        f.get("redundancy", {}).get("total_clone_instances", 0)
        for f in files_data.values()
    )
    total_clone_lines = sum(
        f.get("redundancy", {}).get("clone_lines", 0)
        for f in files_data.values()
    )
    clone_ratio_sum = sum(
        f.get("redundancy", {}).get("clone_ratio", 0)
        for f in files_data.values()
        if f.get("redundancy")
    )
    files_with_clones = sum(
        1 for f in files_data.values() if f.get("redundancy")
    )
    total_ast_grep_violations = sum(
        f.get("ast_grep", {}).get("total_violations", 0)
        for f in files_data.values()
    )
    ast_grep_rules_checked = max(
        (
            f.get("ast_grep", {}).get("rules_checked", 0)
            for f in files_data.values()
        ),
        default=0,
    )
    total_imports = sum(f.get("import_count", 0) for f in files_data.values())
    max_imports = max(
        (f.get("import_count", 0) for f in files_data.values()), default=0
    )
    total_globals = sum(f.get("global_count", 0) for f in files_data.values())

    if mi_min == float("inf"):
        mi_min = 0.0

    # Build SnapshotMetrics-compatible structure (no "aggregates" wrapper)
    quality_data = {
        "file_count": file_count,
        "source_file_count": file_count,
        "lines": {
            "total_lines": total_lines,
            "loc": total_loc,
            "comments": total_comments,
            "single_comment": total_single_comments,
            "multi_comment": total_multi_comments,
        },
        "lint": {
            "errors": total_lint_errors,
            "fixable": total_lint_fixable,
            "counts": {},
        },
        "symbols": {
            "total": total_symbols,
            "functions": function_count,
            "methods": method_count,
            "classes": class_count,
            "variables": variable_count,
            "type_aliases": type_alias_count,
            "statements": total_statements,
            "expressions_top_level": total_expressions_top_level,
            "expressions": total_expressions,
            "imports": total_imports,
            "max_imports": max_imports,
            "globals": total_globals,
        },
        "functions": {
            "count": len(func_complexity),
            "cc_sum": sum(func_complexity) if func_complexity else 0,
            "cc_max": max(func_complexity) if func_complexity else 0,
            "cc_mean": (
                sum(func_complexity) / len(func_complexity)
                if func_complexity
                else 0.0
            ),
            "cc_std": 0.0,  # Simplified for tests
            "cc_high_count": sum(1 for c in func_complexity if c > 10),
            "cc_extreme_count": sum(1 for c in func_complexity if c > 30),
            "high_cc_mean": (
                sum(c for c in func_complexity if c > 10)
                / sum(1 for c in func_complexity if c > 10)
                if any(c > 10 for c in func_complexity)
                else 0.0
            ),
            "extreme_cc_mean": 0.0,
            "cc_normalized": 0.0,
            "cc_concentration": 0.0,
            "depth_max": max(func_depths) if func_depths else 0,
            "lines_sum": sum(func_lines) if func_lines else 0,
            "lines_mean": (
                sum(func_lines) / len(func_lines) if func_lines else 0.0
            ),
            "control_blocks_sum": (
                sum(func_control_blocks) if func_control_blocks else 0
            ),
        },
        "classes": {
            "count": len(class_method_counts),
            "method_counts_sum": (
                sum(class_method_counts) if class_method_counts else 0
            ),
            "method_counts_mean": (
                sum(class_method_counts) / len(class_method_counts)
                if class_method_counts
                else 0.0
            ),
            "attribute_counts_sum": (
                sum(class_attribute_counts) if class_attribute_counts else 0
            ),
            "attribute_counts_mean": (
                sum(class_attribute_counts) / len(class_attribute_counts)
                if class_attribute_counts
                else 0.0
            ),
        },
        "complexity": {
            "cc_ratings": cc_ratings,
            "mi_ratings": mi_ratings,
            "cc_sum": cc_sum,
            "cc_max": cc_max,
            "num_complex": num_complex,
            "mi_sum": mi_sum,
            "mi_min": mi_min,
        },
        "waste": {
            "single_use_functions": total_single_use_functions,
            "trivial_wrappers": total_trivial_wrappers,
            "single_method_classes": total_single_method_classes,
        },
        "redundancy": {
            "clone_instances": total_clone_instances,
            "clone_lines": total_clone_lines,
            "clone_ratio_sum": clone_ratio_sum,
            "files_with_clones": files_with_clones,
        },
        "ast_grep": {
            "violations": total_ast_grep_violations,
            "rules_checked": ast_grep_rules_checked,
            "counts": {},
        },
        "source_files": None,
    }

    # Create quality_analysis directory
    quality_dir = tmp_path / QUALITY_DIR
    quality_dir.mkdir(parents=True, exist_ok=True)

    # Write overall_quality.json
    quality_file = quality_dir / QUALITY_METRIC_SAVENAME
    quality_file.write_text(json.dumps(quality_data))

    # Write flat files.jsonl
    with (quality_dir / FILES_QUALITY_SAVENAME).open("w") as f:
        for file_path, fm in files_data.items():
            # Create flat file metrics (no nested symbols/ast_grep lists)
            flat_fm = {
                "file_path": file_path,
                "loc": fm["lines"]["loc"],
                "total_lines": fm["lines"]["total_lines"],
                "comments": (
                    fm["lines"]["single_comment"] + fm["lines"]["multi_comment"]
                ),
                "multi_comment": fm["lines"]["multi_comment"],
                "single_comment": fm["lines"]["single_comment"],
                "lint_errors": fm["lint"]["errors"],
                "lint_fixable": fm["lint"]["fixable"],
                "mi": fm["mi"],
                "depth": fm.get("depth", 0),
                "is_entry_language": fm.get("is_entry_language", False),
                "import_count": fm.get("import_count", 0),
                "global_count": fm.get("global_count", 0),
                "symbol_count": len(fm["symbols"]),
                "ast_grep_violation_count": fm.get("ast_grep", {}).get(
                    "total_violations", 0
                ),
                "ast_grep_rules_checked": fm.get("ast_grep", {}).get(
                    "rules_checked", 0
                ),
                "clone_instances": fm.get("redundancy", {}).get(
                    "total_clone_instances", 0
                ),
                "clone_lines": fm.get("redundancy", {}).get("clone_lines", 0),
                "clone_ratio": fm.get("redundancy", {}).get("clone_ratio", 0.0),
                "single_use_count": fm.get("waste", {}).get(
                    "single_use_count", 0
                ),
                "trivial_wrapper_count": fm.get("waste", {}).get(
                    "trivial_wrapper_count", 0
                ),
                "single_method_class_count": fm.get("waste", {}).get(
                    "single_method_class_count", 0
                ),
            }
            f.write(json.dumps(flat_fm) + "\n")

    # Write flat symbols.jsonl
    with (quality_dir / SYMBOLS_QUALITY_SAVENAME).open("w") as f:
        for file_path, fm in files_data.items():
            for s in fm["symbols"]:
                flat_sym = {
                    "file_path": file_path,
                    "name": s.get("name", "unknown"),
                    "type": s["type"],
                    "start": s.get("start", 0),
                    "start_col": s.get("start_col", 0),
                    "end": s.get("end", 0),
                    "end_col": s.get("end_col", 0),
                    "complexity": s["complexity"],
                    "branches": s.get("branches", 0),
                    "statements": s.get("statements", 0),
                    "expressions_top_level": s.get("expressions_top_level", 0),
                    "expressions_total": s.get("expressions_total", 0),
                    "control_blocks": s.get("control_blocks", 0),
                    "control_flow": s.get("control_flow", 0),
                    "exception_scaffold": s.get("exception_scaffold", 0),
                    "comparisons": s.get("comparisons", 0),
                    "max_nesting_depth": s.get("max_nesting_depth", 0),
                    "lines": s.get("lines", 0),
                    "method_count": s.get("method_count"),
                    "attribute_count": s.get("attribute_count"),
                }
                f.write(json.dumps(flat_sym) + "\n")

    # Write flat ast_grep.jsonl (empty for most tests, but structure is there)
    with (quality_dir / AST_GREP_QUALITY_SAVENAME).open("w") as f:
        # AST-grep violations are typically from the ast_grep field in files_data
        # For now we just create an empty file (violations are aggregated)
        pass

    return tmp_path


class TestGetQualityMetrics:
    """Tests for get_quality_metrics function."""

    @pytest.fixture
    def sample_quality_file(self, tmp_path: Path) -> Path:
        files_data = {
            "main.py": {
                "mi": 75.0,
                "symbols": [
                    {
                        "type": "function",
                        "complexity": 5,
                        "branches": 2,
                        "statements": 10,
                        "expressions_top_level": 3,
                        "expressions_total": 8,
                        "control_blocks": 2,
                        "max_nesting_depth": 2,
                        "lines": 15,
                        "comparisons": 1,
                        "exception_scaffold": 1,
                    },
                    {
                        "type": "function",
                        "complexity": 15,
                        "branches": 8,
                        "statements": 25,
                        "expressions_top_level": 5,
                        "expressions_total": 20,
                        "control_blocks": 4,
                        "max_nesting_depth": 4,
                        "lines": 30,
                        "comparisons": 4,
                        "exception_scaffold": 2,
                    },
                    {
                        "type": "class",
                        "complexity": 3,
                        "branches": 1,
                        "statements": 5,
                        "expressions_top_level": 1,
                        "expressions_total": 3,
                        "control_blocks": 0,
                        "max_nesting_depth": 1,
                        "lines": 20,
                        "method_count": 2,
                        "attribute_count": 3,
                        "comparisons": 0,
                        "exception_scaffold": 0,
                    },
                ],
                "lines": {
                    "total_lines": 100,
                    "loc": 80,
                    "single_comment": 5,
                    "multi_comment": 3,
                },
                "lint": {
                    "errors": 2,
                    "fixable": 1,
                    "counts": {"E501": 1, "W503": 1},
                },
                "waste": {
                    "single_use_count": 1,
                    "trivial_wrapper_count": 0,
                    "single_method_class_count": 0,
                },
                "redundancy": {
                    "total_clone_instances": 2,
                    "clone_lines": 10,
                    "clone_ratio": 0.1,
                },
                "ast_grep": {
                    "total_violations": 3,
                    "rules_checked": 33,
                    "counts": {"bare-except": 2, "len-comparison": 1},
                },
                "import_count": 5,
                "global_count": 1,
            },
            "utils.py": {
                "mi": 65.0,
                "symbols": [
                    {
                        "type": "function",
                        "complexity": 8,
                        "branches": 4,
                        "statements": 15,
                        "expressions_top_level": 4,
                        "expressions_total": 12,
                        "control_blocks": 3,
                        "max_nesting_depth": 3,
                        "lines": 25,
                        "comparisons": 2,
                        "exception_scaffold": 0,
                    },
                ],
                "lines": {
                    "total_lines": 50,
                    "loc": 40,
                    "single_comment": 2,
                    "multi_comment": 1,
                },
                "lint": {
                    "errors": 1,
                    "fixable": 1,
                    "counts": {"E501": 1},
                },
                "import_count": 3,
                "global_count": 0,
            },
        }
        return _create_quality_test_files(tmp_path, files_data)

    def test_lines_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        assert result["loc"] == 120  # 80 + 40
        assert result["total_lines"] == 150  # 100 + 50
        assert result["single_comments"] == 7  # 5 + 2

    def test_quality_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        assert result["lint_errors"] == 3  # 2 + 1
        assert result["lint_fixable"] == 2  # 1 + 1
        assert result["files"] == 2
        # cc values for functions/methods only: 5, 15, 8 -> 1 above 10
        assert result["cc_high_count"] == 1
        assert result["cc_mean"] == (5 + 15 + 8) / 3  # Functions only, not class
        assert result["cc_max"] == 15
        assert result["high_cc_mean"] == 15.0  # only one high value

    def test_files_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        assert result["files"] == 2
        # files_created/modified/deleted removed - not used anywhere

    def test_symbols_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        # 3 functions + 1 class
        assert result["functions"] == 3
        assert result["classes"] == 1
        assert result["methods"] == 0

    def test_symbols_additional_metrics(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        # max_nesting_depth: max(2, 4, 3) = 4 (only functions/methods)
        assert result["max_nesting_depth"] == 4
        # lines_per_symbol: (15 + 30 + 25) / 3 = 23.33... (avg of function lines)
        assert abs(result["lines_per_symbol"] - 70 / 3) < 0.01
        # mean function LOC from distributions (max_func_loc removed)
        assert abs(result["mean_func_loc"] - 70 / 3) < 0.01
        # comparisons: total = 1 + 4 + 2 = 7 (max_comparisons removed)
        assert result["comparisons"] == 7
        # exception_scaffold: total = 1 + 2 + 0 = 3
        assert result["try_scaffold"] == 3
        # Removed: expressions_top_level, expressions, control_blocks,
        # method_counts, attribute_counts, max_func_loc, max_comparisons

    def test_waste_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        assert result["single_use_functions"] == 1
        assert result["trivial_wrappers"] == 0
        assert result["single_method_classes"] == 0

    def test_redundancy_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        assert result["clone_instances"] == 2
        assert result["clone_lines"] == 10
        # clone_ratio_mean removed - derived metric not used

    def test_ast_grep_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        assert result["ast_grep_violations"] == 3

    def test_globals_namespace(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        # globals_count removed - not used anywhere
        assert "globals_count" not in result

    def test_derived_ratios(self, sample_quality_file: Path):
        result = get_quality_metrics(sample_quality_file)

        # methods_per_class, attributes_per_class removed - not used
        assert "methods_per_class" not in result
        assert "attributes_per_class" not in result

    def test_missing_file(self, tmp_path: Path):
        result = get_quality_metrics(tmp_path)
        assert result == {}

    def test_empty_files(self, tmp_path: Path):
        # Create empty but valid snapshot structure
        files_data = {}
        _create_quality_test_files(tmp_path, files_data)

        result = get_quality_metrics(tmp_path)

        assert result["loc"] == 0
        # When there are no files, complexity stats might not be computed
        # Just verify basic fields exist
        assert "files" in result


class TestGetRubricMetrics:
    """Tests for get_rubric_metrics function."""

    @pytest.fixture
    def sample_rubric_file(self, tmp_path: Path) -> Path:
        grades = [
            {"criteria": "Code Complexity", "file_name": "main.py"},
            {"criteria": "Code Complexity", "file_name": "utils.py"},
            {"criteria": "Magic Numbers", "file_name": "main.py"},
            {
                "criteria": "Magic Numbers",
                "file_name": "main.py",
                "carried_over": True,
            },
        ]
        rubric_file = tmp_path / "rubric.jsonl"
        rubric_file.write_text("\n".join(json.dumps(g) for g in grades))
        return tmp_path

    def test_returns_flat_rubric(self, sample_rubric_file: Path):
        result = get_rubric_metrics(sample_rubric_file)

        assert result["rubric_total_flags"] == 4
        assert result["rubric_carried_over"] == 1

    def test_missing_file(self, tmp_path: Path):
        result = get_rubric_metrics(tmp_path)
        assert result == {}

    def test_empty_file(self, tmp_path: Path):
        rubric_file = tmp_path / "rubric.jsonl"
        rubric_file.write_text("")

        result = get_rubric_metrics(tmp_path)

        assert result["rubric_total_flags"] == 0
        assert result["rubric_carried_over"] == 0


class TestGetCheckpointMetrics:
    """Tests for get_checkpoint_metrics function."""

    def test_combines_all_metrics(self, tmp_path: Path):
        """Test that get_checkpoint_metrics combines all metric types."""
        # Create evaluation.json
        eval_data = {
            "pass_counts": {"Core": 5},
            "total_counts": {"Core": 10},
            "duration": 5.0,
        }
        (tmp_path / "evaluation.json").write_text(json.dumps(eval_data))

        # Create inference_result.json
        inference_data = {
            "started": "2024-01-01T00:00:00",
            "completed": "2024-01-01T00:01:00",
            "usage": {
                "cost": 0.5,
                "steps": 10,
                "net_tokens": {"input": 100, "output": 50},
            },
        }
        (tmp_path / "inference_result.json").write_text(
            json.dumps(inference_data)
        )

        result = get_checkpoint_metrics(tmp_path)

        # Verify it contains metrics from all sources
        assert "pass_rate" in result  # from evaluation
        assert "cost" in result  # from inference
        assert "total_tests" in result  # from evaluation

    def test_empty_checkpoint(self, tmp_path: Path):
        """Test that get_checkpoint_metrics works with missing files."""
        result = get_checkpoint_metrics(tmp_path)

        # Should return default fields when all metric files are missing
        assert result["is_first"] is False
        assert result["is_last"] is False
        # May also include erosion metrics with default values
        assert "erosion_velocity" in result or len(result) == 2


class TestComputeCheckpointDelta:
    """Tests for compute_checkpoint_delta function."""

    def test_returns_empty_for_none_prev(self):
        """First checkpoint should return empty dict."""
        curr = {"loc": 100, "symbols.total": 10}
        result = compute_checkpoint_delta(None, curr)
        assert result == {}

    def test_percentage_deltas(self):
        """Test percentage change calculation."""
        prev = {
            "loc": 100,
            "lint_errors": 5,
            "total_lines": 120,
        }
        curr = {
            "loc": 150,
            "lint_errors": 10,
            "lines_added": 20,
            "lines_removed": 10,
        }
        result = compute_checkpoint_delta(prev, curr)

        assert result["delta.loc"] == 50.0  # (150-100)/100 * 100
        assert result["delta.lint_errors"] == 100.0

    def test_zero_prev_returns_inf(self):
        """Test handling of zero previous values."""
        prev = {
            "lint_errors": 0,
            "total_lines": 100,
        }
        curr = {
            "lint_errors": 5,
            "lines_added": 10,
            "lines_removed": 5,
        }
        result = compute_checkpoint_delta(prev, curr)

        # Should be inf when prev is 0 but curr > 0
        assert result["delta.lint_errors"] == float("inf")

    def test_zero_both_returns_zero(self):
        """Test handling when both prev and curr are zero."""
        prev = {
            "lint_errors": 0,
            "total_lines": 100,
        }
        curr = {
            "lint_errors": 0,
            "lines_added": 0,
            "lines_removed": 0,
        }
        result = compute_checkpoint_delta(prev, curr)

        assert result["delta.lint_errors"] == 0.0

    def test_negative_delta(self):
        """Test negative percentage changes."""
        prev = {
            "lint_errors": 10,
            "total_lines": 100,
        }
        curr = {
            "lint_errors": 5,
            "lines_added": 10,
            "lines_removed": 5,
        }
        result = compute_checkpoint_delta(prev, curr)

        assert result["delta.lint_errors"] == -50.0

    def test_churn_ratio(self):
        """Test churn ratio calculation."""
        prev = {"total_lines": 100}
        curr = {"total_lines": 120, "lines_added": 20, "lines_removed": 10}
        result = compute_checkpoint_delta(prev, curr)

        assert result["delta.churn_ratio"] == 0.3  # (20+10) / 100

    def test_churn_ratio_zero_prev(self):
        """Test churn ratio when prev total_lines is zero."""
        prev = {"total_lines": 0}
        curr = {"total_lines": 100, "lines_added": 30, "lines_removed": 20}
        result = compute_checkpoint_delta(prev, curr)

        assert result["delta.churn_ratio"] == float("inf")

    def test_new_violations_per_loc(self):
        """Test new violations per LOC calculation."""
        prev = {
            "rubric_total_flags": 5,
            "total_lines": 100,
        }
        curr = {
            "rubric_total_flags": 8,
            "rubric_carried_over": 5,
            "loc": 100,
            "lines_added": 10,
            "lines_removed": 5,
        }
        result = compute_checkpoint_delta(prev, curr)

        # new_flags = 8 - 5 = 3, per_loc = 3 / 100 = 0.03
        assert result["delta.new_violations_per_loc"] == 0.03

    def test_new_violations_per_loc_small_loc(self):
        """Test new violations per LOC with small LOC value."""
        prev = {
            "total_lines": 50,
        }
        curr = {
            "rubric_total_flags": 5,
            "rubric_carried_over": 2,
            "loc": 10,
            "lines_added": 5,
            "lines_removed": 3,
        }
        result = compute_checkpoint_delta(prev, curr)

        # new_flags = 5 - 2 = 3, per_loc = 3 / 10 = 0.3
        assert result["delta.new_violations_per_loc"] == 0.3

    def test_high_complexity_total(self):
        """Test high complexity total calculation."""
        prev = {
            "cc_high_count": 2,
            "total_lines": 100,
        }
        curr = {
            "cc_high_count": 4,
            "lines_added": 20,
            "lines_removed": 10,
        }
        result = compute_checkpoint_delta(prev, curr)

        assert result["delta.cc_high_count"] == 100.0

    def test_all_delta_keys_present(self):
        """Test that all expected delta keys are present in output."""
        prev = {
            "loc": 100,
            "lint_errors": 5,
            "ast_grep_violations": 10,
            "functions": 5,
            "total_lines": 120,
        }
        curr = {
            "loc": 150,
            "lint_errors": 8,
            "ast_grep_violations": 12,
            "functions": 7,
            "lines_added": 20,
            "lines_removed": 10,
            "rubric_total_flags": 5,
            "rubric_carried_over": 2,
        }
        result = compute_checkpoint_delta(prev, curr)

        # Check DELTA_METRIC_KEYS deltas are present (reduced set)
        assert "delta.loc" in result
        assert "delta.lint_errors" in result
        assert "delta.ast_grep_violations" in result
        assert "delta.cc_high_count" in result
        assert "delta.comparisons" in result

        # Check special delta metrics
        assert "delta.churn_ratio" in result
        assert "delta.new_violations_per_loc" in result

        # Verify removed deltas are not present
        assert "delta.functions" not in result
        assert "delta.clone_instances" not in result
