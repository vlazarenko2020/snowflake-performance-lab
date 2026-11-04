#!/usr/bin/env bash
# wrapper_run_deliberately_inefficient_queries.sh [INSTANCES]
#
# Starts INSTANCES copies (default: 1) of run_deliberately_inefficient_queries.sh in the
# background, waiting a random 1-15 seconds between launches. Instances overlap, so they
# run concurrently. Each one gets its own log and its own generated SQL file in tmp/.
#
# Usage:
#   ./wrapper_run_deliberately_inefficient_queries.sh          # 1 instance
#   ./wrapper_run_deliberately_inefficient_queries.sh 5        # 5 instances, random 1-15 s apart

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/run_deliberately_inefficient_queries.sh"

INSTANCES="${1:-1}"
MIN_INTERVAL=1
MAX_INTERVAL=15
[[ "$INSTANCES" =~ ^[1-9][0-9]*$ ]] || { echo "Usage: $0 [INSTANCES]  (INSTANCES must be a positive integer, default 1)" >&2; exit 1; }
[ -x "$TARGET" ] || { echo "Not found or not executable: $TARGET" >&2; exit 1; }

mkdir -p "$SCRIPT_DIR/tmp"
STAMP="$(date +%Y%m%d_%H%M%S)"

echo "Starting $INSTANCES instance(s), ${MIN_INTERVAL}-${MAX_INTERVAL}s apart (random)."
for i in $(seq 1 "$INSTANCES"); do
  LOG_FILE="$SCRIPT_DIR/tmp/run_${STAMP}_instance${i}.log"
  # Separate SQL file per instance so concurrent runs don't overwrite each other's file.
  SQL_FILE="$SCRIPT_DIR/tmp/inefficient_queries_${STAMP}_instance${i}.sql" \
    nohup "$TARGET" > "$LOG_FILE" 2>&1 &
  echo "  instance $i: PID $!  log: $LOG_FILE"
  if [ "$i" -lt "$INSTANCES" ]; then
    DELAY=$(( RANDOM % (MAX_INTERVAL - MIN_INTERVAL + 1) + MIN_INTERVAL ))
    echo "  waiting ${DELAY}s before next instance..."
    sleep "$DELAY"
  fi
done
echo "All instances started. Follow with: tail -f $SCRIPT_DIR/tmp/run_${STAMP}_instance*.log"
