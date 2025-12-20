# Checkpoint 2: Directory Recursion

Extend the YAML joiner to support recursive directory scanning.

## New Requirements

- Accept directory path via `-cd` flag
- Recursively find all `.yaml` files in the directory
- Support static asset directories via placeholder syntax

## Usage

```bash
# Join all YAML files in a directory recursively
python solution.py result.yaml -cd ./configs/

# Use static assets
python solution.py result.yaml -cd {{static:cfg_dir}}
```

## Example

Given directory structure:
```
local/
  A.yaml: original: local_A
  Z/
    ZZ.yaml: original: local_Z_ZZ
```

Output (`result.yaml`):
```yaml
local/A.yaml:
  original: local_A
local/Z/ZZ.yaml:
  original: local_Z_ZZ
```
