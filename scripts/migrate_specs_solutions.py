#!/usr/bin/env python3
"""
Migrate specs and solutions to the new directory structure.

Old structure:
    problems/problem_name/checkpoint_N/spec.md
    problems/problem_name/checkpoint_N/solution/

New structure:
    problems/problem_name/checkpoint_N.md
    problems/problem_name/solutions/checkpoint_N/

This script COPIES files (does not delete originals).
"""

import argparse
import re
import shutil
from pathlib import Path


def find_checkpoints(problem_dir: Path) -> list[Path]:
    """Find all checkpoint_N directories in a problem."""
    pattern = re.compile(r"^checkpoint_\d+$")
    checkpoints = []
    for child in problem_dir.iterdir():
        if child.is_dir() and pattern.match(child.name):
            checkpoints.append(child)
    return sorted(checkpoints, key=lambda p: int(p.name.split("_")[1]))


def migrate_problem(problem_dir: Path, dry_run: bool = False) -> dict[str, list[str]]:
    """Migrate a single problem to the new structure."""
    results = {"specs": [], "solutions": [], "skipped": []}

    checkpoints = find_checkpoints(problem_dir)
    if not checkpoints:
        return results

    for checkpoint_dir in checkpoints:
        checkpoint_name = checkpoint_dir.name

        # Migrate spec.md -> checkpoint_N.md
        spec_src = checkpoint_dir / "spec.md"
        spec_dst = problem_dir / f"{checkpoint_name}.md"
        if spec_src.exists():
            if spec_dst.exists():
                results["skipped"].append(f"{spec_dst} already exists")
            else:
                if not dry_run:
                    shutil.copy2(spec_src, spec_dst)
                results["specs"].append(f"{spec_src} -> {spec_dst}")

        # Migrate solution/ -> solutions/checkpoint_N/
        solution_src = checkpoint_dir / "solution"
        solutions_dir = problem_dir / "solutions"
        solution_dst = solutions_dir / checkpoint_name
        if solution_src.exists() and solution_src.is_dir():
            if solution_dst.exists():
                results["skipped"].append(f"{solution_dst} already exists")
            else:
                if not dry_run:
                    solutions_dir.mkdir(exist_ok=True)
                    shutil.copytree(solution_src, solution_dst)
                results["solutions"].append(f"{solution_src} -> {solution_dst}")

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "problems",
        nargs="*",
        help="Specific problem names to migrate (default: all)",
    )
    parser.add_argument(
        "--problems-dir",
        type=Path,
        default=Path(__file__).parent.parent / "problems",
        help="Path to problems directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    problems_dir = args.problems_dir.resolve()
    if not problems_dir.exists():
        print(f"Error: Problems directory not found: {problems_dir}")
        return 1

    # Get list of problems to migrate
    if args.problems:
        problem_dirs = [problems_dir / name for name in args.problems]
        for p in problem_dirs:
            if not p.exists():
                print(f"Error: Problem not found: {p}")
                return 1
    else:
        problem_dirs = [
            p for p in problems_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]

    if args.dry_run:
        print("DRY RUN - no changes will be made\n")

    total_specs = 0
    total_solutions = 0
    total_skipped = 0

    for problem_dir in sorted(problem_dirs):
        results = migrate_problem(problem_dir, dry_run=args.dry_run)

        if results["specs"] or results["solutions"] or results["skipped"]:
            print(f"\n{problem_dir.name}:")

            for item in results["specs"]:
                print(f"  [spec] {item}")
            for item in results["solutions"]:
                print(f"  [solution] {item}")
            for item in results["skipped"]:
                print(f"  [skipped] {item}")

            total_specs += len(results["specs"])
            total_solutions += len(results["solutions"])
            total_skipped += len(results["skipped"])

    print(f"\n{'=' * 40}")
    print(f"Total specs migrated: {total_specs}")
    print(f"Total solutions migrated: {total_solutions}")
    print(f"Total skipped (already exist): {total_skipped}")

    if args.dry_run:
        print("\nRun without --dry-run to apply changes")

    return 0


if __name__ == "__main__":
    exit(main())
