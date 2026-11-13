#!/usr/bin/env python3
"""Generate the daily CUSTOMER_LOYALTY rows (new sign-ups for the day) -> OUTPUT_DIR/<date>/customer_loyalty.csv

This script is fully standalone: it does not import any other script of this project.

Usage:
    ./1-1-generate-CUSTOMER_LOYALTY_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--rows N] [--no-snowflake]
    e.g. ./1-1-generate-CUSTOMER_LOYALTY_table_rows.py 2026-11-08 ./data

    YYYY-MM-DD      mandatory, the day to generate data for
    OUTPUT_DIR      optional, base folder for the CSV files (default ./data)
    ORDERS          optional, accepted only so all 1-1-generate-* scripts take the same parameters.
                    It is not used here, because the CUSTOMER_LOYALTY table has no orders.
    --rows N        optional, how many rows to generate instead of the default (N_CUSTOMERS in this file);
                    0 writes the CSV with only the header line, so the loader still finds the file
    --no-snowflake  do not ask Snowflake for the current highest ID, number the rows from 1
                    (offline testing only: these IDs will clash with rows that are already loaded)

IDs: the new rows get IDs that are bigger than the current highest CUSTOMER_ID in Snowflake, so they never
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

# How many new loyalty customers sign up per day.
N_CUSTOMERS = 5

# A customer lives in one of the first N_CITIES cities of the lists below.
N_CITIES = 3

# Name of the file this script writes, and its column names (in the order they appear in the file).
CSV_FILE_NAME = "customer_loyalty.csv"
CSV_COLUMNS = [
    "CUSTOMER_ID",
    "FIRST_NAME",
    "LAST_NAME",
    "CITY",
    "COUNTRY",
    "POSTAL_CODE",
    "PREFERRED_LANGUAGE",
    "GENDER",
    "FAVOURITE_BRAND",
    "MARITAL_STATUS",
    "CHILDREN_COUNT",
    "SIGN_UP_DATE",
    "BIRTHDAY",
    "E_MAIL",
    "PHONE_NUMBER",
]

# Lists the random values are picked from. Names must stay plain ASCII, because they go into e-mail addresses.
FIRST_NAMES = ["Ava", "Liam", "Noah", "Emma", "Olivia", "Mia", "Lucas", "Sofia", "Ethan", "Chloe", "Mateo", "Yuki",
               "Amir", "Lena", "Raj", "Isabella", "Oliver", "Amelia", "Elijah", "Harper", "Henry", "Evelyn", "Jack",
               "Grace", "Leo", "Nora", "Daniel", "Zoe", "Samuel", "Layla", "Hugo", "Freya", "Mohamed", "Aisha",
               "Chen", "Mei", "Hiroshi", "Akira", "Priya", "Arjun", "Ananya", "Diego", "Valentina", "Santiago",
               "Camila", "Anders", "Ingrid", "Sven", "Katarina", "Dmitri", "Natasha", "Pavel", "Olga", "Luca",
               "Giulia", "Marco", "Elena", "Kofi", "Amara", "Tunde", "Zara", "Omar", "Fatima", "Yusuf", "Leila",
               "Jin", "Soo", "Min", "Hana", "Tomas", "Petra", "Felix", "Clara", "Andre", "Beatriz"]
LAST_NAMES = ["Smith", "Garcia", "Muller", "Rossi", "Tanaka", "Kim", "Novak", "Silva", "Dubois", "Patel", "Brown",
              "Jensen", "Lopez", "Cohen", "Ali", "Johnson", "Williams", "Jones", "Davis", "Miller", "Wilson", "Moore",
              "Taylor", "Anderson", "Thomas", "Martin", "Lee", "Walker", "Hall", "Fernandez", "Martinez", "Gonzalez",
              "Rodriguez", "Hernandez", "Perez", "Sanchez", "Ramirez", "Torres", "Flores", "Costa", "Pereira",
              "Santos", "Schmidt", "Schneider", "Fischer", "Weber", "Wagner", "Becker", "Hoffmann", "Bianchi",
              "Ferrari", "Romano", "Moreau", "Laurent", "Bernard", "Ivanov", "Petrov", "Kowalski", "Nowak",
              "Nielsen", "Hansen", "Larsen", "Johansson", "Lindberg", "Sato", "Suzuki", "Watanabe", "Wang", "Zhang",
              "Liu", "Nguyen", "Tran", "Singh", "Sharma", "Gupta", "Khan", "Hassan", "Ahmed", "Okafor", "Mensah",
              "Adeyemi", "Murphy", "Walsh"]

# These two lists are parallel: position 0 in each list describes the same city, position 1 the next one, etc.
CITIES = ["Seattle", "Boston", "Denver", "Toronto", "Vancouver", "London", "Paris", "Berlin",
          "Madrid", "Tokyo", "Sydney", "Mumbai", "Sao Paulo", "Seoul", "Cairo"]
COUNTRIES = ["United States", "United States", "United States", "Canada", "Canada", "England", "France",
             "Germany", "Spain", "Japan", "Australia", "India", "Brazil", "South Korea", "Egypt"]

LANGUAGES = ["English", "French", "German", "Spanish", "Japanese"]
GENDERS = ["Male", "Female", "Undisclosed"]
MARITAL_STATUSES = ["Single", "Married", "Divorced", "Undisclosed"]
BRANDS = ["Kitakata Ramen Bar", "Freezing Point", "Smoky BBQ", "Guac n Roll", "The Mega Melt", "Tasty Tibs",
          "Le Coin des Crepes", "Better Off Bread", "Plant Palace", "Revenge of the Curds", "Cheeky Greek",
          "Peking Truck", "Nani's Kitchen", "The Mac Shack", "Not the Wurst Hot Dogs"]

# The 1970-01-01 date is "day 0". The number of days since then is used to seed the random generator.
EPOCH = date(1970, 1, 1)


# ---------------------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------------------

def f_read_command_line():
    """Read the parameters given on the command line and return them (a Namespace object) and the parser."""
    parser = argparse.ArgumentParser(
        description="Generate the daily CUSTOMER_LOYALTY rows as a CSV file.",
        epilog="example: %(prog)s 2026-11-08 ./data   ->   ./data/2026-11-08/customer_loyalty.csv")

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
    """Ask Snowflake for the highest CUSTOMER_ID that exists today. Return it in a dictionary.

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
    # CUSTOMER_LOYALTY lives in its own schema, not in the one the other tables use.
    database = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schema = os.environ.get("TASTY_CUSTOMER_SCHEMA", "RAW_CUSTOMER")

    highest_ids = {}
    session = Session.builder.configs({"connection_name": connection}).create()
    try:
        # COALESCE(MAX(...), 0) turns "no rows yet" (NULL) into 0.
        sql = "SELECT COALESCE(MAX(CUSTOMER_ID), 0) FROM " + database + "." + schema + ".CUSTOMER_LOYALTY"
        rows = session.sql(sql).collect()
        highest_ids["CUSTOMER_ID"] = rows[0][0]
        print("  MAX(CUSTOMER_LOYALTY.CUSTOMER_ID) = " + str(highest_ids["CUSTOMER_ID"]))
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


