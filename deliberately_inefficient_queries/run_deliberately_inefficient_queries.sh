#!/usr/bin/env bash
# run_deliberately_inefficient_queries.sh



# Connection: you need one configured first. Set it up with snow connection add, then check it with snow connection test -c default.
# Selection:        each run picks a random number of queries (2-6) and that many distinct random
#                   queries from inefficient_queries/all_in_one_file.sql. All of them go into ONE SQL file
#                   and are sent to Snowflake in ONE snow sql call, i.e. one session. Between queries the
#                   file contains SELECT SYSTEM$WAIT(<random 1-15>) so the pauses happen inside the session.
# Temporary tables: queries that write to temporary tables need WORK_DB/WORK_SCHEMA: your role must have
#                   USAGE on that database and schema plus CREATE TABLE on the schema.
#                   The temp tables are dropped automatically when the session ends.
# Result cache: USE_CACHED_RESULT = FALSE stops reruns from coming back instantly from the cache, which would leave nothing to investigate.
# Finding the queries: in Query History, filter on the query tag inefficient_demo.



set -euo pipefail

# Set SCRIPT_DIR to the absolute path of the directory containing the script, no matter where you ran it from. 
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# .env lives in the parent directory of this script. It is optional, but if it exists, it is sourced to set environment variables.
[ -f "$SCRIPT_DIR/../.env" ] && { set -a; source "$SCRIPT_DIR/../.env"; set +a; }


# --- Settings (required: set them in .env or the environment; see .env.example) ---
: "${CONNECTION:?CONNECTION is not set (connection name from ~/.snowflake/config.toml). Set it in .env}"
: "${ROLE:?ROLE is not set. Set it in .env}"
: "${WAREHOUSE:?WAREHOUSE is not set. Set it in .env}"
: "${WORK_DB:?WORK_DB is not set (needed for temp tables). Set it in .env}"
: "${WORK_SCHEMA:?WORK_SCHEMA is not set (needed for temp tables). Set it in .env}"

# Optional
SQL_FILE="${SQL_FILE:-$SCRIPT_DIR/tmp/inefficient_queries.sql}"   # generated once per run (one session)
QUERIES_FILE="${QUERIES_FILE:-$SCRIPT_DIR/inefficient_queries/all_in_one_file.sql}"
MIN_QUERIES=2
MAX_QUERIES=6  # per session
MIN_DELAY=1
MAX_DELAY=15
mkdir -p "$(dirname "$SQL_FILE")"

command -v snow >/dev/null || { echo "Snowflake CLI 'snow' not found. Install: pip install snowflake-cli"; exit 1; }
[ -f "$QUERIES_FILE" ] || { echo "Queries file not found: $QUERIES_FILE"; exit 1; }

# Print the query numbered $1 (its "-- N. Description" header line plus the SQL up to the next header).
get_query() {
  local pick="$1" printing=false line
  while IFS= read -r line; do
    if [[ "$line" =~ ^--[[:space:]]+([0-9]+)\. ]]; then
      # Header line: print from here only if it is the picked query number
      if [[ "${BASH_REMATCH[1]}" == "$pick" ]]; then
        printing=true
      else
        printing=false
      fi
    fi
    if $printing; then
      printf '%s\n' "$line"
    fi
  done < "$QUERIES_FILE"
}

TOTAL=$(grep -cE '^-- [0-9]+\.' "$QUERIES_FILE")
[ "$TOTAL" -ge "$MIN_QUERIES" ] || { echo "Need at least $MIN_QUERIES queries in $QUERIES_FILE, found $TOTAL"; exit 1; }

# Random number of queries (2-6, capped by what the file has), then that many distinct random query numbers.
MAX=$(( MAX_QUERIES < TOTAL ? MAX_QUERIES : TOTAL ))
COUNT=$(( RANDOM % (MAX - MIN_QUERIES + 1) + MIN_QUERIES ))
mapfile -t PICKS < <(shuf -i 1-"$TOTAL" -n "$COUNT")

# Build ONE SQL file: session preamble, then the picked queries separated by random SYSTEM$WAIT pauses.
{
  echo "ALTER SESSION SET QUERY_TAG = 'inefficient_demo';"
  echo "ALTER SESSION SET USE_CACHED_RESULT = FALSE;   -- force real execution on reruns"
  for idx in "${!PICKS[@]}"; do
    if [ "$idx" -gt 0 ]; then
      DELAY=$(( RANDOM % (MAX_DELAY - MIN_DELAY + 1) + MIN_DELAY ))
      echo
      echo "SELECT SYSTEM\$WAIT($DELAY);   -- pause ${DELAY}s inside the session"
    fi
    echo
    get_query "${PICKS[$idx]}"    # get the query from the all_in_one_file.sql file
  done
} > "$SQL_FILE"

echo "Running $COUNT of $TOTAL queries (#${PICKS[*]}) in one session with connection '$CONNECTION' (role=$ROLE, wh=$WAREHOUSE)..."
echo "SQL file: $SQL_FILE"
snow sql -c "$CONNECTION" \
  --role "$ROLE" \
  --warehouse "$WAREHOUSE" \
  --database "$WORK_DB" \
  --schema "$WORK_SCHEMA" \
  -f "$SQL_FILE"

echo "Done. In Query History, filter on the query tag inefficient_demo."
