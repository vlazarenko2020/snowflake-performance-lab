#!/usr/bin/env bash
# 0-generate_plus_load.sh YYYY-MM-DD
#
# Step 1: generate the day's CSV files (1-generate_tasty_bytes_data.py)
# Step 2: load them into Snowflake      (2-load_tasty_bytes_data.py)
#
# Example: ./0-generate_plus_load.sh 2026-11-08

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -ne 1 ] || ! [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || ! date -d "$1" >/dev/null 2>&1; then
  cat >&2 <<MSG
ERROR: exactly one parameter is required: the date, in the format YYYY-MM-DD.
It is the day to generate and load data for (it sets the folder name, the
order/customer ID range and the random seed).

Usage:   $0 YYYY-MM-DD
Example: $0 2026-11-08
MSG
  exit 2
fi

RUN_DATE="$1"
cd "$SCRIPT_DIR"

echo "=== Step 1/2: generate data for $RUN_DATE ==="
uv run 1-generate_tasty_bytes_data.py "$RUN_DATE"

echo
echo "=== Step 2/2: load data for $RUN_DATE into Snowflake ==="
uv run 2-load_tasty_bytes_data.py "$RUN_DATE"