def f_random_date(rng, first_year, last_year):
    """Return a made-up date like 1984-07-23. The day is never above 28, so it is valid in every month."""
    year = rng.randint(first_year, last_year)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    # %02d means "a number padded with leading zeros to 2 digits".
    return "%d-%02d-%02d" % (year, month, day)


def f_random_phone(rng):
    """Return a made-up phone number like 555-123-4567."""
    part1 = rng.randint(200, 999)
    part2 = rng.randint(100, 999)
    part3 = rng.randint(0, 9999)
    return "%03d-%03d-%04d" % (part1, part2, part3)


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
                       "Usage:   1-1-generate-CUSTOMER_LOYALTY_table_rows.py YYYY-MM-DD [OUTPUT_DIR]\n"
                       "Example: 1-1-generate-CUSTOMER_LOYALTY_table_rows.py " + date.today().isoformat() + "\n")

    # The date must be a real calendar date, not just text that looks like one (2026-02-31 is rejected).
    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error("invalid date '" + args.run_date + "', expected YYYY-MM-DD")

    if args.orders is not None and args.orders < 1:
        parser.error("orders must be a positive integer")

    # How many rows to generate: --rows if it was given, otherwise the default of this script.
    if args.rows is None:
        number_of_rows = N_CUSTOMERS
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
        print("CUSTOMER_LOYALTY rows for " + args.run_date + " have already been generated in "
              + str(csv_path.resolve()) + ": nothing to do")
        return

    if args.output_dir is None:
        print("OUTPUT_DIR not provided: the file will be created in the folder " + str(day_folder.resolve()))

    # parents=True creates missing parent folders too, exist_ok=True is not an error if the folder is already there.
    day_folder.mkdir(parents=True, exist_ok=True)

    # ---- 3. Find out where the numbering of the new rows has to start -------------------------------------
    # The new rows are numbered highest ID + 1, + 2, + 3 ...
    if number_of_rows == 0:
        highest_ids = {"CUSTOMER_ID": 0}
    elif args.no_snowflake:
        highest_ids = {"CUSTOMER_ID": 0}
        print("--no-snowflake: IDs start from 1 (they may clash with data already in Snowflake)")
    else:
        highest_ids = f_get_highest_ids()

    # ---- 4. Prepare the random generator ------------------------------------------------------------------
    # Seeded with the day number and the table name: the same date always gives the same random values,
    # and this script does not depend on how many random values any other script uses.
    days_since_epoch = (run_date - EPOCH).days
    rng = random.Random(str(days_since_epoch) + ":CUSTOMER_LOYALTY")

    # ---- 5. Write the CSV file ----------------------------------------------------------------------------
    # newline="" and lineterminator="\n" make the file use plain Unix line endings on every operating system.
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")

        # First line of the file: the column names.
        writer.writerow(CSV_COLUMNS)

        # One row per new customer. "number" goes 1, 2, 3 ... N_CUSTOMERS.
        for number in range(1, number_of_rows + 1):
            customer_id = highest_ids["CUSTOMER_ID"] + number

            # Pick one of the first N_CITIES cities; the country comes from the same position in its list.
            city_position = rng.randint(0, N_CITIES - 1)

            first_name = rng.choice(FIRST_NAMES)
            last_name = rng.choice(LAST_NAMES)

            # A 5-digit postal code, padded with leading zeros if needed.
            postal_code = "%05d" % rng.randint(10000, 99999)

            preferred_language = rng.choice(LANGUAGES)
            gender = rng.choice(GENDERS)
            favourite_brand = rng.choice(BRANDS)
            marital_status = rng.choice(MARITAL_STATUSES)
            children_count = rng.randint(0, 4)

            # The customer signs up on the day we generate data for; the birthday is a random date.
            sign_up_date = args.run_date
            birthday = f_random_date(rng, 1955, 2005)

            # The customer ID is added to the e-mail address, so two customers with the same name differ.
            e_mail = first_name.lower() + "." + last_name.lower() + str(customer_id) + "@example.com"
            phone_number = f_random_phone(rng)

            writer.writerow([
                customer_id,
                first_name,
                last_name,
                CITIES[city_position],
                COUNTRIES[city_position],
                postal_code,
                preferred_language,
                gender,
                favourite_brand,
                marital_status,
                children_count,
                sign_up_date,
                birthday,
                e_mail,
                phone_number,
            ])

    # ---- 6. Tell the user what was done -------------------------------------------------------------------
    print("Generated " + str(csv_path) + ": " + str(number_of_rows) + " rows")


if __name__ == "__main__":
    main()
