#!/usr/bin/env bash
# run_deliberately_inefficient_queries.sh



# Connection: you need one configured first. Set it up with snow connection add, then check it with snow connection test -c default.
# Temporary tables: queries #2, #3, #4 and #6 write their output to temporary tables. 
#                   Otherwise the CLI would download millions of rows to your terminal. 
#                   This is also why the script needs WORK_DB/WORK_SCHEMA: your role must have USAGE on that database and schema plus CREATE TABLE on the schema. 
#                   The temp tables are dropped automatically when the session ends.
# Result cache: USE_CACHED_RESULT = FALSE stops reruns from coming back instantly from the cache, which would leave nothing to investigate.
# Finding the queries: the last SELECT prints the query IDs. In Query History, filter on the query tag inefficient_demo to find them.



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
SQL_FILE="${SQL_FILE:-$SCRIPT_DIR/tmp/inefficient_queries.sql}"
mkdir -p "$(dirname "$SQL_FILE")"

command -v snow >/dev/null || { echo "Snowflake CLI 'snow' not found. Install: pip install snowflake-cli"; exit 1; }

cat > "$SQL_FILE" <<'SQL'
ALTER SESSION SET QUERY_TAG = 'inefficient_demo';
ALTER SESSION SET USE_CACHED_RESULT = FALSE;   -- force real execution on reruns

-- 1. Exploding join
SELECT COUNT(*)
FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o1
JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o2
  ON o1.o_orderpriority = o2.o_orderpriority
WHERE o1.o_orderdate = '1995-01-01';

-- 2. Poor pruning + SELECT *
CREATE OR REPLACE TEMPORARY TABLE demo_q2 AS
SELECT *
FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF10.LINEITEM
WHERE TO_VARCHAR(l_shipdate, 'YYYY-MM') = '1996-03';

-- 3. Large sort (spilling)
CREATE OR REPLACE TEMPORARY TABLE demo_q3 AS
SELECT l_orderkey, l_partkey, l_extendedprice, l_comment
FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF10.LINEITEM
ORDER BY l_comment;

-- 4. Correlated subquery
CREATE OR REPLACE TEMPORARY TABLE demo_q4 AS
SELECT c.c_custkey, c.c_name,
       (SELECT SUM(o.o_totalprice)
        FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o
        WHERE o.o_custkey = c.c_custkey) AS total_spend
FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER c;

-- 5. COUNT DISTINCT + leading-wildcard LIKE
SELECT COUNT(DISTINCT l_comment)
FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF10.LINEITEM
WHERE l_comment LIKE '%furious%';

-- 6. Unpartitioned window function
CREATE OR REPLACE TEMPORARY TABLE demo_q6 AS
SELECT o_orderkey,
       ROW_NUMBER() OVER (ORDER BY o_totalprice DESC) AS rn
FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF10.ORDERS;

-- List the query IDs for Query History
SELECT query_id, LEFT(query_text, 60) AS query_text, total_elapsed_time/1000 AS secs
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION())
WHERE query_tag = 'inefficient_demo'
ORDER BY start_time;
SQL

echo "Running $SQL_FILE with connection '$CONNECTION' (role=$ROLE, wh=$WAREHOUSE)..."
snow sql -c "$CONNECTION" \
  --role "$ROLE" \
  --warehouse "$WAREHOUSE" \
  --database "$WORK_DB" \
  --schema "$WORK_SCHEMA" \
  -f "$SQL_FILE"

