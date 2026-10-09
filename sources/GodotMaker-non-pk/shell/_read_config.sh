#!/usr/bin/env bash
# Read a value from the selected agent's godotmaker.yaml.
# Usage: bash _read_config.sh <key>
#   e.g. GODOT=$(bash ".agents/skills/_read_config.sh" godot_path)
#
# Falls back to default if godotmaker.yaml doesn't exist or key is missing.
# Defaults: godot_path → "godot"
set -euo pipefail

KEY="${1:-}"
if [ -z "$KEY" ]; then
    echo "Usage: $0 <key>" >&2
    exit 1
fi

# Locate godotmaker.yaml relative to this script.
# The helper is published at .claude/skills/_read_config.sh or
# .agents/skills/_read_config.sh, so ../godotmaker.yaml resolves to the
# selected agent's project-local config.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../godotmaker.yaml"

# Defaults
declare -A DEFAULTS=(
    [godot_path]="godot"
)

if [ -f "$CONFIG_FILE" ]; then
    # Simple yaml parser: extract value for key (handles quoted and unquoted values)
    value=$(sed -n "s/^${KEY}:[[:space:]]*//p" "$CONFIG_FILE" | sed 's/^"\(.*\)"$/\1/' | sed "s/^'\(.*\)'$/\1/" | head -1)
    if [ -n "$value" ]; then
        echo "$value"
        exit 0
    fi
fi

# Fall back to default
if [ -n "${DEFAULTS[$KEY]+x}" ]; then
    echo "${DEFAULTS[$KEY]}"
else
    echo "Error: key '$KEY' not found in godotmaker.yaml and no default available" >&2
    exit 1
fi
