#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["snowflake-snowpark-python", "python-dotenv"]
# ///
"""Load one day of generated Tasty Bytes CSV files into Snowflake with Snowpark.

Run 1-generate_tasty_bytes_data.py first, then:

    uv run 2-load_tasty_bytes_data.py YYYY-MM-DD [DATA_DIR] [--force] [--dry-run]
    e.g. uv run 2-load_tasty_bytes_data.py 2026-11-08 ./data

What it does, in order:
  0. skips every fact-table file that COPY_HISTORY (last 14 days) shows as already loaded (unless --force),
  1. creates the internal stage if it does not exist,
  2. PUTs DATA_DIR/<date>/*.csv to @<stage>/<date>/,
  3. lookup tables (country, franchise, location, truck, menu): COPY into a temporary table, then MERGE
     into the real table, so re-running a day updates rows instead of duplicating them,
  4. fact tables (customer_loyalty, order_header, order_detail): COPY INTO the real table. Snowflake skips
     files it has already loaded, so re-running a day does not insert duplicates unless you pass --force.

Columns are matched by the CSV header names (PARSE_HEADER + MATCH_BY_COLUMN_NAME), so the tables must
already exist with those column names.

Settings come from the environment or the repo's git-ignored .env (same as the performance-lab scripts):
    CONNECTION              connection name in ~/.snowflake/config.toml        (required)
                            Only the NAME is read here. Account, user, authentication, role, warehouse,
                            database and schema all come from that connection; ROLE and WAREHOUSE in
                            .env are ignored by this script.
    TASTY_DB                default FROSTBYTE_TASTY_BYTES_2
    TASTY_SCHEMA            default RAW_POS       (stage and POS tables)
    TASTY_CUSTOMER_SCHEMA   default RAW_CUSTOMER  (CUSTOMER_LOYALTY table)
    TASTY_STAGE             default DAILY_LOAD
"""
import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# One entry per CSV file, in the order the files are loaded:
#   (file name without ".csv", target table name, which schema the table lives in, merge key columns)
# - "pos" / "customer" are looked up in the `schemas` dict inside main() (RAW_POS / RAW_CUSTOMER by default).
# - Merge key columns present  -> lookup table: its rows repeat every day, so we MERGE (update or insert).
# - Merge key columns = None   -> fact table: every day brings new rows, so a plain COPY INTO is enough.
TABLES = [
    ("country", "COUNTRY", "pos", ["CITY_ID"]),       # one row per city, so CITY_ID is the unique key
    ("franchise", "FRANCHISE", "pos", ["FRANCHISE_ID"]),
    ("location", "LOCATION", "pos", ["LOCATION_ID"]),
    ("truck", "TRUCK", "pos", ["TRUCK_ID"]),
    ("menu", "MENU", "pos", ["MENU_ITEM_ID"]),
    ("customer_loyalty", "CUSTOMER_LOYALTY", "customer", None),
    ("order_header", "ORDER_HEADER", "pos", None),
    ("order_detail", "ORDER_DETAIL", "pos", None),
]

# How COPY INTO reads the CSV files:
#   PARSE_HEADER = TRUE                  use the first row as column names (needed for MATCH_BY_COLUMN_NAME)
#   FIELD_OPTIONALLY_ENCLOSED_BY = '"'   fields may be wrapped in double quotes (the health JSON column is)
#   EMPTY_FIELD_AS_NULL = TRUE           an empty value (e.g. no customer on an order) becomes NULL
FILE_FORMAT = ("(TYPE = CSV PARSE_HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '\"' "
               "EMPTY_FIELD_AS_NULL = TRUE)")


