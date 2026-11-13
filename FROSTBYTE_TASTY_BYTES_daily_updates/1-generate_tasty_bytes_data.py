#!/usr/bin/env python3
"""Generate one day of Tasty Bytes data by running all the 1-1-generate-* sub-scripts, one after another.

This script does not generate any data itself. Every table has its own sub-script
(1-1-generate-<TABLE>_table_rows.py). This wrapper decides HOW MANY rows each table gets that day,
and then starts the sub-scripts in the right order.

How many rows (all numbers are random, but the same date always gives the same numbers):
    ORDER_HEADER / ORDER_DETAIL   100 to 500 orders. The range depends on the day of the week:
                                  few on Monday and Tuesday, more in the middle of the week, most on the weekend.
    CUSTOMER_LOYALTY              new customers every day: 5 to 25 on weekdays, 25 to 60 on Saturday and Sunday.
    COUNTRY, FRANCHISE, LOCATION, TRUCK, MENU
                                  rarely change, so on most days they get 0 rows (the CSV file is written with
                                  only the header line). Now and then a day gets a few rows.

Usage:
    ./1-generate_tasty_bytes_data.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
    e.g. ./1-generate_tasty_bytes_data.py 2026-11-08 ./data

    YYYY-MM-DD      mandatory, the day to generate data for
    OUTPUT_DIR      optional, base folder for the CSV files (default ./data)
    ORDERS          optional, use exactly this number of orders instead of the random one
    --no-snowflake  number all the rows from 1 instead of reading the highest IDs from Snowflake
                    (offline testing only). Because nothing can be read from Snowflake then, FRANCHISE,
                    LOCATION, TRUCK and MENU get at least 1 row, so the orders have something to refer to.

A sub-script whose CSV file(s) already exist for that day skips itself, so running this wrapper again
for the same date is safe.
"""
import argparse
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = "./data"

# The 1970-01-01 date is "day 0". The number of days since then is used to seed the random generator.
EPOCH = date(1970, 1, 1)

# Orders per day of the week: (lowest, highest). date.weekday() gives 0 for Monday ... 6 for Sunday.
ORDERS_BY_WEEKDAY = {
    0: (100, 160),    # Monday    - the quietest day
    1: (100, 180),    # Tuesday
    2: (180, 280),    # Wednesday
    3: (200, 300),    # Thursday
    4: (280, 400),    # Friday
    5: (400, 500),    # Saturday  - the busiest days
    6: (380, 500),    # Sunday
}

# New loyalty customers per day: (lowest, highest). Always at least a few, more on Saturday and Sunday.
CUSTOMERS_ON_WEEKDAY = (5, 25)
CUSTOMERS_ON_WEEKEND = (25, 60)

# Tables that rarely change. In real life a company does not open a new country, sign a new franchise,
# add a location or a truck, or change its menu every day, so most days these tables get NO new rows.
#
# Every table has three numbers: (chance, lowest, highest)
#
#   chance   the probability that the day gets any new rows at all, from 0 (never) to 1 (every day).
#            0.02 = 2 percent = about 1 day in 50 (roughly 7 days in a year)
#            0.10 = 10 percent = about 1 day in 10 (roughly 36 days in a year)
#            On all the other days the table gets 0 rows and its CSV file has only the header line.
#   lowest   if the day DOES get rows, it gets at least this many ...
#   highest  ... and at most this many. The exact number is picked randomly between lowest and highest
#            (both included). When lowest and highest are equal, the number is always the same.
#
# Example: "FRANCHISE": (0.08, 1, 2)
#   -> on about 8 days out of 100 a franchise is added, and that day it is 1 or 2 new franchises.
#   -> on the other 92 days no franchise is added (0 rows).
#
# To make a table change more often, raise the chance. To make a busy day bigger, raise highest.
RARE_TABLES = {
    "COUNTRY": (0.02, 1, 1),        # very rare (about 1 day in 50), and always exactly 1 new row
    "FRANCHISE": (0.08, 1, 2),      # about 1 day in 12, 1 or 2 new franchises
    "LOCATION": (0.12, 1, 3),       # about 1 day in 8, 1 to 3 new places where trucks can stand
    "TRUCK": (0.10, 1, 3),          # about 1 day in 10, 1 to 3 new trucks
    "MENU": (0.06, 1, 4),           # about 1 day in 17, 1 to 4 new menu items (rows of the MENU table)
}

# The sub-scripts, in the order they have to run. Parents first, children after them.
SUB_SCRIPTS = [
    ("COUNTRY", "1-1-generate-COUNTRY_table_rows.py"),
    ("FRANCHISE", "1-1-generate-FRANCHISE_table_rows.py"),
    ("LOCATION", "1-1-generate-LOCATION_table_rows.py"),
    ("TRUCK", "1-1-generate-TRUCK_table_rows.py"),
    ("MENU", "1-1-generate-MENU_table_rows.py"),
    ("CUSTOMER_LOYALTY", "1-1-generate-CUSTOMER_LOYALTY_table_rows.py"),
    ("ORDER_HEADER_ORDER_DETAIL", "1-1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py"),
]


# ---------------------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------------------

