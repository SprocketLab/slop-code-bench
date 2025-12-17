#!/usr/bin/env python3
"""
Convert all checkpoint 3 hidden tests to use app.db files instead of inline setup migrations.
"""
import json
from pathlib import Path

import yaml


def convert_case_yaml(test_dir):
    """Convert a test's case.yaml to use app.db file."""
    case_path = test_dir / "case.yaml"

    # Read the current case.yaml
    with open(case_path) as f:
        case_data = yaml.safe_load(f)

    # Find the final migration (migration.json)
    migration_json_content = None
    for input_file in case_data.get('input_files', []):
        if input_file.get('path') == 'migration.json':
            migration_json_content = input_file.get('content')
            break

    if not migration_json_content:
        print(f"✗ Could not find migration.json in {test_dir.name}")
        return False

    # Create new case.yaml with app.db file reference
    new_case_yaml = f"""arguments: migrate migration.json app.db
input_files:
- path: app.db
  file_type: sqlite
- content: {json.dumps(migration_json_content)}
  file_type: json
  path: migration.json
tracked_files:
- app.db
expected_status: 0
"""

    # Write the new case.yaml
    with open(case_path, 'w') as f:
        f.write(new_case_yaml)

    print(f"✓ Updated {test_dir.name}/case.yaml")
    return True


def main():
    """Convert all test case.yaml files."""
    hidden_dir = Path(__file__).parent

    test_dirs = [d for d in hidden_dir.iterdir() if d.is_dir()]

    success_count = 0
    for test_dir in sorted(test_dirs):
        if convert_case_yaml(test_dir):
            success_count += 1

    print(f"\n✓ Updated {success_count}/{len(test_dirs)} case.yaml files!")


if __name__ == "__main__":
    main()