def csv_header(path):
    """Return the column names (first row) of a CSV file as a list. Used to build the MERGE statement."""
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def f_loaded_fact_files(session, db, schemas, run_date):
    """Return the set of fact-table file stems (e.g. 'order_header') that COPY_HISTORY shows as loaded for `run_date`.

    Uses <db>.INFORMATION_SCHEMA.COPY_HISTORY, which only keeps the last 14 days and is kept per table
    (truncating or recreating a table wipes its history). A day older than 14 days cannot be verified, so
    the answer is an empty set. Every fact table is checked, so a partly loaded day is reported exactly.
    """
    if session is None:                                   # dry run: nothing to ask Snowflake
        return set()
    if (date.today() - date.fromisoformat(run_date)).days >= 14:
        print(f"Note: {run_date} is outside the 14-day COPY_HISTORY window, so 'already loaded' cannot be checked")
        return set()
    loaded = set()
    for csv_file_stem, table, kind, key in TABLES:
        if key is not None:                               # lookup tables are MERGEd: re-running them is harmless
            continue
        rows = session.sql(
            f"SELECT COUNT(*) FROM TABLE({db}.INFORMATION_SCHEMA.COPY_HISTORY("
            f"TABLE_NAME => '{db}.{schemas[kind]}.{table}', "
            f"START_TIME => DATEADD(day, -14, CURRENT_TIMESTAMP()))) "
            f"WHERE STATUS = 'Loaded' AND FILE_NAME LIKE '%{run_date}/{csv_file_stem}.csv'").collect()
        n = rows[0][0]
        print(f"  check> {table}: {n} 'Loaded' entr{'y' if n == 1 else 'ies'} in COPY_HISTORY for {csv_file_stem}.csv")
        if n > 0:
            loaded.add(csv_file_stem)
    return loaded


