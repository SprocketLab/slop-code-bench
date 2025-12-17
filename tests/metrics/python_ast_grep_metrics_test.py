"""Integration-style tests for AST-grep metrics without mocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.metrics.driver import _calculate_file_metrics
from slop_code.metrics.languages import EXT_TO_LANGUAGE
from slop_code.metrics.languages import LANGUAGE_REGISTRY
from slop_code.metrics.languages.python import calculate_redundancy_metrics
from slop_code.metrics.languages.python import calculate_waste_metrics
from slop_code.metrics.languages.python import get_symbols
from slop_code.metrics.models import LanguageSpec
from slop_code.metrics.models import LineCountMetrics
from slop_code.metrics.models import LintMetrics


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


class TestFunctionAndClassMetrics:
    def test_function_expression_and_control_metrics(
        self, tmp_path: Path
    ) -> None:
        source = _write(
            tmp_path,
            "metrics_sample.py",
            """def simple(a):
    foo(a)
    return a + 1

def nested(x):
    if x:
        while x:
            if x > 1:
                x -= 1
    return x
""",
        )

        symbols = get_symbols(source)
        simple = next(s for s in symbols if s.name == "simple")
        nested = next(s for s in symbols if s.name == "nested")

        assert simple.expressions_top_level == 1
        assert simple.expressions_total == 2
        assert simple.control_blocks == 0
        assert simple.control_flow == 0
        assert simple.exception_scaffold == 0
        assert simple.comparisons == 0
        assert simple.max_nesting_depth == 0
        assert simple.lines == 3

        assert nested.control_blocks == 1
        assert nested.control_flow == 2
        assert nested.exception_scaffold == 0
        assert nested.comparisons == 1
        assert nested.max_nesting_depth == 3
        assert nested.lines == 6

    def test_class_attribute_and_method_counts(self, tmp_path: Path) -> None:
        source = _write(
            tmp_path,
            "class_sample.py",
            """class Sample:
    def __init__(self):
        self.a = 1
        self.b = 2

    def method(self):
        self.a += 1
""",
        )

        symbols = get_symbols(source)
        sample_cls = next(s for s in symbols if s.name == "Sample")

        assert sample_cls.method_count == 2
        assert sample_cls.attribute_count == 2

    def test_dataclass_attribute_count(self, tmp_path: Path) -> None:
        source = _write(
            tmp_path,
            "dataclass_sample.py",
            """from dataclasses import dataclass

@dataclass
class Config:
    host: str
    port: int = 8000
""",
        )

        symbols = get_symbols(source)
        config_cls = next(s for s in symbols if s.name == "Config")

        assert config_cls.method_count == 0
        assert config_cls.attribute_count == 2

    def test_control_flow_and_exception_scaffold_counts(
        self, tmp_path: Path
    ) -> None:
        source = _write(
            tmp_path,
            "control_flow_sample.py",
            """def flow(x):
    if x == 1:
        match x:
            case 1:
                pass
            case 2:
                pass
    elif x in (1, 2):
        try:
            risky(x)
        except ValueError:
            handle()
        finally:
            cleanup()
    return x is not None
""",
        )

        symbols = get_symbols(source)
        flow = next(s for s in symbols if s.name == "flow")

        assert flow.control_flow == 5
        assert flow.exception_scaffold == 3
        assert flow.comparisons == 3


class TestRedundancyAndWasteDetection:
    def test_detects_code_clones(self, tmp_path: Path) -> None:
        source = _write(
            tmp_path,
            "clones.py",
            """def first():
    if True:
        return 1

def second():
    if True:
        return 1
""",
        )

        metrics = calculate_redundancy_metrics(source)

        assert metrics.clones
        assert metrics.total_clone_instances >= 2
        assert metrics.clone_lines > 0
        assert metrics.clone_ratio > 0.0

    def test_detects_waste_patterns(self, tmp_path: Path) -> None:
        source = _write(
            tmp_path,
            "waste.py",
            """x = 1

def helper():
    return x

def wrapper():
    return helper()

def single_use():
    helper()

def call_helper_twice():
    helper()
    helper()

class Solo:
    def only(self):
        return helper()
""",
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        trivial_names = {w.name for w in metrics.trivial_wrappers}
        assert "wrapper" in trivial_names

        single_method_classes = set(metrics.single_method_classes)
        assert "Solo" in single_method_classes

        single_use_names = {s.name for s in metrics.single_use_functions}
        assert "single_use" in single_use_names
        assert "call_helper_twice" in single_use_names


class TestDriverIntegration:
    @pytest.fixture(autouse=True)
    def override_language_registry(self):
        """Use a lightweight Python spec to avoid external tools."""
        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

        def line_fn(path: Path) -> LineCountMetrics:
            return LineCountMetrics(
                total_lines=len(path.read_text().splitlines()),
                loc=1,
                comments=0,
                multi_comment=0,
                single_comment=0,
            )

        def lint_fn(path: Path) -> LintMetrics:
            return LintMetrics(errors=0, fixable=0, counts={})

        def mi_fn(path: Path) -> float:
            return 1.0

        spec = LanguageSpec(
            extensions={".py"},
            line=line_fn,
            lint=lint_fn,
            symbol=get_symbols,
            mi=mi_fn,
            redundancy=calculate_redundancy_metrics,
            waste=calculate_waste_metrics,
        )
        LANGUAGE_REGISTRY["python"] = spec
        EXT_TO_LANGUAGE[".py"] = "python"

        yield

        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

    def test_driver_populates_imports_globals_and_ast_grep_metrics(
        self, tmp_path: Path
    ) -> None:
        source = _write(
            tmp_path,
            "driver_sample.py",
            """import math

x = 1

def clone_one():
    if True:
        return 1

def clone_two():
    if True:
        return 1

def wrapper():
    return clone_one()

class Solo:
    def only(self):
        return wrapper()
""",
        )

        metrics = _calculate_file_metrics(source, depth=1)
        assert metrics is not None

        assert metrics.import_count == 1
        assert metrics.global_count == 1

        assert metrics.redundancy is not None
        assert metrics.redundancy.total_clone_instances >= 2

        assert metrics.waste is not None
        assert "Solo" in metrics.waste.single_method_classes
        assert any(w.name == "wrapper" for w in metrics.waste.trivial_wrappers)
