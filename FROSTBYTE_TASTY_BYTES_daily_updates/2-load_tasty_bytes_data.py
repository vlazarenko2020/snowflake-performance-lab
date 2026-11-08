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

    # The generator writes DATA_DIR/<date>/*.csv; stop early with a hint if that folder or any file is missing,
    # so we never start a half-finished load.
    src_dir = Path(args.data_dir) / args.run_date
    if not src_dir.is_dir():
        parser.exit(1, (f"ERROR: {src_dir.resolve()} does not exist.\n"
                        f"Generate it first: 1-generate_tasty_bytes_data.py {args.run_date} {args.data_dir}\n"))
    missing = [stem + ".csv" for stem, *_ in TABLES if not (src_dir / (stem + ".csv")).is_file()]
    if missing:
        parser.exit(1, f"ERROR: missing files in {src_dir.resolve()}: {', '.join(missing)}\n")

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
        print(f"Loading {src_dir.resolve()} -> {db} (stage {stage}){'  [dry run]' if args.dry_run else ''}")

        # ------------------------------------------------------------ 5. Create the stage
        # The stage is the Snowflake-side folder the files are uploaded to before they are loaded.
        run(f"CREATE STAGE IF NOT EXISTS {stage}")

        # ------------------------------------------------------------ 6. Upload (PUT) the CSV files
        # Local files -> stage. AUTO_COMPRESS=FALSE keeps them as plain .csv, so the FILES = ('name.csv')
        # lists below match. OVERWRITE=TRUE replaces a file of the same name from an earlier run of this day.
        for stem, *_ in TABLES:
            path = src_dir / f"{stem}.csv"
            print(f"PUT {path.name}")
            if session is None:
                print(f"  PUT file://{path.resolve()} {stage_dir}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
            else:
                for r in session.file.put(str(path.resolve()), stage_dir, auto_compress=False, overwrite=True):
                    print(f"       {r.source} -> {r.status}")

        # ------------------------------------------------------------ 7. Load every table
        for stem, table, kind, key in TABLES:
            target = f"{db}.{schemas[kind]}.{table}"
            print(f"LOAD {stem}.csv -> {target}" + (" (merge)" if key else ""))
            # MATCH_BY_COLUMN_NAME maps CSV columns to table columns by header name (not by position), so the
            # table may have extra columns or a different column order. Matching ignores upper/lower case.
            copy_opts = f"FILE_FORMAT = {FILE_FORMAT} MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE"

            # 7a. Fact table (no merge key): new rows every day, so load straight into the table.
            #     Snowflake remembers which staged files it already loaded and skips them, which makes a
            #     re-run of the same day safe. --force loads them again anyway (this can create duplicates).
            if key is None:
                run(f"COPY INTO {target} FROM {stage_dir}/ FILES = ('{stem}.csv') {copy_opts}"
                    + (" FORCE = TRUE" if args.force else ""))
                continue

            # 7b. Lookup table (has a merge key): the same rows come back every day with regenerated values,
            #     so a plain COPY would duplicate them. Instead:
            #       1) create an empty temporary copy of the table (same columns and types, dropped when the
            #          session ends),
            #       2) COPY the file into that temporary table,
            #       3) MERGE: rows whose key already exists are updated, new keys are inserted.
            cols = csv_header(src_dir / f"{stem}.csv")                          # column names from the CSV header
            stg = f"{db}.{schemas[kind]}.STG_{table}"                            # fully qualified: the session may have no default schema
            on = " AND ".join(f"t.{k} = s.{k}" for k in key)                     # join condition on the key column(s)
            sets = ", ".join(f"t.{c} = s.{c}" for c in cols if c not in key)    # update every non-key column
            run(f"CREATE OR REPLACE TEMPORARY TABLE {stg} LIKE {target}")
            run(f"COPY INTO {stg} FROM {stage_dir}/ FILES = ('{stem}.csv') {copy_opts}")
            run(f"MERGE INTO {target} t USING {stg} s ON {on} "
                f"WHEN MATCHED THEN UPDATE SET {sets} "
                f"WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)})")
        print("Done.")
    finally:
        # ---------------------------------------------------------------- 8. Always close the session
        # Closing it also drops the temporary STG_* tables, even if a statement above failed.
        if session is not None:
            session.close()


if __name__ == "__main__":
    sys.exit(main())
