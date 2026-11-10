# Snowflake Performance Lab

A small sandbox for practising Snowflake query performance tuning. It runs a set of **deliberately inefficient queries** against the built-in `SNOWFLAKE_SAMPLE_DATA` (TPC-H) dataset. You can then open the slow queries in Query History / Query Profile, diagnose what went wrong, and rewrite them.

## What's inside

```
.
├── .env.example                     # Config template (copy to .env)
└── deliberately_inefficient_queries/
    ├── run_deliberately_inefficient_queries.sh   # Generates the SQL and runs it via Snowflake CLI
    ├── wrapper_run_deliberately_inefficient_queries.sh  # Launches N concurrent instances in the background
    └── inefficient_queries/all_in_one_file.sql   # Query pool (50 numbered queries) the script picks from
```

A second, separate part of the repo, `FROSTBYTE_TASTY_BYTES_daily_updates/`, generates fictional daily CSV batches for the Tasty Bytes tables and loads them into Snowflake (`./0-generate_plus_load.sh YYYY-MM-DD`). It has its own README.

## The queries

`all_in_one_file.sql` holds 50 numbered queries (`-- N. Description`, each ending with `;`). Each run picks a random 2-6 of them and sends them to Snowflake together in one session. Every query demonstrates one common anti-pattern (for example a function on a filter column that defeats pruning, a Cartesian or exploding join, a correlated subquery, an unpartitioned window function, or a huge sort), and the description in its header comment names it.

Every query returns at most 100 rows: the heavy work runs server-side, and the final result is aggregated or ends in `ORDER BY ... LIMIT 100` (the `ORDER BY` forces the full computation). That way the CLI never downloads large results to your terminal. Keep this rule when adding queries.

In Query Profile, look for things like: row-count blow-up on join nodes, partitions scanned close to partitions total, spilling to local/remote storage, repeated aggregation from correlated subqueries, and single-node global sorts.

Challenge: for each query, find the bottleneck, rewrite it, and compare the before/after runtime and bytes scanned.

## Prerequisites

- A Snowflake account with access to `SNOWFLAKE_SAMPLE_DATA`
- [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index) (`pip install snowflake-cli`)
- A configured connection (`snow connection add`, then `snow connection test -c default`)
- A role with `USAGE` on a working database and schema, plus `CREATE TABLE` on that schema. The queries currently create no tables (they return at most 100 rows), but the script still requires `WORK_DB`/`WORK_SCHEMA` and runs in that context.

## Setup

```bash
cp .env.example .env
# edit .env: CONNECTION, ROLE, WAREHOUSE, WORK_DB, WORK_SCHEMA
```

| Variable | Description |
|----------|-------------|
| `CONNECTION` | Connection name from `~/.snowflake/config.toml` |
| `ROLE` | Role to run as |
| `WAREHOUSE` | Warehouse to run on (a small one is fine) |
| `WORK_DB` / `WORK_SCHEMA` | Database and schema the queries run in (and where temporary tables would be created) |
| `SQL_FILE` | *(optional)* Override the generated SQL file location |

## Usage

```bash
./deliberately_inefficient_queries/run_deliberately_inefficient_queries.sh
```

To launch several instances in the background, use the wrapper:

```bash
./deliberately_inefficient_queries/wrapper_run_deliberately_inefficient_queries.sh      # 1 instance (default)
./deliberately_inefficient_queries/wrapper_run_deliberately_inefficient_queries.sh 5    # 5 instances
```

The wrapper starts the instances one at a time, waiting a random 1-15 seconds between launches. They overlap, so they run concurrently, which is useful for generating concurrent load and queueing. Each instance gets its own log (`tmp/run_<timestamp>_instance<N>.log`) and its own generated SQL file in `tmp/`. Follow progress with `tail -f tmp/run_<timestamp>_instance*.log`.

Running the main script directly picks a random 2-6 distinct queries from `all_in_one_file.sql`, writes them into one SQL file (`tmp/inefficient_queries.sql`) and runs it with a single `snow sql` call, so all of them execute in one Snowflake session. Between queries the file contains `SELECT SYSTEM$WAIT(n)` with a random 1-15 s pause, so the delays happen inside the session (the warehouse stays busy waiting). If a query fails, the CLI is expected to stop the rest of that file. Query IDs are not printed; use Query History (below).

### How the two scripts divide the work

| | Wrapper | Main script |
|---|---|---|
| File | `wrapper_run_deliberately_inefficient_queries.sh [INSTANCES]` | `run_deliberately_inefficient_queries.sh` |
| Responsibility | Parallelism: launches INSTANCES copies of the main script in the background (`nohup`) | One instance's whole run |
| Randomness | Random 1-15 s delay between instance launches (`MIN_INTERVAL_IN_SECS`/`MAX_INTERVAL_IN_SECS`) | Random 2-6 queries per session, picked from the pool, with a random 1-15 s `SYSTEM$WAIT` between queries (`MIN_QUERIES`/`MAX_QUERIES`/`MIN_DELAY`/`MAX_DELAY`) |
| Snowflake work | None | Loads `.env`, checks variables, extracts queries, runs each with `snow sql` |
| Files | Per-instance log `tmp/run_<stamp>_instance<N>.log` and `SQL_FILE` `tmp/inefficient_queries_<stamp>_instance<N>.sql` | Writes the session preamble plus all picked queries to `SQL_FILE`, then one `snow sql` call |

The only link between them is the `SQL_FILE` environment variable: the wrapper sets it per instance so concurrent runs don't overwrite each other's file, and the main script reads it. The main script knows nothing about the wrapper. With 5 instances you get up to 5 overlapping sessions of 2-6 queries each (up to 30 queries), so size the warehouse accordingly.

## Finding the queries afterwards

In Snowsight go to **Monitoring → Query History** and filter by query tag `inefficient_demo`. Open a query and inspect **Query Profile**.

## Notes

- `USE_CACHED_RESULT = FALSE` is set so reruns actually execute instead of returning cached results.
- Temporary tables are dropped automatically when the session ends.
- The queries on `TPCH_SF10` scan tens of millions of rows. Use a small warehouse and expect some credit consumption. Each wrapper instance repeats the full set, so credit use scales with the instance count.
- `.env`, `tmp/` and `nohup.out` are git-ignored. Never commit credentials.
