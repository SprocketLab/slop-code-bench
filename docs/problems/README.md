---
version: 1.0
last_updated: 2025-11-06
---

# Problem Authoring Guide

Welcome to the Slop Code problem authoring documentation. This guide helps you create evaluation problems that test coding agents on multi-checkpoint programming tasks.

## What is a Problem?

A problem is a self-contained evaluation package that tests an agent's ability to build software. Each problem consists of:

- **Specification**: What the agent must build (in `spec.md` files)
- **Test Cases**: Inputs and expected outputs to validate solutions
- **Checkpoints**: Progressive milestones that build on each other
- **Loader**: Discovers and loads test cases
- **Verifier**: Validates agent outputs against expected results

> **First time?** Start with the [Problem Design Philosophy](../contributing-problems/README.md) to understand what makes a good problem, then return here for implementation.

## Get Started

**New to problem authoring?** Follow the [**Step-by-Step Tutorial**](tutorial.md) to create your first working problem in 30 minutes.

**Need a quick skeleton?** Use the 2-minute quick start below.

## Quick Start: 2-Minute Skeleton

Create a problem skeleton in 5 steps:

```bash
# 1. Create problem directory
mkdir -p problems/my_problem/checkpoint_1/core

# 2. Create root config
cat > problems/my_problem/config.yaml << 'EOF'
name: my_problem
description: My first evaluation problem
adapter:
  type: cli
  tracked_files: ["output.txt"]
entry_file: solution
loader_script: loader.py
loader_entrypoint: Loader
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
        timeout: 30
    specification: spec.md
    state: Core Tests
EOF

# 3. Copy template loader and verifier (from repository root)
cp examples/yaml_joiner/problem/loader.py problems/my_problem/
cp examples/yaml_joiner/problem/verifier.py problems/my_problem/

# 4. Write your spec
echo "# Checkpoint 1: Build a CLI tool..." > problems/my_problem/checkpoint_1/spec.md
```

Now add test cases and customize the loader/verifier for your problem!

## Should I Use CLI or API Adapter?

Choose your adapter type based on what you're testing:

### CLI Adapter
**Use when testing:**
- Command-line tools
- Batch processing scripts
- File transformation utilities
- Data pipeline tools

**Example**: `file_backup` - CLI tool that schedules backup jobs

**Test case structure**: Directory-based, with `ARGS` files and input files

### API Adapter
**Use when testing:**
- REST APIs
- Web services
- Stateful server applications
- Request/response workflows

**Example**: `dynamic_config_service_api` - Versioned configuration API

**Test case structure**: YAML files with HTTP request/response definitions

### Playwright Adapter
**Use when testing:**
- Web UIs
- Interactive applications
- Browser-based workflows

*Note: Less common, see specialized docs if needed*

## Minimal Problem Structure

### CLI Problem (Directory-Based Cases)
```
problems/your_problem/
├── config.yaml              # Problem metadata & adapter config
├── loader.py                # Test case discovery
├── verifier.py              # Output validation
├── checkpoint_1/
│   ├── spec.md              # What agents must build
│   └── core/                # Test group
│       ├── test_case_1/     # Individual test case
│       │   ├── case.yaml    # Input & CLI arguments
│       │   └── expected.txt # Expected output
│       └── test_case_2/
│           ├── case.yaml
│           └── expected.txt
└── files/                   # Static assets (optional)
    └── shared_data/
```

### API Problem (YAML-Based Cases)
```
problems/your_problem/
├── config.yaml              # Problem metadata & adapter config
├── loader.py                # Test case discovery
├── verifier.py              # Output validation
└── checkpoint_1/
    ├── spec.md              # What agents must build
    ├── core/                # Test group
    │   ├── create_user.yaml     # POST /users
    │   ├── get_user.yaml        # GET /users/{id}
    │   └── update_user.yaml     # PATCH /users/{id}
    └── errors/              # Error handling tests
        ├── missing_field.yaml
        └── invalid_id.yaml
```

