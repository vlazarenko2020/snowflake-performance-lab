#!/usr/bin/env python3
"""Generate the daily COUNTRY rows (one row per city) -> OUTPUT_DIR/<date>/country.csv

This script is fully standalone: it does not import any other script of this project.

Usage:
    ./1-1-generate-COUNTRY_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--rows N] [--no-snowflake]
    e.g. ./1-1-generate-COUNTRY_table_rows.py 2026-11-08 ./data

    YYYY-MM-DD      mandatory, the day to generate data for
    OUTPUT_DIR      optional, base folder for the CSV files (default ./data)
    ORDERS          optional, accepted only so all 1-1-generate-* scripts take the same parameters.
                    It is not used here, because the COUNTRY table has no orders.
    --rows N        optional, how many rows to generate instead of the default (N_CITIES in this file);
                    0 writes the CSV with only the header line, so the loader still finds the file
    --no-snowflake  do not ask Snowflake for the current highest ID, number the rows from 1
                    (offline testing only: these IDs will clash with rows that are already loaded)

IDs: the new rows get IDs that are bigger than the current highest COUNTRY_ID and CITY_ID in Snowflake,
so they never collide with rows that are already loaded. Snowflake is reached through the CONNECTION
variable (from the environment or from the .env file in the repo root), the same one the loader uses.
"""
import argparse
import csv
import os
import random
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = "./data"
DEFAULT_ORDERS = 500          # not used by this script, only here to document the shared parameter

# How many cities (= COUNTRY rows) are generated per day. Only a few rows: this is a small lookup table.
N_CITIES = 3

# Name of the file this script writes, and its column names (in the order they appear in the file).
CSV_FILE_NAME = "country.csv"
CSV_COLUMNS = [
    "COUNTRY_ID",
    "COUNTRY",
    "ISO_CURRENCY",
    "ISO_COUNTRY",
    "CITY_ID",
    "CITY",
    "CITY_POPULATION",
]

# The next four lists are parallel: position 0 in each list describes the same city, position 1 the next one, etc.
# Only the first N_CITIES entries are used.
CITIES = ["Seattle", "Boston", "Denver", "Toronto", "Vancouver", "London", "Paris", "Berlin",
          "Madrid", "Tokyo", "Sydney", "Mumbai", "Sao Paulo", "Seoul", "Cairo"]
COUNTRIES = ["United States", "United States", "United States", "Canada", "Canada", "England", "France",
             "Germany", "Spain", "Japan", "Australia", "India", "Brazil", "South Korea", "Egypt"]
ISO_CODES = ["US", "US", "US", "CA", "CA", "GB", "FR", "DE", "ES", "JP", "AU", "IN", "BR", "KR", "EG"]
CURRENCIES = ["USD", "USD", "USD", "CAD", "CAD", "GBP", "EUR", "EUR", "EUR", "JPY", "AUD", "INR", "BRL", "KRW", "EGP"]

# The 1970-01-01 date is "day 0". The number of days since then is used to seed the random generator.
EPOCH = date(1970, 1, 1)


# ---------------------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------------------

def f_read_command_line():
    """Read the parameters given on the command line and return them (a Namespace object)."""
    parser = argparse.ArgumentParser(
        description="Generate the daily COUNTRY rows as a CSV file.",
        epilog="example: %(prog)s 2026-11-08 ./data   ->   ./data/2026-11-08/country.csv")

    # nargs="?" makes a positional parameter optional. We check the date ourselves later,
    # to be able to print a clearer message than the default one.
    parser.add_argument("run_date", nargs="?",
                        help="MANDATORY. The day to generate data for, as YYYY-MM-DD")
    parser.add_argument("output_dir", nargs="?",
                        help="base output directory (default: " + DEFAULT_OUTPUT_DIR + ")")
    parser.add_argument("orders", nargs="?", type=int,
                        help="not used by this script, accepted so all 1-1-generate-* scripts take the same parameters")
    parser.add_argument("--no-snowflake", action="store_true",
                        help="do not read the highest IDs from Snowflake: number the rows from 1 (offline testing only)")

    parser.add_argument("--rows", type=int,
                        help="how many rows to generate instead of the default (0 = only the header line)")

    return parser.parse_args(), parser


