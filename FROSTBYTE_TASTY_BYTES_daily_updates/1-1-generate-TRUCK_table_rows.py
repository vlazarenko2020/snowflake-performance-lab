#!/usr/bin/env python3
"""Generate the daily TRUCK rows -> OUTPUT_DIR/<date>/truck.csv

This script is fully standalone: it does not import any other script of this project.

Every truck belongs to a franchise: one of the franchises in franchise.csv of the same day (run
1-1-generate-FRANCHISE_table_rows.py first) or, unless --no-snowflake is used, one already in Snowflake.

Usage:
    ./1-1-generate-TRUCK_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--rows N] [--no-snowflake]
    e.g. ./1-1-generate-TRUCK_table_rows.py 2026-11-08 ./data

    YYYY-MM-DD      mandatory, the day to generate data for
    OUTPUT_DIR      optional, base folder for the CSV files (default ./data)
    ORDERS          optional, accepted only so all 1-1-generate-* scripts take the same parameters.
                    It is not used here, because the TRUCK table has no orders.
    --rows N        optional, how many rows to generate instead of the default (N_TRUCKS in this file);
                    0 writes the CSV with only the header line, so the loader still finds the file
    --no-snowflake  do not ask Snowflake for the current highest ID, number the rows from 1
                    (offline testing only: these IDs will clash with rows that are already loaded)

IDs: the new rows get IDs that are bigger than the current highest TRUCK_ID in Snowflake, so they never
collide with rows that are already loaded. Snowflake is reached through the CONNECTION variable (from the
environment or from the .env file in the repo root), the same one the loader uses.
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

# How many trucks are generated per day.
N_TRUCKS = 4

# A truck is based in one of the first N_CITIES cities of the lists below.
N_CITIES = 3

# Name of the file this script writes, the file it reads, and the column names of the file it writes.
CSV_FILE_NAME = "truck.csv"
FRANCHISE_CSV_FILE_NAME = "franchise.csv"
CSV_COLUMNS = [
    "TRUCK_ID",
    "FRANCHISE_ID",
    "PRIMARY_CITY",
    "REGION",
    "ISO_REGION",
    "COUNTRY",
    "ISO_COUNTRY_CODE",
    "FRANCHISE_FLAG",
    "YEAR",
    "MAKE",
    "MODEL",
    "EV_FLAG",
    "TRUCK_OPENING_DATE",
    "TRUCK_START_DATE",
]

# The next three lists are parallel: position 0 in each list describes the same city, position 1 the next one, etc.
CITIES = ["Seattle", "Boston", "Denver", "Toronto", "Vancouver", "London", "Paris", "Berlin",
          "Madrid", "Tokyo", "Sydney", "Mumbai", "Sao Paulo", "Seoul", "Cairo"]
COUNTRIES = ["United States", "United States", "United States", "Canada", "Canada", "England", "France",
             "Germany", "Spain", "Japan", "Australia", "India", "Brazil", "South Korea", "Egypt"]
ISO_CODES = ["US", "US", "US", "CA", "CA", "GB", "FR", "DE", "ES", "JP", "AU", "IN", "BR", "KR", "EG"]

# These two lists are parallel as well: model number 0 is a "Ford Step Van", number 1 a "Freightliner Box Truck", etc.
MAKES = ["Ford", "Freightliner", "Chevrolet", "Nissan", "Isuzu"]
MODELS = ["Step Van", "Box Truck", "NV200", "NPR", "Utilimaster"]

# The 1970-01-01 date is "day 0". The number of days since then is used to seed the random generator.
EPOCH = date(1970, 1, 1)


# ---------------------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------------------

def f_read_command_line():
    """Read the parameters given on the command line and return them (a Namespace object) and the parser."""
    parser = argparse.ArgumentParser(
        description="Generate the daily TRUCK rows as a CSV file.",
        epilog="example: %(prog)s 2026-11-08 ./data   ->   ./data/2026-11-08/truck.csv")

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


def f_open_session():
    """Open and return a Snowpark session for the Snowflake connection named in CONNECTION."""
    # snowflake and dotenv are not part of the Python standard library. They are imported here, inside the
    # function, so that --help and --no-snowflake keep working on a machine that does not have them installed.
    try:
        from dotenv import load_dotenv
        from snowflake.snowpark import Session
    except ImportError:
        sys.exit("ERROR: snowflake-snowpark-python and python-dotenv are needed to read from Snowflake.\n"
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
        sys.exit("ERROR: the CONNECTION variable is not set (or is empty), so Snowflake cannot be used.\n"
                 "Set it in the repo's .env (CONNECTION=<name from ~/.snowflake/config.toml>), or use --no-snowflake.")

    if connection_was_in_environment:
        source = "the environment"
    else:
        source = "the .env file"
    print("Using Snowflake connection '" + connection + "' (taken from " + source + ")")

    return Session.builder.configs({"connection_name": connection}).create()


def f_get_highest_ids():
    """Ask Snowflake for the highest TRUCK_ID that exists today. Return it in a dictionary.

    An empty table gives 0, so the first new row will get ID 1.
    """
    # Database and schema can be overridden with the same TASTY_* settings the loader uses.
    database = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schema = os.environ.get("TASTY_SCHEMA", "RAW_POS")

    highest_ids = {}
    session = f_open_session()
    try:
        # COALESCE(MAX(...), 0) turns "no rows yet" (NULL) into 0.
        sql = "SELECT COALESCE(MAX(TRUCK_ID), 0) FROM " + database + "." + schema + ".TRUCK"
        rows = session.sql(sql).collect()
        highest_ids["TRUCK_ID"] = rows[0][0]
        print("  MAX(TRUCK.TRUCK_ID) = " + str(highest_ids["TRUCK_ID"]))
    finally:
        # Always close the connection, even if the query failed.
        session.close()

    return highest_ids


def f_file_already_generated(csv_path):
    """Return True if the CSV file exists and is not empty, which means this day was already generated."""
    if not csv_path.is_file():
        return False
    if csv_path.stat().st_size == 0:
        return False
    return True


def f_read_franchise_ids(franchise_csv_path, run_date_text, output_dir, use_snowflake):
    """Return the list of FRANCHISE_IDs a new truck can belong to.

    Two sources are used:
      1. franchise.csv of the same day (franchises created today), if the file exists;
      2. the FRANCHISE table in Snowflake (franchises from earlier days), unless --no-snowflake was given.
    Stops with a hint if no franchise is found at all.
    """
    franchise_ids = []

    # Source 1: today's franchise file. It is normal that it has no rows (most days no franchise is added).
    if franchise_csv_path.is_file():
        with open(franchise_csv_path, newline="", encoding="utf-8") as csv_file:
            # DictReader gives every row as a dictionary: column name -> value.
            reader = csv.DictReader(csv_file)
            for row in reader:
                franchise_ids.append(int(row["FRANCHISE_ID"]))

    # Source 2: franchises that are already in Snowflake. SAMPLE takes a random part of a big table.
    if use_snowflake:
        database = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
        schema = os.environ.get("TASTY_SCHEMA", "RAW_POS")
        session = f_open_session()
        try:
            sql = "SELECT FRANCHISE_ID FROM " + database + "." + schema + ".FRANCHISE SAMPLE (1000 ROWS)"
            for row in session.sql(sql).collect():
                franchise_id = int(row[0])
                if franchise_id not in franchise_ids:
                    franchise_ids.append(franchise_id)
        finally:
            session.close()

    if len(franchise_ids) == 0:
        sys.exit("ERROR: no franchise found for the trucks (" + str(franchise_csv_path.resolve()) + " has no rows"
                 " and none were read from Snowflake).\n"
                 "Generate some first: 1-1-generate-FRANCHISE_table_rows.py " + run_date_text + " " + output_dir
                 + " --rows 1")

    return franchise_ids


def f_random_date(rng, first_year, last_year):
    """Return a made-up date like 2019-07-23. The day is never above 28, so it is valid in every month."""
    year = rng.randint(first_year, last_year)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    # %02d means "a number padded with leading zeros to 2 digits".
    return "%d-%02d-%02d" % (year, month, day)


def f_random_flag(rng, probability):
    """Return 1 with the given probability (0.3 = 30 percent of the calls), otherwise 0."""
    if rng.random() < probability:
        return 1
    return 0


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
                       "Usage:   1-1-generate-TRUCK_table_rows.py YYYY-MM-DD [OUTPUT_DIR]\n"
                       "Example: 1-1-generate-TRUCK_table_rows.py " + date.today().isoformat() + "\n")

    # The date must be a real calendar date, not just text that looks like one (2026-02-31 is rejected).
    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error("invalid date '" + args.run_date + "', expected YYYY-MM-DD")

    if args.orders is not None and args.orders < 1:
        parser.error("orders must be a positive integer")

    # How many rows to generate: --rows if it was given, otherwise the default of this script.
    if args.rows is None:
        number_of_rows = N_TRUCKS
    else:
        number_of_rows = args.rows
    if number_of_rows < 0:
        parser.error("--rows must be 0 or a positive integer")

    if args.output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    else:
        output_dir = args.output_dir

    # ---- 2. Decide where the file goes, and stop if it is already there -----------------------------------
    # Every day gets its own folder: OUTPUT_DIR/<date>/
    day_folder = Path(output_dir) / args.run_date
    csv_path = day_folder / CSV_FILE_NAME

    if f_file_already_generated(csv_path):
        print("TRUCK rows for " + args.run_date + " have already been generated in " + str(csv_path.resolve())
              + ": nothing to do")
        return

    # ---- 3. Read the franchises the trucks will belong to -------------------------------------------------
    # Done before anything is created, so a missing franchise stops the script early.
    # Not needed when no truck is generated.
    franchise_ids = []
    if number_of_rows > 0:
        use_snowflake = not args.no_snowflake
        franchise_ids = f_read_franchise_ids(day_folder / FRANCHISE_CSV_FILE_NAME, args.run_date, output_dir,
                                             use_snowflake)

    if args.output_dir is None:
        print("OUTPUT_DIR not provided: the file will be created in the folder " + str(day_folder.resolve()))

    # parents=True creates missing parent folders too, exist_ok=True is not an error if the folder is already there.
    day_folder.mkdir(parents=True, exist_ok=True)

    # ---- 4. Find out where the numbering of the new rows has to start -------------------------------------
    # The new rows are numbered highest ID + 1, + 2, + 3 ...
    if number_of_rows == 0:
        highest_ids = {"TRUCK_ID": 0}
    elif args.no_snowflake:
        highest_ids = {"TRUCK_ID": 0}
        print("--no-snowflake: IDs start from 1 (they may clash with data already in Snowflake)")
    else:
        highest_ids = f_get_highest_ids()

    # ---- 5. Prepare the random generator ------------------------------------------------------------------
    # Seeded with the day number and the table name: the same date always gives the same random values,
    # and this script does not depend on how many random values any other script uses.
    days_since_epoch = (run_date - EPOCH).days
    rng = random.Random(str(days_since_epoch) + ":TRUCK")

    # ---- 6. Write the CSV file ----------------------------------------------------------------------------
    # newline="" and lineterminator="\n" make the file use plain Unix line endings on every operating system.
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")

        # First line of the file: the column names.
        writer.writerow(CSV_COLUMNS)

        # One row per truck. "number" goes 1, 2, 3 ... N_TRUCKS.
        for number in range(1, number_of_rows + 1):
            truck_id = highest_ids["TRUCK_ID"] + number

            # Pick one of the first N_CITIES cities; the country and ISO code come from the same position.
            city_position = rng.randint(0, N_CITIES - 1)

            # Pick a make and model (they are paired: the same position in both lists).
            model_position = rng.randint(0, len(MAKES) - 1)

            # The truck belongs to one of the franchises read from franchise.csv.
            franchise_id = rng.choice(franchise_ids)

            # About 30 percent of the trucks are franchise trucks, about 20 percent are electric.
            franchise_flag = f_random_flag(rng, 0.3)
            year = rng.randint(2005, 2025)
            ev_flag = f_random_flag(rng, 0.2)

            # NOTE: this value is only a year (not a full date). It was like that in the old generator
            # script and is kept as it was.
            truck_opening_date = rng.randint(2015, 2025)
            truck_start_date = f_random_date(rng, 2015, 2025)

            writer.writerow([
                truck_id,
                franchise_id,
                CITIES[city_position],          # PRIMARY_CITY
                CITIES[city_position],          # REGION (same as the city, to keep the data simple)
                ISO_CODES[city_position],       # ISO_REGION
                COUNTRIES[city_position],
                ISO_CODES[city_position],       # ISO_COUNTRY_CODE
                franchise_flag,
                year,
                MAKES[model_position],
                MODELS[model_position],
                ev_flag,
                truck_opening_date,
                truck_start_date,
            ])

    # ---- 7. Tell the user what was done -------------------------------------------------------------------
    print("Generated " + str(csv_path) + ": " + str(number_of_rows) + " rows")


if __name__ == "__main__":
    main()
