---
version: 1.0
last_updated: 2025-01-04
---

# viz

Visualization tools for inspecting agent submissions and changes.

## Subcommands

| Command | Description |
|---------|-------------|
| [`diff`](#diff) | Launch diff viewer for checkpoint changes |

---

## diff

Launch the diff viewer visualization to inspect changes between checkpoints.

### Quick Start

```bash
# Visualize diffs for a run
slop-code viz diff outputs/my_run

# The diff viewer will launch in a web browser
```

### Usage

```bash
slop-code viz diff [RUN_DIR]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RUN_DIR` | No | Path to the run directory to visualize. If omitted, you can browse to select a run. |

### Behavior

The diff viewer is an interactive Streamlit application that displays:

- **Checkpoint Navigation**: Browse through checkpoints in a run
- **File Changes**: See which files were added, modified, or deleted
- **Diff Visualization**: View line-by-line differences between checkpoints
- **Statistics**: Display metrics on code churn (lines added/removed)

### How It Works

1. Loads `diff.json` files from checkpoint directories
2. Parses change information (created/modified/deleted files)
3. Renders interactive UI for browsing diffs
4. Supports filtering by file type and change type

### Examples

```bash
# Visualize a specific run
slop-code viz diff outputs/opus-4.5/claude_code-2.0.51_just-solve_none_20250104

# Launch and then browse to select a run
slop-code viz diff
```

### Output

The diff viewer launches a local web server (default port 8501) and opens a browser tab. The UI displays:

- Run selection (if no directory provided)
- Checkpoint selector (tabs or dropdown)
- File list with change indicators
- Side-by-side diff view
- Statistics panel with code churn metrics

### Requirements

- Streamlit must be installed (included with slop-code-bench)
- A web browser to view the visualization
- The run directory must contain `diff.json` files for checkpoints

### Troubleshooting

**Diff files missing:**

```bash
# Repopulate diffs if they're missing
slop-code utils repopulate-diffs outputs/my_run
```

**Browser doesn't open automatically:**

- Open `http://localhost:8501` manually in your browser
- Check that port 8501 is not already in use

**Visualization errors:**

- Verify the run directory contains completed checkpoints
- Check that `diff.json` files are valid JSON
- Run with `--help` to see Streamlit-specific options

## See Also

- [utils repopulate-diffs](utils.md#repopulate-diffs) - Regenerate diff.json files
- [Execution: Snapshots](../execution/snapshots.md) - How snapshots and diffs work
- [metrics run-results](../metrics/run-results.md) - Analyzing code churn metrics
