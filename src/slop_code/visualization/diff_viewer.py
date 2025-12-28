import streamlit as st
from pathlib import Path
import json
import difflib
import os
import re
import argparse
import sys
import streamlit.components.v1 as components

# Try importing pygments
try:
    import pygments
    from pygments.lexers import get_lexer_for_filename, guess_lexer, TextLexer
    from pygments.formatters import HtmlFormatter
    from pygments import highlight
    HAS_PYGMENTS = True
except ImportError:
    HAS_PYGMENTS = False

st.set_page_config(layout="wide", page_title="Diff Viewer")

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        return None

def get_subdirs(path):
    if not path.exists():
        return []
    return sorted([d.name for d in path.iterdir() if d.is_dir() and not d.name.startswith('.')])

def get_checkpoints(problem_path):
    if not problem_path.exists():
        return []
    # Find directories matching checkpoint_N
    checkpoints = []
    for d in problem_path.iterdir():
        if d.is_dir() and d.name.startswith("checkpoint_"):
            try:
                num = int(d.name.split('_')[1])
                checkpoints.append((num, d.name))
            except ValueError:
                pass
    checkpoints.sort(key=lambda x: x[0])
    return [c[1] for c in checkpoints]

def get_snapshot_files(snapshot_dir):
    files = {}
    if not snapshot_dir.exists():
        return files
    for p in snapshot_dir.rglob("*"):
        if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
            rel_path = p.relative_to(snapshot_dir)
            try:
                files[str(rel_path)] = p.read_text(errors='replace')
            except Exception:
                files[str(rel_path)] = "<binary or unreadable>"
    return files

def get_highlighted_line(line, lexer):
    if not HAS_PYGMENTS:
        return line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        # highlight returns a full div/pre block usually, we need inner span
        # nowrap=True returns just the spans
        return highlight(line, lexer, HtmlFormatter(nowrap=True, noclasses=True)).rstrip("\n")
    except Exception:
        return line