def f_read_command_line():
    """Read the parameters given on the command line and return them (a Namespace object) and the parser."""
    parser = argparse.ArgumentParser(
        description="Generate one day of Tasty Bytes data with a random number of rows per table.",
        epilog="example: %(prog)s 2026-11-08 ./data")

    parser.add_argument("run_date", nargs="?",
                        help="MANDATORY. The day to generate data for, as YYYY-MM-DD")
    parser.add_argument("output_dir", nargs="?",
                        help="base output directory (default: " + DEFAULT_OUTPUT_DIR + ")")
    parser.add_argument("orders", nargs="?", type=int,
                        help="use exactly this number of orders instead of a random one")
    parser.add_argument("--no-snowflake", action="store_true",
                        help="number the rows from 1 instead of reading the highest IDs from Snowflake (offline testing only)")

    return parser.parse_args(), parser


def f_random_count(rng, lowest, highest):
    """Return a random whole number from lowest to highest (both included)."""
    return rng.randint(lowest, highest)


def f_choose_row_counts(run_date, orders_override, no_snowflake):
    """Decide how many rows each table gets on this day. Return a dictionary: table name -> number of rows."""
    # The same date always gives the same numbers, so re-running a day does not change the plan.
    days_since_epoch = (run_date - EPOCH).days
    rng = random.Random(str(days_since_epoch) + ":WRAPPER")

    weekday = run_date.weekday()        # 0 = Monday ... 6 = Sunday
    is_weekend = weekday >= 5

    row_counts = {}

    # The tables that rarely change: most days 0, now and then a few rows.
    for table_name, (chance, lowest, highest) in RARE_TABLES.items():
        # rng.random() gives a number from 0 to 1, so it is below 0.05 in about 5 percent of the cases.
        # The count is drawn in both cases to keep the sequence of random numbers the same for every day.
        draw = rng.random()
        count = f_random_count(rng, lowest, highest)
        if draw < chance:
            row_counts[table_name] = count
        else:
            row_counts[table_name] = 0

        # Offline there is no Snowflake to take older rows from, so the tables the orders and trucks
        # refer to need at least one row of their own.
        if no_snowflake and table_name != "COUNTRY" and row_counts[table_name] == 0:
            row_counts[table_name] = 1

    # New customers every day, more on the weekend.
    if is_weekend:
        lowest, highest = CUSTOMERS_ON_WEEKEND
    else:
        lowest, highest = CUSTOMERS_ON_WEEKDAY
    row_counts["CUSTOMER_LOYALTY"] = f_random_count(rng, lowest, highest)

    # Orders: the range depends on the day of the week, unless the user asked for an exact number.
    if orders_override is not None:
        row_counts["ORDER_HEADER_ORDER_DETAIL"] = orders_override
    else:
        lowest, highest = ORDERS_BY_WEEKDAY[weekday]
        row_counts["ORDER_HEADER_ORDER_DETAIL"] = f_random_count(rng, lowest, highest)

    return row_counts


# ---------------------------------------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------------------------------------

def main():
    args, parser = f_read_command_line()

    # ---- 1. Check the parameters -------------------------------------------------------------------------
    if args.run_date is None:
        parser.exit(2, "ERROR: the date is mandatory.\n"
                       "Provide the day to generate data for as the first argument, in the format YYYY-MM-DD.\n\n"
                       "Usage:   1-generate_tasty_bytes_data.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]\n"
                       "Example: 1-generate_tasty_bytes_data.py " + date.today().isoformat() + "\n")

    # The date must be a real calendar date, not just text that looks like one (2026-02-31 is rejected).
    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error("invalid date '" + args.run_date + "', expected YYYY-MM-DD")

    if args.orders is not None and args.orders < 1:
        parser.error("orders must be a positive integer")

    if args.output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    else:
        output_dir = args.output_dir

    # ---- 2. Decide how many rows every table gets ---------------------------------------------------------
    row_counts = f_choose_row_counts(run_date, args.orders, args.no_snowflake)

    print("Plan for " + args.run_date + " (" + run_date.strftime("%A") + "):")
    for table_name, script_name in SUB_SCRIPTS:
        print("  " + table_name.ljust(28) + str(row_counts[table_name]).rjust(5) + " rows")
    print(flush=True)

    # ---- 3. Run the sub-scripts, parents first ------------------------------------------------------------
    # The sub-scripts are in the same folder as this script.
    script_folder = Path(__file__).resolve().parent

    number_of_scripts = len(SUB_SCRIPTS)
    script_number = 0
    for table_name, script_name in SUB_SCRIPTS:
        script_number = script_number + 1
        print("=== " + str(script_number) + "/" + str(number_of_scripts) + ": " + script_name + " ===", flush=True)

        # sys.executable is the Python that runs this wrapper, so the sub-scripts use the same
        # environment (for example the one 'uv run' prepared, which has snowflake-snowpark-python).
        command = [sys.executable, str(script_folder / script_name), args.run_date, output_dir]

        if table_name == "ORDER_HEADER_ORDER_DETAIL":
            # The orders script takes the number of orders as its third parameter.
            command.append(str(row_counts[table_name]))
        else:
            # All the others take the number of rows with --rows (0 = only the header line).
            command.append("--rows")
            command.append(str(row_counts[table_name]))

        if args.no_snowflake:
            command.append("--no-snowflake")

        result = subprocess.run(command)

        # A sub-script that fails stops everything: later tables depend on the earlier ones.
        if result.returncode != 0:
            sys.exit("ERROR: " + script_name + " failed (exit code " + str(result.returncode) + "), stopping.")

        print()

    print("All " + str(number_of_scripts) + " sub-scripts finished.")


if __name__ == "__main__":
    main()