def f_get_highest_ids():
    """Ask Snowflake for the highest COUNTRY_ID and CITY_ID that exist today. Return them as a dictionary.

    An empty table gives 0, so the first new row will get ID 1.
    """
    # snowflake and dotenv are not part of the Python standard library. They are imported here, inside the
    # function, so that --help and --no-snowflake keep working on a machine that does not have them installed.
    try:
        from dotenv import load_dotenv
        from snowflake.snowpark import Session
    except ImportError:
        sys.exit("ERROR: snowflake-snowpark-python and python-dotenv are needed to read the highest IDs from Snowflake.\n"
                 "Run the script with 'uv run' (see README), or use --no-snowflake to number the rows from 1.")

    # Remember whether CONNECTION was already set before .env is read, only to tell the user where it came from.
    connection_was_in_environment = False
    if os.environ.get("CONNECTION", "").strip() != "":
        connection_was_in_environment = True

    # The .env file is in the repo root, one folder above the folder this script is in.
    # Values that are already set in the real environment win over the ones in the file.
    env_file = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_file)

    connection = os.environ.get("CONNECTION", "").strip()
    if connection == "":
        sys.exit("ERROR: the CONNECTION variable is not set (or is empty), so the highest IDs cannot be read from Snowflake.\n"
                 "Set it in the repo's .env (CONNECTION=<name from ~/.snowflake/config.toml>), or use --no-snowflake.")

    if connection_was_in_environment:
        source = "the environment"
    else:
        source = "the .env file"
    print("Reading the highest IDs with Snowflake connection '" + connection + "' (taken from " + source + ")")

    # Database and schema can be overridden with the same TASTY_* settings the loader uses.
    database = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schema = os.environ.get("TASTY_SCHEMA", "RAW_POS")

    # COALESCE(MAX(...), 0) turns "no rows yet" (NULL) into 0.
    id_columns = ["COUNTRY_ID", "CITY_ID"]

    highest_ids = {}
    session = Session.builder.configs({"connection_name": connection}).create()
    try:
        for column in id_columns:
            sql = "SELECT COALESCE(MAX(" + column + "), 0) FROM " + database + "." + schema + ".COUNTRY"
            rows = session.sql(sql).collect()
            highest_ids[column] = rows[0][0]
            print("  MAX(COUNTRY." + column + ") = " + str(highest_ids[column]))
    finally:
        # Always close the connection, even if one of the queries failed.
        session.close()

    return highest_ids


def f_file_already_generated(csv_path):
    """Return True if the CSV file exists and is not empty, which means this day was already generated."""
    if not csv_path.is_file():
        return False
    if csv_path.stat().st_size == 0:
        return False
    return True


# ---------------------------------------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------------------------------------

def main():
    args, parser = f_read_command_line()

    # ---- 1. Check the parameters -------------------------------------------------------------------------
    if args.run_date is None:
        parser.exit(2, "ERROR: the date is mandatory.\n"
                       "Provide the day to generate data for as the first argument, in the format YYYY-MM-DD.\n"
                       "It decides the folder name and the random seed.\n\n"
                       "Usage:   1-1-generate-COUNTRY_table_rows.py YYYY-MM-DD [OUTPUT_DIR]\n"
                       "Example: 1-1-generate-COUNTRY_table_rows.py " + date.today().isoformat() + "\n")

    # The date must be a real calendar date, not just text that looks like one (2026-02-31 is rejected).
    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error("invalid date '" + args.run_date + "', expected YYYY-MM-DD")

    if args.orders is not None and args.orders < 1:
        parser.error("orders must be a positive integer")

    # How many rows to generate: --rows if it was given, otherwise the default of this script.
    if args.rows is None:
        number_of_rows = N_CITIES
    else:
        number_of_rows = args.rows
    if number_of_rows < 0:
        parser.error("--rows must be 0 or a positive integer")
    if number_of_rows > len(CITIES):
        parser.error("--rows can be at most " + str(len(CITIES)) + " for COUNTRY")

    if args.output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    else:
        output_dir = args.output_dir

    # ---- 2. Decide where the file goes, and stop if it is already there -----------------------------------
    # Every day gets its own folder: OUTPUT_DIR/<date>/
    day_folder = Path(output_dir) / args.run_date
    csv_path = day_folder / CSV_FILE_NAME

    if f_file_already_generated(csv_path):
        print("COUNTRY rows for " + args.run_date + " have already been generated in " + str(csv_path.resolve())
              + ": nothing to do")
        return

    if args.output_dir is None:
        print("OUTPUT_DIR not provided: the file will be created in the folder " + str(day_folder.resolve()))

    # parents=True creates missing parent folders too, exist_ok=True is not an error if the folder is already there.
    day_folder.mkdir(parents=True, exist_ok=True)

    # ---- 3. Find out where the numbering of the new rows has to start -------------------------------------
    # The new rows are numbered highest ID + 1, + 2, + 3 ...
    if number_of_rows == 0:
        highest_ids = {"COUNTRY_ID": 0, "CITY_ID": 0}
    elif args.no_snowflake:
        highest_ids = {"COUNTRY_ID": 0, "CITY_ID": 0}
        print("--no-snowflake: IDs start from 1 (they may clash with data already in Snowflake)")
    else:
        highest_ids = f_get_highest_ids()

    # ---- 4. Prepare the random generator ------------------------------------------------------------------
    # Seeded with the day number and the table name: the same date always gives the same random values,
    # and this script does not depend on how many random values any other script uses.
    days_since_epoch = (run_date - EPOCH).days
    rng = random.Random(str(days_since_epoch) + ":COUNTRY")

    # ---- 5. Write the CSV file ----------------------------------------------------------------------------
    # newline="" and lineterminator="\n" make the file use plain Unix line endings on every operating system.
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")

        # First line of the file: the column names.
        writer.writerow(CSV_COLUMNS)

        # One row per city. "position" goes 0, 1, 2 ... N_CITIES - 1 and picks the same place in every list.
        for position in range(number_of_rows):
            country_id = highest_ids["COUNTRY_ID"] + position + 1
            city_id = highest_ids["CITY_ID"] + position + 1

            # Made-up population, between 500 thousand and 12 million.
            city_population = rng.randint(500000, 12000000)

            writer.writerow([
                country_id,
                COUNTRIES[position],
                CURRENCIES[position],
                ISO_CODES[position],
                city_id,
                CITIES[position],
                city_population,
            ])

    # ---- 6. Tell the user what was done -------------------------------------------------------------------
    print("Generated " + str(csv_path) + ": " + str(number_of_rows) + " rows")


if __name__ == "__main__":
    main()
