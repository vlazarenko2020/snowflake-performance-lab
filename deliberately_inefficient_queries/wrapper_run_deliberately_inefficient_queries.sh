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
TARGET_SCRIPT_TO_RUN="$SCRIPT_DIR/run_deliberately_inefficient_queries.sh"

AMOUNT_OF_INSTANCES_TO_START="${1:-1}"
MIN_INTERVAL_IN_SECS=1
MAX_INTERVAL_IN_SECS=15
[[ "$AMOUNT_OF_INSTANCES_TO_START" =~ ^[1-9][0-9]*$ ]] || { echo "Usage: $0 [INSTANCES]  (INSTANCES must be a positive integer, default 1)" >&2; exit 1; }
[ -x "$TARGET_SCRIPT_TO_RUN" ] || { echo "Not found or not executable: $TARGET_SCRIPT_TO_RUN" >&2; exit 1; }

mkdir -p "$SCRIPT_DIR/tmp"
STAMP="$(date +%Y%m%d_%H%M%S)"

echo "Starting $AMOUNT_OF_INSTANCES_TO_START instance(s), ${MIN_INTERVAL_IN_SECS}-${MAX_INTERVAL_IN_SECS}s apart (random)."
for i in $(seq 1 "$AMOUNT_OF_INSTANCES_TO_START"); do
  LOG_FILE="$SCRIPT_DIR/tmp/run_${STAMP}_instance${i}.log"
  # Separate SQL file per instance so concurrent runs don't overwrite each other's file.
  SQL_FILE="$SCRIPT_DIR/tmp/inefficient_queries_${STAMP}_instance${i}.sql" \
    nohup "$TARGET_SCRIPT_TO_RUN" > "$LOG_FILE" 2>&1 &
  echo "  instance $i: PID $!  log: $LOG_FILE"
  if [ "$i" -lt "$AMOUNT_OF_INSTANCES_TO_START" ]; then
    DELAY=$(( RANDOM % (MAX_INTERVAL_IN_SECS - MIN_INTERVAL_IN_SECS + 1) + MIN_INTERVAL_IN_SECS ))
    echo "  waiting ${DELAY}s before next instance..."
    sleep "$DELAY"
  fi
done
echo "All instances started."
echo "Follow with: tail -f $SCRIPT_DIR/tmp/run_${STAMP}_instance*.log"
