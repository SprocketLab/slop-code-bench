#!/usr/bin/env bash
set -euo pipefail

workflow=artnet # openspec or artnet
case "$workflow" in
  openspec)
    agent_config=configs/agents/codex-openspec.yaml
    environment_config=docker-python3.12-uv
    save_dir=outputs/codex_openspec
    ;;
  artnet)
    agent_config=configs/agents/codex-artnet.yaml
    environment_config=docker-python3.12-uv-artnet
    save_dir=outputs/codex_artnet
    ;;
  *)
    echo "workflow must be openspec or artnet" >&2
    exit 2
    ;;
esac

problems=(
  # Easy
  cfgpipe
  code_search
  env_manager
  execution_server
  forge

  # Medium
  # circuit_eval
  # database_migration
  # file_query_tool
  # mvvault
  # trajectory_api

  # Hard
  # eve_industry
  # meshctl
  # mocked_http
  # recli
  # test_translator
  # rejector
)

problem_args=()
for problem in "${problems[@]}"; do
  problem_args+=(--problem "$problem")
done

exec uv run slop-code run \
  --agent "$agent_config" \
  --environment "$environment_config" \
  --prompt checkpoint-only \
  --model codex_auth/gpt-5.5 \
  --num-workers 3 \
  "${problem_args[@]}" \
  thinking=high \
  pass_policy=any-case \
  save_dir="$save_dir" \
  'save_template=${model.name}_${thinking}_${now:%Y%m%dT%H%M}'