## Core Documentation

### Getting Started
- **[Quick Reference](quick-reference.md)** - One-page cheat sheet with everything you need
- **[Problem Structure](structure.md)** - Visual guide to problem organization
- **[Config Schema](config-schema.md)** - Complete field-by-field reference

### Essential Guides
- **[Test Case Authoring](test-cases.md)** - How to write effective test cases
- **[Checkpoint Design](checkpoints.md)** - When and how to split into checkpoints
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions

### Advanced Topics
- **[Group Organization](groups.md)** - Organizing test cases into groups
- **[Regression Testing](regression.md)** - Manual tests and automated importing
- **[Creating Loaders and Verifiers](../guides/creating-loaders-and-verifiers.md)** - Loader and verifier patterns
- **[Static Assets](../execution/assets.md)** - Managing shared files and data

### Examples
- **[Simple CLI Problem](examples/simple-cli.md)** - Walkthrough of `file_backup`
- **[Stateful API Problem](examples/stateful-api.md)** - Walkthrough of `dynamic_config_service_api`

### Comprehensive Guides
For in-depth information, see:
- **[Problem Authoring (Detailed)](../guides/problem-authoring.md)** - End-to-end authoring guide
- **[Creating Loaders and Verifiers](../guides/creating-loaders-and-verifiers.md)** - Protocol details and APIs

## Common Questions

**Q: What's the difference between a group and a checkpoint?**

A checkpoint is a milestone in problem progression (e.g., "basic functionality" → "add persistence"). A group is a collection of related test cases within a checkpoint (e.g., "core" success cases vs "errors" failure cases).

**Q: When should I create multiple checkpoints?**

Create multiple checkpoints when:
- Later features build on earlier ones
- You want to track incremental progress
- The full problem is too large for one specification

See [Checkpoint Design](checkpoints.md) for patterns.

**Q: Do I need to write a custom loader and verifier?**

Yes, but they're usually simple! Most loaders are <100 lines and follow standard patterns. Most verifiers are <50 lines and use framework helpers. See [Creating Loaders and Verifiers](../guides/creating-loaders-and-verifiers.md) for detailed guidance.

**Q: How do I debug test cases that aren't loading?**

1. Check file paths and names match `case_order` (for APIs)
2. Verify checkpoint config references the correct groups
3. Use the dashboard to see what cases were discovered
4. Test your loader directly (see [Troubleshooting](troubleshooting.md))

**Q: What's the difference between static_assets and group_files?**

- `static_assets`: Large shared files mounted from problem root (e.g., reference databases)
- `group_files`: Small files shared within a group (e.g., common JSON fixtures)

See [Static Assets](../execution/assets.md) and [Config Schema](config-schema.md).

## Real-World Examples

Browse existing problems in `problems/` for inspiration:

- **`file_backup`** - Simple CLI with YAML parsing and JSONL output
- **`dynamic_config_service_api`** - Stateful REST API with versioning
- **`eve_industry`** - Complex data processing with large static assets
- **`file_merger`** - CSV transformation with file I/O
- **`trajectory_api`** - API with resource creation and ID tracking

## Testing Your Problem

```bash
# Run agent on your problem
slop-code run \
  --agent configs/agents/haiku-4.5-claude-code.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/simple.jinja \
  --problem your_problem

# Evaluate results
uv run python -m slop_code.entrypoints.cli eval \
  outputs/run_name \
  --pass-policy all-cases

# View in dashboard
uv run python -m slop_code.visualization.app outputs/
```

## Next Steps

1. **Follow the [Step-by-Step Tutorial](tutorial.md)** to create your first problem (30 min)
2. **Read the [Quick Reference](quick-reference.md)** for templates and commands
3. **Study an [Example Problem](examples/simple-cli.md)** similar to yours
4. **Check the [Config Schema](config-schema.md)** when writing configs
5. **Reference [Troubleshooting](troubleshooting.md)** when stuck

Happy problem authoring! 🚀