def main():
    # ---------------------------------------------------------------- 1. Command-line arguments
    # The date is declared optional (nargs="?") on purpose, so we can print our own explanation below
    # instead of argparse's short "arguments are required" error.
    parser = argparse.ArgumentParser(
        description="Load one day of generated Tasty Bytes CSV files into Snowflake with Snowpark.",
        epilog="example: %(prog)s 2026-11-08 ./data")
    parser.add_argument("run_date", nargs="?", help="MANDATORY. The day to load, as YYYY-MM-DD")
    parser.add_argument("data_dir", nargs="?", default="./data",
                        help="base directory the generator wrote to (default: ./data); files are read from DATA_DIR/<date>/")
    parser.add_argument("--force", action="store_true",
                        help="reload fact-table files even if Snowflake already loaded them (can create duplicates)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the SQL and PUT commands without connecting to Snowflake")
    args = parser.parse_args()

    # ---------------------------------------------------------------- 2. Validate the input
    # Mandatory date: explain what to provide and exit with code 2 (usage error).
    if args.run_date is None:
        parser.exit(2, ("ERROR: the date is mandatory.\n"
                        "Provide the day to load as the first argument, as YYYY-MM-DD. It selects the folder\n"
                        "DATA_DIR/<date>/ written by 1-generate_tasty_bytes_data.py.\n\n"
                        "Usage:   2-load_tasty_bytes_data.py YYYY-MM-DD [DATA_DIR] [--force] [--dry-run]\n"
                        f"Example: 2-load_tasty_bytes_data.py {date.today().isoformat()}\n"))
    # The date must be a real calendar date, not just text that looks like one.
    try:
        date.fromisoformat(args.run_date)
    except ValueError:
        parser.error(f"invalid date '{args.run_date}', expected YYYY-MM-DD")

    # Pre-flight check of the input files. 1-generate_tasty_bytes_data.py writes one folder per run date,
    # DATA_DIR/<date>/, holding one CSV per table (see TABLES). Before connecting to Snowflake, verify that
    # the folder exists and that every expected CSV is in it. If anything is missing, exit with an error that
    # names the missing folder or files and says how to generate them, so we never start a half-finished load
    # (e.g. some tables loaded and others not).
    src_dir = Path(args.data_dir) / args.run_date
    if not src_dir.is_dir():
        parser.exit(1, (f"ERROR: {src_dir.resolve()} does not exist.\n"
                        f"Generate it first: 1-generate_tasty_bytes_data.py {args.run_date} {args.data_dir}\n"))
    expected_csv_files = [t[0] + ".csv" for t in TABLES]
    missing_csv_files = [name for name in expected_csv_files if not (src_dir / name).is_file()]
    if missing_csv_files:
        parser.exit(1, f"ERROR: missing files in {src_dir.resolve()}: {', '.join(missing_csv_files)}\n")

    # ---------------------------------------------------------------- 3. Settings from .env / environment
    # Same .env as the performance-lab scripts (repo root, one level up from this folder). It is optional;
    # real environment variables work too. Values already in the environment win over the file.
    # Remember whether CONNECTION was already set in the real environment BEFORE .env is read, so we can
    # tell the user where the value came from (the script prints it below).
    connection_from_env = bool(os.environ.get("CONNECTION", "").strip())
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    # strip() so a value of only spaces counts as empty. A missing variable and an empty one are treated alike.
    connection = os.environ.get("CONNECTION", "").strip()
    # A dry run never connects, so it does not need a connection. A real load stops here, before touching
    # Snowflake, and explains how to fix it.
    if not connection and not args.dry_run:
        parser.exit(2, (
            "ERROR: the CONNECTION variable is not set (or is empty).\n"
            "It must be the NAME of a connection defined in ~/.snowflake/config.toml, e.g. [connections.default]\n"
            "-> name 'default'. Snowpark uses it to know which account, user and authentication to log in with.\n\n"
            "What to do:\n"
            "  1. List your connections:  snow connection list   (create one with: snow connection add)\n"
            "  2. Set the variable, either in the repo's .env file (snowflake-performance-lab/.env):\n"
            "         CONNECTION=default\n"
            "     or for a single run on the command line:\n"
            "         CONNECTION=default ./2-load_tasty_bytes_data.py " + args.run_date + "\n"
            "  (To only preview the SQL without connecting, use --dry-run.)\n"))
    if connection:
        # Show which connection will be used and where it came from. Note: the script reads the repo's .env
        # itself, so CONNECTION can be set there even when `echo $CONNECTION` in your shell prints nothing.
        source = "the environment" if connection_from_env else "the .env file"
        print(f"Using Snowflake connection '{connection}' (taken from {source})")

    # Where the data goes. Defaults follow the standard Tasty Bytes layout; override with TASTY_* variables.
    db = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schemas = {"pos": os.environ.get("TASTY_SCHEMA", "RAW_POS"),
               "customer": os.environ.get("TASTY_CUSTOMER_SCHEMA", "RAW_CUSTOMER")}
    # One internal stage holds the files of all days, each day in its own sub-folder: @stage/<date>/file.csv.
    stage = f"{db}.{schemas['pos']}.{os.environ.get('TASTY_STAGE', 'DAILY_LOAD')}"
    stage_dir = f"@{stage}/{args.run_date}"

    # ---------------------------------------------------------------- 4. Open the Snowpark session
    # session stays None in a dry run; the helpers below check for that and only print.
    session = None
    if not args.dry_run:
        # Imported here so --help and --dry-run work even without a configured Snowflake setup.
        from snowflake.snowpark import Session
        # "connection_name" makes Snowpark read that connection from ~/.snowflake/config.toml (account, user,
        # authentication, role, warehouse...). Nothing else is passed on purpose: the role and warehouse used are
        # exactly the ones defined in that connection, so ROLE/WAREHOUSE in .env are ignored here.
        session = Session.builder.configs({"connection_name": connection}).create()

    def run(sql):
        """Print one SQL statement on a single line and, unless this is a dry run, execute it."""
        print(f"  SQL> {' '.join(sql.split())}")
        if session is None:
            return []
        rows = session.sql(sql).collect()     # .collect() runs the statement and returns its result rows
        for row in rows:
            print(f"       {tuple(row)}")      # e.g. COPY INTO reports file, status, rows loaded, errors
        return rows

    try:
        # Skip the whole day (no PUT, no COPY) when the copy history says it was already loaded.
        loaded = set() if args.force else f_loaded_fact_files(session, db, schemas, args.run_date)
        fact_stems = {csv_file_stem for csv_file_stem, _, _, key in TABLES if key is None}
        if fact_stems and fact_stems <= loaded:
            print(f"Data for {args.run_date} has already been loaded into {db}: nothing to do (use --force to reload)")
            return
        if loaded:
            print(f"Already loaded, will be skipped: {', '.join(sorted(loaded))}")
        print(f"Loading {src_dir.resolve()} -> {db} (stage {stage}){'  [dry run]' if args.dry_run else ''}")

        # ------------------------------------------------------------ 5. Create the stage
        # The stage is the Snowflake-side folder the files are uploaded to before they are loaded.
        run(f"CREATE STAGE IF NOT EXISTS {stage}")
        print()

        # ------------------------------------------------------------ 6. Upload (PUT) the CSV files
        # Local files -> stage. AUTO_COMPRESS=FALSE keeps them as plain .csv, so the FILES = ('name.csv')
        # lists below match. OVERWRITE=TRUE replaces a file of the same name from an earlier run of this day.
        for csv_file_stem, *_ in TABLES:
            if csv_file_stem in loaded:
                continue
            path = src_dir / f"{csv_file_stem}.csv"
            print(f"PUT {path.name}")
            if session is None:
                print(f"  PUT file://{path.resolve()} {stage_dir}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
            else:
                for r in session.file.put(str(path.resolve()), stage_dir, auto_compress=False, overwrite=True):
                    print(f"       {r.source} -> {r.status}")
            print()

        # ------------------------------------------------------------ 7. Load every table
        for csv_file_stem, table, kind, key in TABLES:
            if csv_file_stem in loaded:
                print(f"SKIP {csv_file_stem}.csv: already loaded\n")
                continue
            target = f"{db}.{schemas[kind]}.{table}"
            print(f"LOAD {csv_file_stem}.csv -> {target}" + (" (merge)" if key else ""))
            # MATCH_BY_COLUMN_NAME maps CSV columns to table columns by header name (not by position), so the
            # table may have extra columns or a different column order. Matching ignores upper/lower case.
            copy_opts = f"FILE_FORMAT = {FILE_FORMAT} MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE"

            # 7a. Fact table (no merge key): new rows every day, so load straight into the table.
            #     Snowflake remembers which staged files it already loaded and skips them, which makes a
            #     re-run of the same day safe. --force loads them again anyway (this can create duplicates).
            if key is None:
                run(f"COPY INTO {target} FROM {stage_dir}/ FILES = ('{csv_file_stem}.csv') {copy_opts}"
                    + (" FORCE = TRUE" if args.force else ""))
                print()
                continue

            # 7b. Lookup table (has a merge key): the same rows come back every day with regenerated values,
            #     so a plain COPY would duplicate them. Instead:
            #       1) create an empty temporary copy of the table (same columns and types, dropped when the
            #          session ends),
            #       2) COPY the file into that temporary table,
            #       3) MERGE: rows whose key already exists are updated, new keys are inserted.
            cols = csv_header(src_dir / f"{csv_file_stem}.csv")                          # column names from the CSV header
            stg = f"{db}.{schemas[kind]}.STG_{table}"                            # fully qualified: the session may have no default schema
            on = " AND ".join(f"t.{k} = s.{k}" for k in key)                     # join condition on the key column(s)
            sets = ", ".join(f"t.{c} = s.{c}" for c in cols if c not in key)    # update every non-key column
            run(f"CREATE OR REPLACE TEMPORARY TABLE {stg} LIKE {target}")
            run(f"COPY INTO {stg} FROM {stage_dir}/ FILES = ('{csv_file_stem}.csv') {copy_opts}")
            run(f"MERGE INTO {target} t USING {stg} s ON {on} "
                f"WHEN MATCHED THEN UPDATE SET {sets} "
                f"WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)})")
            print()
        print("Done.")
    finally:
        # ---------------------------------------------------------------- 8. Always close the session
        # Closing it also drops the temporary STG_* tables, even if a statement above failed.
        if session is not None:
            session.close()


if __name__ == "__main__":
    sys.exit(main())