def generate_modern_diff(a, b, name_a, name_b, filename=""):
    # 1. Determine Lexer
    lexer = None
    if HAS_PYGMENTS:
        try:
            lexer = get_lexer_for_filename(filename)
        except pygments.util.ClassNotFound:
            try:
                lexer = guess_lexer(a if a else b)
            except pygments.util.ClassNotFound:
                lexer = TextLexer()
    
    # 2. Split lines
    lines_a = a.splitlines()
    lines_b = b.splitlines()
    
    # 3. Compute diff opcodes
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
    opcodes = matcher.get_opcodes()
    
    # 4. Build Table Rows
    rows = []
    
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                code = get_highlighted_line(lines_a[i], lexer)
                rows.append(f"""
                <tr>
                    <td class="lineno">{i+1}</td>
                    <td class="code">{code}</td>
                    <td class="lineno">{j+1}</td>
                    <td class="code">{code}</td>
                </tr>
                """)
        elif tag == 'replace':
            # Align replaced lines as best as possible (simplistic)
            len_a = i2 - i1
            len_b = j2 - j1
            max_len = max(len_a, len_b)
            
            for k in range(max_len):
                ia = i1 + k
                jb = j1 + k
                
                cell_a = ""
                num_a = ""
                if ia < i2:
                    cell_a = get_highlighted_line(lines_a[ia], lexer)
                    num_a = ia + 1
                
                cell_b = ""
                num_b = ""
                if jb < j2:
                    cell_b = get_highlighted_line(lines_b[jb], lexer)
                    num_b = jb + 1
                
                rows.append(f"""
                <tr>
                    <td class="lineno { 'diff-del-num' if num_a else ''}">{num_a}</td>
                    <td class="code { 'diff-mod' if num_a else ''}">{cell_a}</td>
                    <td class="lineno { 'diff-add-num' if num_b else ''}">{num_b}</td>
                    <td class="code { 'diff-mod' if num_b else ''}">{cell_b}</td>
                </tr>
                """)
        elif tag == 'delete':
            for i in range(i1, i2):
                code = get_highlighted_line(lines_a[i], lexer)
                rows.append(f"""
                <tr>
                    <td class="lineno diff-del-num">{i+1}</td>
                    <td class="code diff-del">{code}</td>
                    <td class="lineno"></td>
                    <td class="code"></td>
                </tr>
                """)
        elif tag == 'insert':
            for j in range(j1, j2):
                code = get_highlighted_line(lines_b[j], lexer)
                rows.append(f"""
                <tr>
                    <td class="lineno"></td>
                    <td class="code"></td>
                    <td class="lineno diff-add-num">{j+1}</td>
                    <td class="code diff-add">{code}</td>
                </tr>
                """)

    # 5. Assemble HTML
    table_body = "".join(rows)
    
    style = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 0; background-color: white; }
        .diff-container {
            width: 100%;
            overflow-x: auto;
            border: 1px solid #d0d7de;
            border-radius: 6px;
        }
        table.diff { 
            border-collapse: collapse; 
            width: 100%; 
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            font-size: 12px;
        }
        .diff th { 
            background-color: #f6f8fa; 
            color: #57606a; 
            padding: 5px 10px; 
            text-align: left;
            border-bottom: 1px solid #d0d7de;
        }
        .diff td { 
            padding: 0px 10px; 
            vertical-align: top;
            line-height: 20px;
            white-space: pre; 
        }
        .lineno {
            color: #6e7781;
            text-align: right;
            width: 1%;
            min-width: 40px;
            user-select: none;
            background-color: white;
            border-right: 1px solid #eee;
            padding-right: 10px !important;
        }
        .code {
            width: 49%;
            color: #24292f;
        }
        
        /* Diff Colors (GitHub Style) */
        .diff-add { background-color: #e6ffec; }
        .diff-add-num { background-color: #ccffd8; }
        
        .diff-del { background-color: #ffebe9; }
        .diff-del-num { background-color: #ffd7d5; }
        
        .diff-mod { background-color: #fff5b1; }
        
        /* Pygments Inline Styles handling */
        pre { margin: 0; }
        
        /* Navigation Controls */
        .nav-controls {
            position: fixed;
            top: 10px;
            right: 20px;
            z-index: 1000;
            background: white;
            border: 1px solid #d0d7de;
            border-radius: 6px;
            padding: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            font-family: sans-serif;
            font-size: 12px;
        }
        .nav-controls button {
            cursor: pointer;
            padding: 5px 10px;
            margin-left: 5px;
            background: #f6f8fa;
            border: 1px solid #d0d7de;
            border-radius: 4px;
            color: #24292f;
        }
        .nav-controls button:hover {
            background: #f3f4f6;
        }
    </style>
    
    <script>
        let changes = [];
        let currentIndex = -1;

        function initChanges() {
            // Find all rows that have a diff class (modified, added, deleted)
            const diffCells = document.querySelectorAll('td.code.diff-add, td.code.diff-del, td.code.diff-mod');
            const rows = new Set();
            diffCells.forEach(cell => rows.add(cell.parentElement));
            
            const sortedRows = Array.from(rows).sort((a, b) => a.rowIndex - b.rowIndex);
            
            changes = [];
            if (sortedRows.length > 0) {
                changes.push(sortedRows[0]);
                for (let i = 1; i < sortedRows.length; i++) {
                    // Start a new block if rows are not adjacent (separated by context)
                    if (sortedRows[i].rowIndex > sortedRows[i-1].rowIndex + 1) {
                        changes.push(sortedRows[i]);
                    }
                }
            }
            console.log(`Found ${changes.length} change blocks.`);
        }

        function scrollToChange(index) {
            if (changes.length === 0) return;
            
            if (index < 0) index = 0;
            if (index >= changes.length) index = changes.length - 1;
            
            currentIndex = index;
            const el = changes[currentIndex];
            
            // Scroll element into view
            el.scrollIntoView({behavior: 'smooth', block: 'center'});
        }

        function nextChange() {
            scrollToChange(currentIndex + 1);
        }

        function prevChange() {
            scrollToChange(currentIndex - 1);
        }

        // Initialize on load
        window.onload = initChanges;
    </script>
    """
    
    html = f"""
    {style}
    <div class="nav-controls">
        <button onclick="prevChange()">▲ Prev</button>
        <button onclick="nextChange()">▼ Next</button>
    </div>
    <div class="diff-container">
        <table class="diff">
            <thead>
                <tr>
                    <th colspan="2">{name_a}</th>
                    <th colspan="2">{name_b}</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>
    </div>
    """
    return html

# Parse command line arguments
default_run_dir = "outputs/variance_runs/gpt-5.2_0.74.0_low_just-solve/20251227T1027"

try:
    # Use parse_known_args to ignore streamlit's own arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=str)
    args, _ = parser.parse_known_args()
    if args.run_dir:
        default_run_dir = args.run_dir
except Exception:
    pass

# Sidebar
st.sidebar.title("Configuration")
run_dir_input = st.sidebar.text_input("Run Directory", value=default_run_dir)
run_path = Path(run_dir_input)

if not run_path.exists():
    st.error(f"Directory not found: {run_path}")
    st.stop()

problems = get_subdirs(run_path)
selected_problem = st.sidebar.selectbox("Select Problem", problems)

if not selected_problem:
    st.warning("No problems found in run directory.")
    st.stop()

problem_path = run_path / selected_problem
checkpoints = get_checkpoints(problem_path)

if not checkpoints:
    st.warning("No checkpoints found for this problem.")
    st.stop()

# Select Checkpoints
idx_b = len(checkpoints) - 1
idx_a = max(0, idx_b - 1)

col1, col2 = st.sidebar.columns(2)
ckpt_a_name = col1.selectbox("Checkpoint A (Base)", checkpoints, index=idx_a)
ckpt_b_name = col2.selectbox("Checkpoint B (Target)", checkpoints, index=idx_b)

ckpt_a_path = problem_path / ckpt_a_name
ckpt_b_path = problem_path / ckpt_b_name

# Main Content
st.title(f"Problem: {selected_problem}")
st.write(f"Comparing **{ckpt_a_name}** → **{ckpt_b_name}**")

# --- Overview Section (Based on Checkpoint B) ---
st.header("Overview (Target Checkpoint)")

eval_path = ckpt_b_path / "evaluation.json"
quality_path = ckpt_b_path / "quality_analysis" / "overall_quality.json"

eval_data = load_json(eval_path)
quality_data = load_json(quality_path)

col_ov1, col_ov2 = st.columns(2)

with col_ov1:
    st.subheader("Evaluation")
    if eval_data:
        pass_counts = eval_data.get("pass_counts", {})
        st.write("Pass Counts:", pass_counts)
        
        # Expandable details
        with st.expander("Test Details"):
            tests = eval_data.get("tests", {})
            if isinstance(tests, dict):
                for suite, results in tests.items():
                    st.write(f"**{suite}**")
                    failed = results.get("failed", [])
                    passed = results.get("passed", [])
                    if failed:
                        st.error(f"Failed ({len(failed)}): {', '.join(failed[:5])}{'...' if len(failed)>5 else ''}")
                    if passed:
                        st.success(f"Passed ({len(passed)})")
            elif isinstance(tests, list):
                st.write("**Tests (Legacy List Format)**")
                passed_tests = [t.get("id") for t in tests if t.get("status") == "passed"]
                failed_tests = [t.get("id") for t in tests if t.get("status") != "passed"]
                
                if failed_tests:
                    st.error(f"Failed ({len(failed_tests)}): {', '.join(failed_tests[:5])}{'...' if len(failed_tests)>5 else ''}")
                if passed_tests:
                    st.success(f"Passed ({len(passed_tests)})")
            else:
                st.warning(f"Unknown tests format: {type(tests)}")
    else:
        st.warning("No evaluation.json found.")

with col_ov2:
    st.subheader("Quality Analysis")
    if quality_data:
        ast_grep = quality_data.get("ast_grep", {})
        lint = quality_data.get("lint", {})
        complexity = quality_data.get("complexity", {})
        lines = quality_data.get("lines", {})
        
        metrics = {
            "Violations (AST)": ast_grep.get("violations"),
            "Lint Errors": lint.get("errors"),
            "Complexity (CC Sum)": complexity.get("cc_sum"),
            "LOC": lines.get("loc")
        }
        st.json(metrics)
        
        with st.expander("Full Quality Data"):
            st.json(quality_data)
    else:
        st.warning("No quality analysis found.")

st.markdown("---")

# --- Diff Viewer ---
st.header("Snapshot Diffs")

snapshot_a = get_snapshot_files(ckpt_a_path / "snapshot")
snapshot_b = get_snapshot_files(ckpt_b_path / "snapshot")

all_files = sorted(set(snapshot_a.keys()) | set(snapshot_b.keys()))

if not all_files:
    st.info("No files found in snapshots.")
else:
    selected_file = st.selectbox("Select File", all_files)
    
    content_a = snapshot_a.get(selected_file, "")
    content_b = snapshot_b.get(selected_file, "")
    
    if content_a == content_b:
        st.info("Files are identical.")
    else:
        diff_html = generate_modern_diff(
            content_a, 
            content_b, 
            f"{ckpt_a_name} (Before)", 
            f"{ckpt_b_name} (After)",
            filename=selected_file
        )
        components.html(diff_html, height=800, scrolling=True)
