import argparse
from pathlib import Path

import yaml

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
parser.add_argument("--cfg", "-c", type=Path, action="append")
parser.add_argument("--cfg-dir", "-cd", type=Path, action="append")
args = parser.parse_args()

out_cfg = {}


def nested_set(out, path: list[str], value):
    for key in path[:-1]:
        if key not in out:
            out[key] = {}
        out = out[key]
    out[path[-1]] = value
    return out


done_paths = set()

print("PATHS:")
for cfg_path in sorted(args.cfg or []):
    if cfg_path.name in out_cfg:
        print(f"SKIPPING: {cfg_path.name}")
        continue

    print(f"{cfg_path}")
    with open(cfg_path) as f:
        cfg_data = yaml.safe_load(f)
    out_cfg[cfg_path.name] = cfg_data
    done_paths.add(cfg_path.name)

print("DIRS:")
for cfg_dir in sorted(args.cfg_dir or []):
    print(f"{cfg_dir}")
    for cfg_path in sorted(cfg_dir.rglob("*.yaml")):
        if str(cfg_path.relative_to(cfg_dir.parent)) in done_paths:
            print(f"SKIPPING: {cfg_path}")
            continue
        print(f"{cfg_path}")
        with open(cfg_path) as f:
            cfg_data = yaml.safe_load(f)
        done_paths.add(str(cfg_path.relative_to(cfg_dir.parent)))
        out_cfg[str(cfg_path.relative_to(cfg_dir.parent))] = cfg_data

with open(args.output, "w") as f:
    yaml.dump(out_cfg, f)
