"""Tests for program call graph construction and metrics."""

from __future__ import annotations

import networkx as nx

from slop_code.metrics.languages.python.graph import build_dependency_graph
from slop_code.metrics.languages.python.graph import compute_graph_metrics


class TestBuildCallGraph:
    """Tests for build_dependency_graph function (now builds call graphs)."""

    def test_single_function_no_calls(self, tmp_path):
        """Test graph with a single function and no calls."""
        (tmp_path / "main.py").write_text(
            "def main():\n    x = 1\n    return x\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        assert graph.number_of_nodes() == 1
        assert graph.number_of_edges() == 0
        assert any("::main" in node for node in graph.nodes)

    def test_single_call(self, tmp_path):
        """Test graph with one function calling another."""
        (tmp_path / "main.py").write_text(
            "def helper():\n    return 1\n\n"
            "def main():\n    return helper()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1

        # Find the nodes
        main_node = [n for n in graph.nodes if "::main" in n][0]
        helper_node = [n for n in graph.nodes if "::helper" in n][0]

        assert graph.has_edge(main_node, helper_node)

    def test_method_calls(self, tmp_path):
        """Test graph with method calls."""
        (tmp_path / "main.py").write_text(
            "class MyClass:\n"
            "    def method1(self):\n"
            "        return 1\n"
            "\n"
            "    def method2(self):\n"
            "        return self.method1()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        # Should have 2 method nodes
        assert graph.number_of_nodes() == 2

        # method2 should call method1
        method2_node = [n for n in graph.nodes if ".method2" in n][0]
        method1_node = [n for n in graph.nodes if ".method1" in n][0]

        assert graph.has_edge(method2_node, method1_node)

    def test_edge_weight_multiple_calls(self, tmp_path):
        """Test edge weight when function is called multiple times."""
        (tmp_path / "main.py").write_text(
            "def util():\n    return 1\n\n"
            "def main():\n"
            "    a = util()\n"
            "    b = util()\n"
            "    c = util()\n"
            "    return a + b + c\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        main_node = [n for n in graph.nodes if "::main" in n][0]
        util_node = [n for n in graph.nodes if "::util" in n][0]

        edge_data = graph.get_edge_data(main_node, util_node)
        # 3 calls to util()
        assert edge_data["weight"] == 3

    def test_chain_calls(self, tmp_path):
        """Test graph with chained calls (A -> B -> C)."""
        (tmp_path / "main.py").write_text(
            "def c():\n    return 1\n\n"
            "def b():\n    return c()\n\n"
            "def a():\n    return b()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        assert graph.number_of_nodes() == 3
        assert graph.number_of_edges() == 2

        a_node = [n for n in graph.nodes if "::a" in n][0]
        b_node = [n for n in graph.nodes if "::b" in n][0]
        c_node = [n for n in graph.nodes if "::c" in n][0]

        assert graph.has_edge(a_node, b_node)
        assert graph.has_edge(b_node, c_node)

    def test_fan_out_pattern(self, tmp_path):
        """Test fan-out pattern (A calls B, C, D)."""
        (tmp_path / "main.py").write_text(
            "def b():\n    return 1\n\n"
            "def c():\n    return 2\n\n"
            "def d():\n    return 3\n\n"
            "def main():\n"
            "    return b() + c() + d()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        assert graph.number_of_nodes() == 4
        assert graph.number_of_edges() == 3

        main_node = [n for n in graph.nodes if "::main" in n][0]
        b_node = [n for n in graph.nodes if "::b" in n][0]
        c_node = [n for n in graph.nodes if "::c" in n][0]
        d_node = [n for n in graph.nodes if "::d" in n][0]

        assert graph.has_edge(main_node, b_node)
        assert graph.has_edge(main_node, c_node)
        assert graph.has_edge(main_node, d_node)

    def test_circular_calls(self, tmp_path):
        """Test graph with circular function calls (mutual recursion)."""
        (tmp_path / "main.py").write_text(
            "def a(n):\n"
            "    if n > 0:\n"
            "        return b(n-1)\n"
            "    return 0\n\n"
            "def b(n):\n"
            "    if n > 0:\n"
            "        return a(n-1)\n"
            "    return 1\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 2

        a_node = [n for n in graph.nodes if "::a" in n][0]
        b_node = [n for n in graph.nodes if "::b" in n][0]

        assert graph.has_edge(a_node, b_node)
        assert graph.has_edge(b_node, a_node)

    def test_cross_file_calls(self, tmp_path):
        """Test calls across multiple files."""
        (tmp_path / "utils.py").write_text("def helper():\n    return 42\n")
        (tmp_path / "main.py").write_text(
            "from utils import helper\n\n"
            "def main():\n    return helper()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        # Should have functions from both files
        assert graph.number_of_nodes() == 2

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        helper_node = [n for n in graph.nodes if "utils.py::helper" in n][0]

        # main() should call helper()
        assert graph.has_edge(main_node, helper_node)

    def test_nonexistent_entrypoint(self, tmp_path):
        """Test with nonexistent entrypoint returns empty graph."""
        graph = build_dependency_graph(tmp_path, tmp_path / "nonexistent.py")

        assert graph.number_of_nodes() == 0
        assert graph.number_of_edges() == 0


class TestComputeGraphMetrics:
    """Tests for compute_graph_metrics function."""

    def test_empty_graph(self):
        """Test metrics for an empty graph."""
        graph = nx.DiGraph()

        metrics = compute_graph_metrics(graph)

        assert metrics.node_count == 0
        assert metrics.edge_count == 0
        assert metrics.cyclic_dependency_mass == 0.0
        assert metrics.propagation_cost == 0.0
        assert metrics.dependency_entropy == 0.0

    def test_single_node_no_edges(self):
        """Test metrics for a graph with one node and no edges."""
        graph = nx.DiGraph()
        graph.add_node("main.py::func")

        metrics = compute_graph_metrics(graph)

        assert metrics.node_count == 1
        assert metrics.edge_count == 0
        assert metrics.cyclic_dependency_mass == 0.0
        assert metrics.propagation_cost == 0.0
        assert metrics.dependency_entropy == 0.0

    def test_simple_edge(self):
        """Test metrics for a simple two-node graph with one edge."""
        graph = nx.DiGraph()
        graph.add_edge("a.py::func_a", "b.py::func_b")

        metrics = compute_graph_metrics(graph)

        assert metrics.node_count == 2
        assert metrics.edge_count == 1
        assert metrics.cyclic_dependency_mass == 0.0
        assert metrics.propagation_cost == 0.5
        assert metrics.dependency_entropy == 0.0


class TestCyclicDependencyMass:
    """Tests for cyclic dependency mass metric."""

    def test_no_cycles(self):
        """Test CY = 0 when there are no cycles."""
        graph = nx.DiGraph()
        graph.add_edge("a.py::f1", "b.py::f2", weight=1)
        graph.add_edge("b.py::f2", "c.py::f3", weight=1)

        metrics = compute_graph_metrics(graph)

        assert metrics.cyclic_dependency_mass == 0.0

    def test_simple_cycle(self):
        """Test CY for a simple 2-function cycle (mutual recursion)."""
        graph = nx.DiGraph()
        graph.add_edge("a.py::f1", "a.py::f2", weight=1)
        graph.add_edge("a.py::f2", "a.py::f1", weight=1)

        metrics = compute_graph_metrics(graph)

        # All edges are in the SCC, so CY = 2/2 = 1.0
        assert metrics.cyclic_dependency_mass == 1.0


class TestPropagationCost:
    """Tests for propagation cost metric."""

    def test_no_edges(self):
        """Test PC = 0 for disconnected functions."""
        graph = nx.DiGraph()
        graph.add_node("a.py::f1")
        graph.add_node("a.py::f2")
        graph.add_node("a.py::f3")

        metrics = compute_graph_metrics(graph)

        assert metrics.propagation_cost == 0.0

    def test_linear_chain(self):
        """Test PC for a linear chain (f1 -> f2 -> f3)."""
        graph = nx.DiGraph()
        graph.add_edge("a.py::f1", "a.py::f2")
        graph.add_edge("a.py::f2", "a.py::f3")

        metrics = compute_graph_metrics(graph)

        # Reachable pairs: (f1,f2), (f1,f3), (f2,f3) = 3
        # Total pairs: 3 * 2 = 6
        # PC = 3/6 = 0.5
        assert metrics.propagation_cost == 0.5

    def test_full_connectivity(self):
        """Test PC = 1.0 for fully connected graph."""
        graph = nx.DiGraph()
        # All functions call all others
        funcs = ["a.py::f1", "a.py::f2", "a.py::f3"]
        for u in funcs:
            for v in funcs:
                if u != v:
                    graph.add_edge(u, v)

        metrics = compute_graph_metrics(graph)

        # Every function reaches every other function
        # PC = 1.0
        assert metrics.propagation_cost == 1.0


class TestDependencyEntropy:
    """Tests for dependency entropy metric."""

    def test_single_dependency(self):
        """Test ENT = 0 when each function has at most 1 call."""
        graph = nx.DiGraph()
        graph.add_edge("a.py::f1", "a.py::f2", weight=1)
        graph.add_edge("a.py::f2", "a.py::f3", weight=1)

        metrics = compute_graph_metrics(graph)

        # All functions have out-degree <= 1, so ENT = 0
        assert metrics.dependency_entropy == 0.0

    def test_uniform_distribution(self):
        """Test ENT ≈ 1 for uniform distribution."""
        graph = nx.DiGraph()
        # Function f1 calls f2, f3, f4 equally
        graph.add_edge("a.py::f1", "a.py::f2", weight=1)
        graph.add_edge("a.py::f1", "a.py::f3", weight=1)
        graph.add_edge("a.py::f1", "a.py::f4", weight=1)

        metrics = compute_graph_metrics(graph)

        # Uniform distribution -> max entropy -> H_n = 1.0
        # f1 has H_n=1, f2/f3/f4 have H_n=0 (out-degree 0)
        # Average: 1/4 = 0.25
        assert abs(metrics.dependency_entropy - 0.25) < 0.001


class TestCallResolution:
    """Tests for proper call resolution to avoid false edges."""

    def test_same_function_name_different_files_no_false_edges(self, tmp_path):
        """Test that same function names in different files don't create false edges.

        This tests the bug where suffix matching creates edges to ALL functions
        with the same name, even if they're in different files.
        """
        # Create two files with same function name "process"
        (tmp_path / "module_a.py").write_text(
            "def process():\n"
            "    return 'A'\n"
        )
        (tmp_path / "module_b.py").write_text(
            "def process():\n"
            "    return 'B'\n"
        )
        # Main imports both modules, but only calls module_a.process
        (tmp_path / "main.py").write_text(
            "from module_a import process\n"
            "import module_b\n\n"
            "def main():\n"
            "    # Should only call module_a.process, NOT module_b.process\n"
            "    return process()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        # Find the nodes
        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        process_a_node = [n for n in graph.nodes if "module_a.py::process" in n][0]
        process_b_node = [n for n in graph.nodes if "module_b.py::process" in n][0]

        # main() should call module_a.process
        assert graph.has_edge(main_node, process_a_node), \
            "Should have edge from main to module_a.process"

        # main() should NOT call module_b.process (this is the bug!)
        assert not graph.has_edge(main_node, process_b_node), \
            "Should NOT have edge from main to module_b.process (false edge bug)"

    def test_qualified_module_calls(self, tmp_path):
        """Test that qualified calls like 'module.function()' are resolved correctly.

        This tests the bug where only the method name is extracted from qualified
        calls, losing the module context.
        """
        (tmp_path / "utils.py").write_text(
            "def helper():\n"
            "    return 42\n"
        )
        (tmp_path / "main.py").write_text(
            "import utils\n\n"
            "def helper():\n"
            "    # Local helper, different from utils.helper\n"
            "    return 0\n\n"
            "def main():\n"
            "    # Qualified call - should call utils.helper, not local helper\n"
            "    return utils.helper()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        utils_helper_node = [n for n in graph.nodes if "utils.py::helper" in n][0]
        local_helper_node = [n for n in graph.nodes if "main.py::helper" in n][0]

        # main() should call utils.helper (qualified call)
        assert graph.has_edge(main_node, utils_helper_node), \
            "Should have edge from main to utils.helper"

        # main() should NOT call local helper
        assert not graph.has_edge(main_node, local_helper_node), \
            "Should NOT have edge from main to local helper (wrong resolution)"

    def test_same_file_resolution_priority(self, tmp_path):
        """Test that same-file calls are resolved correctly when imported names exist.

        When a function calls 'helper()', and both a local helper and an imported
        helper exist, the local one should take priority.
        """
        (tmp_path / "external.py").write_text(
            "def helper():\n"
            "    return 'external'\n"
        )
        (tmp_path / "main.py").write_text(
            "from external import helper as ext_helper\n\n"
            "def helper():\n"
            "    # Local helper\n"
            "    return 'local'\n\n"
            "def main():\n"
            "    # Unqualified call should resolve to local helper first\n"
            "    return helper()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        local_helper_node = [n for n in graph.nodes if "main.py::helper" in n][0]
        external_helper_node = [n for n in graph.nodes if "external.py::helper" in n][0]

        # main() should call local helper (same-file priority)
        assert graph.has_edge(main_node, local_helper_node), \
            "Should have edge from main to local helper"

        # main() should NOT call external helper
        assert not graph.has_edge(main_node, external_helper_node), \
            "Should NOT have edge from main to external helper"


class TestFailureModes:
    """Tests for known failure modes that need fixing."""

    def test_dotted_import_resolution(self, tmp_path):
        """Test that dotted imports like 'from package.submodule import func' resolve.

        FAILURE MODE: Current implementation only matches file_path.stem == module_name,
        which fails for dotted imports where module_name is 'package.submodule'.
        """
        # Create package structure
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "submodule.py").write_text(
            "def helper():\n"
            "    return 42\n"
        )
        (tmp_path / "main.py").write_text(
            "from mypackage.submodule import helper\n\n"
            "def main():\n"
            "    return helper()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        helper_nodes = [n for n in graph.nodes if "helper" in n]

        # Should find the helper in mypackage/submodule.py
        assert len(helper_nodes) >= 1, "Should find helper function"
        helper_node = [n for n in graph.nodes if "submodule.py::helper" in n][0]

        # main() should call mypackage.submodule.helper
        assert graph.has_edge(main_node, helper_node), \
            "Should resolve dotted import 'from mypackage.submodule import helper'"

    def test_relative_import_same_package(self, tmp_path):
        """Test that relative imports like 'from . import sibling' resolve.

        FAILURE MODE: Current implementation doesn't handle relative imports at all.
        """
        # Create package structure
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text(
            "def helper():\n"
            "    return 42\n"
        )
        (pkg / "main.py").write_text(
            "from . import utils\n\n"
            "def main():\n"
            "    return utils.helper()\n"
        )

        graph = build_dependency_graph(tmp_path, pkg / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        helper_node = [n for n in graph.nodes if "utils.py::helper" in n][0]

        # main() should call utils.helper via relative import
        assert graph.has_edge(main_node, helper_node), \
            "Should resolve relative import 'from . import utils'"

    def test_relative_import_from_module(self, tmp_path):
        """Test that relative imports like 'from .sibling import func' resolve.

        FAILURE MODE: Current implementation doesn't handle relative imports at all.
        """
        # Create package structure
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text(
            "def helper():\n"
            "    return 42\n"
        )
        (pkg / "main.py").write_text(
            "from .utils import helper\n\n"
            "def main():\n"
            "    return helper()\n"
        )

        graph = build_dependency_graph(tmp_path, pkg / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        helper_node = [n for n in graph.nodes if "utils.py::helper" in n][0]

        # main() should call helper via relative import
        assert graph.has_edge(main_node, helper_node), \
            "Should resolve relative import 'from .utils import helper'"

    def test_local_variable_type_tracking(self, tmp_path):
        """Test that method calls on local variables are resolved.

        FAILURE MODE: Current implementation returns None for qualified calls
        where the qualifier is not 'self' or a known import.
        """
        (tmp_path / "client.py").write_text(
            "class Client:\n"
            "    def connect(self):\n"
            "        return True\n"
            "\n"
            "    def send(self, data):\n"
            "        return len(data)\n"
        )
        (tmp_path / "main.py").write_text(
            "from client import Client\n\n"
            "def main():\n"
            "    c = Client()\n"
            "    c.connect()\n"
            "    return c.send('hello')\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        connect_node = [n for n in graph.nodes if "Client.connect" in n][0]
        send_node = [n for n in graph.nodes if "Client.send" in n][0]

        # main() should call Client.connect and Client.send
        assert graph.has_edge(main_node, connect_node), \
            "Should resolve c.connect() to Client.connect via type tracking"
        assert graph.has_edge(main_node, send_node), \
            "Should resolve c.send() to Client.send via type tracking"

    def test_super_resolution(self, tmp_path):
        """Test that super().method() calls resolve to parent class methods.

        FAILURE MODE: Current implementation doesn't track class hierarchy
        or resolve super() calls.
        """
        (tmp_path / "main.py").write_text(
            "class Base:\n"
            "    def process(self):\n"
            "        return 'base'\n"
            "\n"
            "class Child(Base):\n"
            "    def process(self):\n"
            "        result = super().process()\n"
            "        return f'child: {result}'\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        child_process = [n for n in graph.nodes if "Child.process" in n][0]
        base_process = [n for n in graph.nodes if "Base.process" in n][0]

        # Child.process should call Base.process via super()
        assert graph.has_edge(child_process, base_process), \
            "Should resolve super().process() to Base.process"

    def test_identifier_vs_dotted_name_import(self, tmp_path):
        """Test that simple identifier imports are parsed correctly.

        FAILURE MODE: Line 126 checks 'child.type == "dotted_name"' but
        simple imports like 'from module import func' use 'identifier' type.
        """
        (tmp_path / "utils.py").write_text(
            "def func():\n"
            "    return 42\n"
        )
        (tmp_path / "main.py").write_text(
            "from utils import func\n\n"
            "def main():\n"
            "    return func()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")

        main_node = [n for n in graph.nodes if "main.py::main" in n][0]
        func_node = [n for n in graph.nodes if "utils.py::func" in n][0]

        # main() should call utils.func
        assert graph.has_edge(main_node, func_node), \
            "Should parse 'from utils import func' correctly (identifier type)"


class TestGraphIntegration:
    """Integration tests combining graph building and metrics."""

    def test_realistic_functions(self, tmp_path):
        """Test on realistic function structure."""
        (tmp_path / "main.py").write_text(
            "def process_data(data):\n"
            "    validated = validate(data)\n"
            "    return transform(validated)\n\n"
            "def validate(data):\n"
            "    return data if data else {}\n\n"
            "def transform(data):\n"
            "    return str(data)\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")
        metrics = compute_graph_metrics(graph)

        # 3 functions
        assert metrics.node_count == 3
        # process_data calls validate and transform
        assert metrics.edge_count == 2

        # No cycles in this clean structure
        assert metrics.cyclic_dependency_mass == 0.0

    def test_metrics_serialization(self, tmp_path):
        """Test that GraphMetrics can be serialized to JSON."""
        (tmp_path / "main.py").write_text(
            "def helper():\n    return 1\n\n"
            "def main():\n    return helper()\n"
        )

        graph = build_dependency_graph(tmp_path, tmp_path / "main.py")
        metrics = compute_graph_metrics(graph)

        # Test Pydantic serialization
        json_dict = metrics.model_dump(mode="json")

        assert "node_count" in json_dict
        assert "edge_count" in json_dict
        assert "cyclic_dependency_mass" in json_dict
        assert "propagation_cost" in json_dict
        assert "dependency_entropy" in json_dict
        assert json_dict["node_count"] == 2
        assert json_dict["edge_count"] == 1
