#!/usr/bin/env bash
# Generate HTML metrics report from a JSONL event log.
#
# Usage:
#   bash shell/report.sh <metrics.jsonl> [output.html]
#   bash shell/report.sh .godotmaker/metrics.jsonl
#   bash shell/report.sh .godotmaker/metrics.jsonl report.html
#
# If no output path is given, writes to <input_dir>/report.html

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ $# -lt 1 ]; then
    echo "Usage: bash shell/report.sh <metrics.jsonl> [output.html]"
    echo ""
    echo "Examples:"
    echo "  bash shell/report.sh .godotmaker/metrics.jsonl"
    echo "  bash shell/report.sh path/to/metrics.jsonl"
    exit 1
fi

INPUT="$1"
if [ $# -ge 2 ]; then
    OUTPUT="$2"
else
    OUTPUT="$(dirname "$INPUT")/report.html"
fi

cd "$REPO_ROOT"
python -m hooks.metrics.reporter "$INPUT" -o "$OUTPUT"
echo "Open: $OUTPUT"
