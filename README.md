# Snowflake Performance Lab

A small sandbox for practising Snowflake query performance tuning. It runs a set of **deliberately inefficient queries** against the built-in `SNOWFLAKE_SAMPLE_DATA` (TPC-H) dataset. You can then open the slow queries in Query History / Query Profile, diagnose what went wrong, and rewrite them.

## What's inside

```
.
├── .env.example                     # Config template (copy to .env)
└── deliberately_inefficient_queries/
    ├── run_deliberately_inefficient_queries.sh   # Generates the SQL and runs it via Snowflake CLI
    └── inefficient_queries.sql                   # Reference copy of the queries
```

## The queries

Each query demonstrates one common anti-pattern:

| # | Anti-pattern | What to look for in Query Profile |
|---|--------------|-----------------------------------|
| 1 | Exploding join (join on a low-cardinality column) | Row count blow-up on the join node |
| 2 | Poor pruning + `SELECT *` (function on the filter column) | Partitions scanned ≈ partitions total |
| 3 | Large sort on a wide text column | Spilling to local/remote storage |
| 4 | Correlated subquery | Repeated aggregation / join expansion |
| 5 | `COUNT(DISTINCT)` + leading-wildcard `LIKE '%…%'` | Full scan, expensive distinct |
| 6 | Window function with no `PARTITION BY` | Single-node global sort |

Challenge: for each query, find the bottleneck, rewrite it, and compare the before/after runtime and bytes scanned.

## Prerequisites

- A Snowflake account with access to `SNOWFLAKE_SAMPLE_DATA`
- [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index) (`pip install snowflake-cli`)
- A configured connection (`snow connection add`, then `snow connection test -c default`)
- A role with `USAGE` on a working database and schema, plus `CREATE TABLE` on that schema. Queries 2, 3, 4 and 6 write to temporary tables so the CLI doesn't download millions of rows.

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
| `WORK_DB` / `WORK_SCHEMA` | Where temporary tables are created |
| `SQL_FILE` | *(optional)* Override the generated SQL file location |

## Usage

```bash
./deliberately_inefficient_queries/run_deliberately_inefficient_queries.sh
```

For a long run in the background:

```bash
nohup ./deliberately_inefficient_queries/run_deliberately_inefficient_queries.sh &
```

The script writes the SQL to `tmp/inefficient_queries.sql` and runs it with `snow sql`. The final `SELECT` prints the query IDs.

## Finding the queries afterwards

In Snowsight go to **Monitoring → Query History** and filter by query tag `inefficient_demo`. Open a query and inspect **Query Profile**.

## Notes

- `USE_CACHED_RESULT = FALSE` is set so reruns actually execute instead of returning cached results.
- Temporary tables are dropped automatically when the session ends.
- The queries on `TPCH_SF10` scan tens of millions of rows. Use a small warehouse and expect some credit consumption.
- `.env`, `tmp/` and `nohup.out` are git-ignored. Never commit credentials.
