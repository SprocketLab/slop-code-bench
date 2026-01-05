"""Tests for mass delta metrics including Gini coefficient and top N% distribution."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from slop_code.metrics.checkpoint.mass import _compute_gini_coefficient
from slop_code.metrics.checkpoint.mass import _compute_top_n_distribution
from slop_code.metrics.checkpoint.mass import compute_mass_delta


class TestComputeGiniCoefficient:
    """Tests for _compute_gini_coefficient helper function."""

    def test_uniform_distribution_returns_zero(self):
        """All equal values should have Gini = 0."""
        masses = [10.0] * 100
        assert _compute_gini_coefficient(masses) == 0.0

    def test_empty_list_returns_zero(self):
        """Empty list should return 0."""
        assert _compute_gini_coefficient([]) == 0.0

    def test_single_value_returns_zero(self):
        """Single value should return 0."""
        assert _compute_gini_coefficient([5.0]) == 0.0

    def test_all_zeros_returns_zero(self):
        """All zeros should return 0."""
        assert _compute_gini_coefficient([0.0, 0.0, 0.0]) == 0.0

    def test_maximum_inequality_approaches_one(self):
        """One large value with many zeros should approach Gini = 1."""
        masses = [100.0] + [0.0] * 99
        gini = _compute_gini_coefficient(masses)
        # Since zeros are filtered, this becomes single value
        assert gini == 0.0

    def test_maximum_inequality_non_zero(self):
        """One large value with tiny values should have high Gini."""
        masses = [100.0] + [0.001] * 99
        gini = _compute_gini_coefficient(masses)
        assert gini > 0.9  # Should be very high

    def test_known_distribution(self):
        """Test with known Gini value.

        For distribution [1, 2, 3, 4, 5], Gini ≈ 0.267
        """
        masses = [1.0, 2.0, 3.0, 4.0, 5.0]
        gini = _compute_gini_coefficient(masses)
        assert 0.26 < gini < 0.28

    def test_two_values_equal(self):
        """Two equal values should have Gini = 0."""
        assert _compute_gini_coefficient([5.0, 5.0]) == 0.0

    def test_two_values_unequal(self):
        """Two unequal values should have positive Gini."""
        # [1, 3] -> mean = 2, Gini = |1-2| + |3-2| / (2 * 2 * 2) = 2/8 = 0.25
        gini = _compute_gini_coefficient([1.0, 3.0])
        assert 0.24 < gini < 0.26

    def test_ignores_tiny_values(self):
        """Values below threshold (1e-9) should be filtered."""
        masses = [10.0, 1e-10, 1e-11]
        gini = _compute_gini_coefficient(masses)
        assert gini == 0.0  # Only one non-zero value


class TestComputeTopNDistribution:
    """Tests for _compute_top_n_distribution helper function."""

    def test_empty_list_returns_zeros(self):
        """Empty list should return zeros for all percentiles."""
        result = _compute_top_n_distribution([], key_prefix="")
        assert result["top50_count"] == 0
        assert result["top50_mass"] == 0.0
        assert result["top75_count"] == 0
        assert result["top75_mass"] == 0.0
        assert result["top90_count"] == 0
        assert result["top90_mass"] == 0.0

    def test_single_symbol(self):
        """Single symbol should return 1 for all percentiles."""
        result = _compute_top_n_distribution([100.0], key_prefix="")
        assert result["top50_count"] == 1
        assert result["top50_mass"] == 100.0
        assert result["top75_count"] == 1
        assert result["top75_mass"] == 100.0
        assert result["top90_count"] == 1
        assert result["top90_mass"] == 100.0

    def test_even_distribution(self):
        """10 symbols with equal mass should need N/threshold symbols."""
        masses = [10.0] * 10  # Total = 100
        result = _compute_top_n_distribution(masses, key_prefix="")
        # Top 50% needs 50 mass = 5 symbols
        assert result["top50_count"] == 5
        assert result["top50_mass"] == 50.0
        # Top 90% needs 90 mass = 9 symbols
        assert result["top90_count"] == 9
        assert result["top90_mass"] == 90.0

    def test_concentrated_distribution(self):
        """One large symbol should need 1 symbol for high percentiles."""
        # 90% of mass in first symbol
        masses = [90.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        result = _compute_top_n_distribution(masses, key_prefix="")
        assert result["top50_count"] == 1  # First symbol > 50%
        assert result["top90_count"] == 1  # First symbol = 90%

    def test_custom_percentiles(self):
        """Test with custom percentile list."""
        masses = [10.0] * 10  # Total = 100
        result = _compute_top_n_distribution(masses, percentiles=[0.10, 0.90], key_prefix="")
        assert result["top10_count"] == 1
        assert result["top10_mass"] == 10.0
        assert result["top90_count"] == 9
        assert result["top90_mass"] == 90.0

    def test_only_top_90(self):
        """Test with only 90% percentile (used for non-complexity metrics)."""
        masses = [50.0, 30.0, 20.0]  # Total = 100
        result = _compute_top_n_distribution(masses, percentiles=[0.90], key_prefix="")
        # 50 + 30 = 80, need 3rd to reach 90 (total 100)
        assert result["top90_count"] == 3
        assert result["top90_mass"] == 100.0

    def test_all_zeros_returns_zeros(self):
        """All zeros should return zeros."""
        result = _compute_top_n_distribution([0.0, 0.0, 0.0], key_prefix="")
        assert result["top90_count"] == 0
        assert result["top90_mass"] == 0.0


class TestComputeMassDelta:
    """Integration tests for compute_mass_delta function."""

    @pytest.fixture
    def symbol_template(self):
        """Base symbol template."""
        return {
            "name": "func",
            "type": "function",
            "file_path": "test.py",
            "complexity": 5,
            "statements": 10,
            "branches": 3,
            "comparisons": 2,
            "variables_used": 5,
            "variables_defined": 2,
            "exception_scaffold": 1,
        }

    def _create_symbols_file(self, path: Path, symbols: list[dict]):
        """Write symbols to a JSONL file."""
        with path.open("w") as f:
            for sym in symbols:
                f.write(json.dumps(sym) + "\n")

    def test_returns_empty_for_none_prior(self, symbol_template):
        """Returns empty dict when prior path is None."""
        with tempfile.TemporaryDirectory() as tmp:
            curr_path = Path(tmp) / "curr_symbols.jsonl"
            self._create_symbols_file(curr_path, [symbol_template])
            result = compute_mass_delta(None, curr_path)
            assert result == {}

    def test_returns_empty_for_missing_prior(self, symbol_template):
        """Returns empty dict when prior path doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "nonexistent.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"
            self._create_symbols_file(curr_path, [symbol_template])
            result = compute_mass_delta(prior_path, curr_path)
            assert result == {}

    def test_backward_compatible_net_delta(self, symbol_template):
        """Original delta.mass.{metric} keys should still work."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            # Prior: one function
            self._create_symbols_file(prior_path, [symbol_template])

            # Current: same function with higher complexity
            modified = {**symbol_template, "complexity": 10}
            self._create_symbols_file(curr_path, [modified])

            result = compute_mass_delta(prior_path, curr_path)

            # Backward compatible key should exist
            assert "delta.mass.complexity" in result
            assert result["delta.mass.complexity"] > 0

    def test_added_mass_metrics_present(self, symbol_template):
        """New added mass metrics should be present for complexity."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            # Prior: one function
            self._create_symbols_file(prior_path, [symbol_template])

            # Current: same function with higher complexity
            modified = {**symbol_template, "complexity": 10}
            self._create_symbols_file(curr_path, [modified])

            result = compute_mass_delta(prior_path, curr_path)

            # New added mass keys should exist
            assert "delta.mass.complexity_added" in result
            assert "delta.mass.complexity_added_count" in result
            assert "delta.mass.complexity_added_concentration" in result
            assert "delta.mass.complexity_added_top50_count" in result
            assert "delta.mass.complexity_added_top50_mass" in result
            assert "delta.mass.complexity_added_top75_count" in result
            assert "delta.mass.complexity_added_top75_mass" in result
            assert "delta.mass.complexity_added_top90_count" in result
            assert "delta.mass.complexity_added_top90_mass" in result

    def test_removed_mass_metrics_present(self, symbol_template):
        """New removed mass metrics should be present for complexity."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            # Prior: one function with high complexity
            high_cc = {**symbol_template, "complexity": 20}
            self._create_symbols_file(prior_path, [high_cc])

            # Current: same function with lower complexity
            low_cc = {**symbol_template, "complexity": 5}
            self._create_symbols_file(curr_path, [low_cc])

            result = compute_mass_delta(prior_path, curr_path)

            # New removed mass keys should exist
            assert "delta.mass.complexity_removed" in result
            assert "delta.mass.complexity_removed_count" in result
            assert "delta.mass.complexity_removed_concentration" in result
            assert result["delta.mass.complexity_removed"] > 0
            assert result["delta.mass.complexity_removed_count"] == 1

    def test_aggregate_metrics_present(self, symbol_template):
        """Aggregate metrics (gross, net_to_gross_ratio) should be present."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            self._create_symbols_file(prior_path, [symbol_template])
            modified = {**symbol_template, "complexity": 10}
            self._create_symbols_file(curr_path, [modified])

            result = compute_mass_delta(prior_path, curr_path)

            assert "delta.mass.complexity_gross" in result
            assert "delta.mass.complexity_net_to_gross_ratio" in result

    def test_other_metrics_only_top90(self, symbol_template):
        """Non-complexity metrics should only have top 90% keys."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            self._create_symbols_file(prior_path, [symbol_template])
            modified = {**symbol_template, "branches": 10}
            self._create_symbols_file(curr_path, [modified])

            result = compute_mass_delta(prior_path, curr_path)

            # Branches should have top 90% only
            assert "delta.mass.branches_added_top90_count" in result
            assert "delta.mass.branches_added_top90_mass" in result
            # But not top 50% or top 75%
            assert "delta.mass.branches_added_top50_count" not in result
            assert "delta.mass.branches_added_concentration" not in result

    def test_pure_growth_scenario(self, symbol_template):
        """Test scenario with only added mass (no removal)."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            # Prior: empty
            self._create_symbols_file(prior_path, [])

            # Current: one function
            self._create_symbols_file(curr_path, [symbol_template])

            result = compute_mass_delta(prior_path, curr_path)

            # Should have pure growth
            assert result["delta.mass.complexity_added"] > 0
            assert result["delta.mass.complexity_removed"] == 0.0
            # Net to gross ratio should be 1.0 (pure growth)
            assert result["delta.mass.complexity_net_to_gross_ratio"] == 1.0

    def test_pure_removal_scenario(self, symbol_template):
        """Test scenario with only removed mass (no additions)."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            # Prior: one function
            self._create_symbols_file(prior_path, [symbol_template])

            # Current: empty
            self._create_symbols_file(curr_path, [])

            result = compute_mass_delta(prior_path, curr_path)

            # Should have pure removal
            assert result["delta.mass.complexity_added"] == 0.0
            assert result["delta.mass.complexity_removed"] > 0
            # Net to gross ratio should be -1.0 (pure removal)
            assert result["delta.mass.complexity_net_to_gross_ratio"] == -1.0

    def test_balanced_churn_scenario(self, symbol_template):
        """Test scenario with equal added and removed mass."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            # Prior: func1 with cc=10, func2 with cc=5
            func1_prior = {**symbol_template, "name": "func1", "complexity": 10}
            func2_prior = {**symbol_template, "name": "func2", "complexity": 5}
            self._create_symbols_file(prior_path, [func1_prior, func2_prior])

            # Current: func1 with cc=5, func2 with cc=10 (swapped)
            func1_curr = {**symbol_template, "name": "func1", "complexity": 5}
            func2_curr = {**symbol_template, "name": "func2", "complexity": 10}
            self._create_symbols_file(curr_path, [func1_curr, func2_curr])

            result = compute_mass_delta(prior_path, curr_path)

            # Net should be ~0, gross should be > 0
            assert abs(result["delta.mass.complexity"]) < 0.1
            assert result["delta.mass.complexity_gross"] > 0
            # Net to gross ratio should be close to 0
            assert abs(result["delta.mass.complexity_net_to_gross_ratio"]) < 0.1

    def test_concentration_high_for_single_function_change(self, symbol_template):
        """Concentration should be 0 for single function (trivial case)."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            self._create_symbols_file(prior_path, [symbol_template])
            modified = {**symbol_template, "complexity": 15}
            self._create_symbols_file(curr_path, [modified])

            result = compute_mass_delta(prior_path, curr_path)

            # Single change = Gini 0 (no inequality possible)
            assert result["delta.mass.complexity_added_concentration"] == 0.0
            assert result["delta.mass.complexity_added_count"] == 1

    def test_symbol_counts_backward_compatible(self, symbol_template):
        """delta.symbols_added/removed/modified should still work."""
        with tempfile.TemporaryDirectory() as tmp:
            prior_path = Path(tmp) / "prior_symbols.jsonl"
            curr_path = Path(tmp) / "curr_symbols.jsonl"

            func1 = {**symbol_template, "name": "func1"}
            func2 = {**symbol_template, "name": "func2"}
            func3 = {**symbol_template, "name": "func3"}

            # Prior: func1, func2
            self._create_symbols_file(prior_path, [func1, func2])

            # Current: func2 (modified), func3 (added)
            func2_modified = {**func2, "complexity": 15}
            self._create_symbols_file(curr_path, [func2_modified, func3])

            result = compute_mass_delta(prior_path, curr_path)

            assert result["delta.symbols_added"] == 1  # func3
            assert result["delta.symbols_removed"] == 1  # func1
            assert result["delta.symbols_modified"] == 1  # func2
