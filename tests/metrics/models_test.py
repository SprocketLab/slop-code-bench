"""Tests for metrics models and registry."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from slop_code.metrics.languages import EXT_TO_LANGUAGE
from slop_code.metrics.languages import LANGUAGE_REGISTRY
from slop_code.metrics.languages import get_language
from slop_code.metrics.languages import get_language_by_extension
from slop_code.metrics.languages import register_language
from slop_code.metrics.models import AstGrepAggregates
from slop_code.metrics.models import ClassStats
from slop_code.metrics.models import ComplexityAggregates
from slop_code.metrics.models import FileMetrics
from slop_code.metrics.models import FunctionStats
from slop_code.metrics.models import LanguageSpec
from slop_code.metrics.models import LineCountMetrics
from slop_code.metrics.models import LintMetrics
from slop_code.metrics.models import RedundancyAggregates
from slop_code.metrics.models import SnapshotMetrics
from slop_code.metrics.models import SnapshotQualityReport
from slop_code.metrics.models import SymbolAggregates
from slop_code.metrics.models import SymbolMetrics
from slop_code.metrics.models import WasteAggregates
from slop_code.metrics.models import _compute_rating


def _compute_mi_rating(mi: float) -> Literal["A", "B", "C"]:
    """Compute MI rating from maintainability index value."""
    if mi >= 19:
        return "A"
    if mi > 9:
        return "B"
    return "C"


def _create_snapshot_from_files(
    files: dict[str, FileMetrics],
    source_files: set[str] | None = None,
) -> SnapshotMetrics:
    """Helper to create SnapshotMetrics from a files dict for testing."""
    cc_ratings: dict[str, int] = {
        "A": 0,
        "B": 0,
        "C": 0,
        "D": 0,
        "E": 0,
        "F": 0,
    }
    mi_ratings: dict[str, int] = {"A": 0, "B": 0, "C": 0}

    file_count = len(files)
    source_file_count = len(source_files) if source_files else file_count

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
    mi_sum = 0.0
    mi_min = float("inf") if files else 0.0
    total_imports = 0
    max_imports = 0
    total_globals = 0

    for fm in files.values():
        mi_sum += fm.mi
        if fm.mi < mi_min:
            mi_min = fm.mi

        # MI rating
        mi_rating = _compute_mi_rating(fm.mi)
        mi_ratings[mi_rating] = mi_ratings.get(mi_rating, 0) + 1

        for sym in fm.symbols:
            total_symbols += 1
            total_statements += sym.statements

            # CC rating
            cc_sum += sym.complexity
            if sym.complexity > cc_max:
                cc_max = sym.complexity
            if sym.complexity > 10:
                num_complex += 1

            rating = _compute_rating(sym.complexity)
            cc_ratings[rating] = cc_ratings.get(rating, 0) + 1

            # Symbol type counts
            if sym.type == "function":
                function_count += 1
            elif sym.type == "method":
                method_count += 1
            elif sym.type == "class":
                class_count += 1

    if not files:
        mi_min = 0.0

    # Use first file's lines/lint for entry file metrics (test simplification)
    first_file = next(iter(files.values()), None)
    lines = (
        first_file.lines
        if first_file
        else LineCountMetrics(
            total_lines=0, loc=0, comments=0, multi_comment=0, single_comment=0
        )
    )
    lint = (
        first_file.lint
        if first_file
        else LintMetrics(errors=0, fixable=0, counts={})
    )

    return SnapshotMetrics(
        file_count=file_count,
        source_file_count=source_file_count,
        lines=lines,
        lint=lint,
        symbols=SymbolAggregates(
            total=total_symbols,
            functions=function_count,
            methods=method_count,
            classes=class_count,
            variables=variable_count,
            type_aliases=type_alias_count,
            statements=total_statements,
            expressions_top_level=total_expressions_top_level,
            expressions=total_expressions,
            imports=total_imports,
            max_imports=max_imports,
            globals=total_globals,
        ),
        functions=FunctionStats(),
        classes=ClassStats(),
        complexity=ComplexityAggregates(
            cc_ratings=cc_ratings,
            mi_ratings=mi_ratings,
            cc_sum=cc_sum,
            cc_max=cc_max,
            num_complex=num_complex,
            mi_sum=mi_sum,
            mi_min=mi_min,
        ),
        waste=WasteAggregates(
            single_use_functions=0,
            trivial_wrappers=0,
            single_method_classes=0,
        ),
        redundancy=RedundancyAggregates(
            clone_instances=0,
            clone_lines=0,
            clone_ratio_sum=0.0,
            files_with_clones=0,
        ),
        ast_grep=AstGrepAggregates(violations=0, rules_checked=0),
    )


class TestSnapshotQualityReport:
    """Tests for SnapshotQualityReport aggregation logic."""

    def test_from_snapshot_metrics_basic(self):
        """Test basic aggregation of snapshot metrics."""
        files = {
            "file1.py": FileMetrics(
                symbols=[
                    SymbolMetrics(
                        name="func1",
                        type="function",
                        start=1,
                        start_col=0,
                        end=5,
                        end_col=0,
                        complexity=2,
                        branches=1,
                        statements=2,
                    ),
                    SymbolMetrics(
                        name="func2",
                        type="function",
                        start=10,
                        start_col=0,
                        end=15,
                        end_col=0,
                        complexity=8,
                        branches=5,
                        statements=8,
                    ),
                ],
                lines=LineCountMetrics(
                    total_lines=50,
                    loc=40,
                    comments=8,
                    multi_comment=5,
                    single_comment=3,
                ),
                lint=LintMetrics(errors=2, fixable=1, counts={}),
                mi=20.5,
                depth=1,
            ),
            "file2.py": FileMetrics(
                symbols=[
                    SymbolMetrics(
                        name="func3",
                        type="function",
                        start=1,
                        start_col=0,
                        end=10,
                        end_col=0,
                        complexity=15,
                        branches=10,
                        statements=15,
                    ),
                ],
                lines=LineCountMetrics(
                    total_lines=30,
                    loc=25,
                    comments=3,
                    multi_comment=2,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=5, fixable=3, counts={}),
                mi=12.0,
                depth=1,
            ),
        }
        snapshot = _create_snapshot_from_files(files)

        report = SnapshotQualityReport.from_snapshot_metrics(snapshot)

        assert report.files == 2
        assert report.source_files == 2
        # Lines/lint come from first file in helper
        assert report.overall_lines.total_lines == 50
        assert report.overall_lines.loc == 40
        assert report.lint_errors == 2
        assert report.lint_fixable == 1
        # CC ratings: complexity 2=A, 8=B, 15=C
        assert report.cc_counts == {
            "A": 1,
            "B": 1,
            "C": 1,
            "D": 0,
            "E": 0,
            "F": 0,
        }
        # MI ratings: 20.5=A, 12.0=B
        assert report.mi == {"A": 1, "B": 1, "C": 0}

    def test_from_snapshot_metrics_mi_ratings(self):
        """Test MI rating categorization (A >= 19, 9 < B < 19, C <= 9)."""
        files = {
            "high.py": FileMetrics(
                symbols=[],
                lines=LineCountMetrics(
                    total_lines=10,
                    loc=8,
                    comments=1,
                    multi_comment=0,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=25.0,  # A rating
                depth=1,
            ),
            "medium.py": FileMetrics(
                symbols=[],
                lines=LineCountMetrics(
                    total_lines=10,
                    loc=8,
                    comments=1,
                    multi_comment=0,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=15.0,  # B rating
                depth=1,
            ),
            "low.py": FileMetrics(
                symbols=[],
                lines=LineCountMetrics(
                    total_lines=10,
                    loc=8,
                    comments=1,
                    multi_comment=0,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=5.0,  # C rating
                depth=1,
            ),
            "boundary_a.py": FileMetrics(
                symbols=[],
                lines=LineCountMetrics(
                    total_lines=10,
                    loc=8,
                    comments=1,
                    multi_comment=0,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=19.0,  # Exactly 19, should be A
                depth=1,
            ),
            "boundary_c.py": FileMetrics(
                symbols=[],
                lines=LineCountMetrics(
                    total_lines=10,
                    loc=8,
                    comments=1,
                    multi_comment=0,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=9.0,  # Exactly 9, should be C
                depth=1,
            ),
        }
        snapshot = _create_snapshot_from_files(files)

        report = SnapshotQualityReport.from_snapshot_metrics(snapshot)

        assert report.mi == {"A": 2, "B": 1, "C": 2}

    def test_from_snapshot_metrics_all_cc_ratings(self):
        """Test CC rating counts for all possible ratings A-F."""
        files = {
            "file.py": FileMetrics(
                symbols=[
                    SymbolMetrics(
                        name="a",
                        type="function",
                        start=1,
                        start_col=0,
                        end=4,
                        end_col=0,
                        complexity=1,
                        branches=0,
                        statements=1,
                    ),
                    SymbolMetrics(
                        name="b",
                        type="function",
                        start=5,
                        start_col=0,
                        end=9,
                        end_col=0,
                        complexity=6,
                        branches=4,
                        statements=6,
                    ),
                    SymbolMetrics(
                        name="c",
                        type="function",
                        start=10,
                        start_col=0,
                        end=14,
                        end_col=0,
                        complexity=11,
                        branches=8,
                        statements=11,
                    ),
                    SymbolMetrics(
                        name="d",
                        type="function",
                        start=15,
                        start_col=0,
                        end=19,
                        end_col=0,
                        complexity=21,
                        branches=15,
                        statements=21,
                    ),
                    SymbolMetrics(
                        name="e",
                        type="function",
                        start=20,
                        start_col=0,
                        end=24,
                        end_col=0,
                        complexity=31,
                        branches=25,
                        statements=31,
                    ),
                    SymbolMetrics(
                        name="f",
                        type="function",
                        start=25,
                        start_col=0,
                        end=30,
                        end_col=0,
                        complexity=50,
                        branches=40,
                        statements=50,
                    ),
                ],
                lines=LineCountMetrics(
                    total_lines=100,
                    loc=80,
                    comments=15,
                    multi_comment=10,
                    single_comment=5,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=20.0,
                depth=1,
            ),
        }
        snapshot = _create_snapshot_from_files(files)

        report = SnapshotQualityReport.from_snapshot_metrics(snapshot)

        assert report.cc_counts == {
            "A": 1,
            "B": 1,
            "C": 1,
            "D": 1,
            "E": 1,
            "F": 1,
        }

    def test_from_snapshot_metrics_empty(self):
        """Test with empty snapshot."""
        snapshot = _create_snapshot_from_files({})

        report = SnapshotQualityReport.from_snapshot_metrics(snapshot)

        assert report.files == 0
        assert report.source_files == 0
        assert report.overall_lines.total_lines == 0
        assert report.lint_errors == 0
        assert report.lint_fixable == 0
        # Empty files means no CC/MI counts
        assert report.cc_counts == {
            "A": 0,
            "B": 0,
            "C": 0,
            "D": 0,
            "E": 0,
            "F": 0,
        }
        assert report.mi == {"A": 0, "B": 0, "C": 0}
        assert report.ast_grep_violations == 0
        assert report.ast_grep_rules_checked == 0

    def test_from_snapshot_metrics_with_ast_grep(self):
        """Test AST-grep metrics from aggregates are included in report."""
        files = {
            "file.py": FileMetrics(
                symbols=[],
                lines=LineCountMetrics(
                    total_lines=10,
                    loc=8,
                    comments=1,
                    multi_comment=0,
                    single_comment=1,
                ),
                lint=LintMetrics(errors=0, fixable=0, counts={}),
                mi=20.0,
                depth=1,
            ),
        }
        snapshot = _create_snapshot_from_files(files)
        # Set ast_grep values directly on the ast_grep aggregate section
        snapshot = snapshot.model_copy(
            update={
                "ast_grep": AstGrepAggregates(violations=15, rules_checked=34)
            }
        )

        report = SnapshotQualityReport.from_snapshot_metrics(snapshot)

        assert report.ast_grep_violations == 15
        assert report.ast_grep_rules_checked == 34

    def test_from_snapshot_metrics_no_ast_grep(self):
        """Test report with no AST-grep metrics defaults to zero."""
        snapshot = _create_snapshot_from_files({})

        report = SnapshotQualityReport.from_snapshot_metrics(snapshot)

        assert report.ast_grep_violations == 0
        assert report.ast_grep_rules_checked == 0


class TestLanguageRegistry:
    """Tests for language registry functions."""

    @pytest.fixture(autouse=True)
    def clear_registry(self):
        """Clear the language registry before each test."""
        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()
        yield
        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

    def _dummy_line_metrics(self, path: Path) -> LineCountMetrics:
        """Dummy line metrics function."""
        return LineCountMetrics(
            total_lines=10,
            loc=8,
            comments=2,
            multi_comment=1,
            single_comment=1,
        )

    def _dummy_lint_metrics(self, path: Path) -> LintMetrics:
        """Dummy lint metrics function."""
        return LintMetrics(errors=0, fixable=0, counts={})

    def _dummy_symbol_metrics(self, path: Path) -> list[SymbolMetrics]:
        """Dummy symbol metrics function."""
        return []

    def _dummy_mi(self, path: Path) -> float:
        """Dummy MI function."""
        return 20.0

    def test_register_and_get_language(self):
        """Test registering and retrieving a language by name."""
        spec = LanguageSpec(
            extensions={".py", ".pyw"},
            line=self._dummy_line_metrics,
            lint=self._dummy_lint_metrics,
            symbol=self._dummy_symbol_metrics,
            mi=self._dummy_mi,
        )

        register_language("python", spec)

        retrieved = get_language("python")
        assert retrieved == spec
        assert retrieved.extensions == {".py", ".pyw"}

    def test_register_language_maps_extensions(self):
        """Test that registering a language maps all extensions."""
        spec = LanguageSpec(
            extensions={".js", ".jsx", ".mjs"},
            line=self._dummy_line_metrics,
            lint=self._dummy_lint_metrics,
            symbol=self._dummy_symbol_metrics,
            mi=self._dummy_mi,
        )

        register_language("javascript", spec)

        assert EXT_TO_LANGUAGE[".js"] == "javascript"
        assert EXT_TO_LANGUAGE[".jsx"] == "javascript"
        assert EXT_TO_LANGUAGE[".mjs"] == "javascript"

    def test_get_language_by_extension(self):
        """Test retrieving a language by file extension."""
        spec = LanguageSpec(
            extensions={".rs"},
            line=self._dummy_line_metrics,
            lint=self._dummy_lint_metrics,
            symbol=self._dummy_symbol_metrics,
            mi=self._dummy_mi,
        )

        register_language("rust", spec)

        retrieved = get_language_by_extension(".rs")
        assert retrieved == spec

    def test_get_language_by_extension_unknown(self):
        """Test retrieving unknown extension returns None."""
        spec = LanguageSpec(
            extensions={".go"},
            line=self._dummy_line_metrics,
            lint=self._dummy_lint_metrics,
            symbol=self._dummy_symbol_metrics,
            mi=self._dummy_mi,
        )

        register_language("go", spec)

        result = get_language_by_extension(".unknown")
        assert result is None

    def test_get_language_not_found(self):
        """Test getting a non-existent language raises KeyError."""
        with pytest.raises(KeyError):
            get_language("nonexistent")

    def test_register_multiple_languages(self):
        """Test registering multiple languages."""
        python_spec = LanguageSpec(
            extensions={".py"},
            line=self._dummy_line_metrics,
            lint=self._dummy_lint_metrics,
            symbol=self._dummy_symbol_metrics,
            mi=self._dummy_mi,
        )

        ruby_spec = LanguageSpec(
            extensions={".rb"},
            line=self._dummy_line_metrics,
            lint=self._dummy_lint_metrics,
            symbol=self._dummy_symbol_metrics,
            mi=self._dummy_mi,
        )

        register_language("python", python_spec)
        register_language("ruby", ruby_spec)

        assert get_language("python") == python_spec
        assert get_language("ruby") == ruby_spec
        assert get_language_by_extension(".py") == python_spec
        assert get_language_by_extension(".rb") == ruby_spec
