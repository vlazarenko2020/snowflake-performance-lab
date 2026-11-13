#!/usr/bin/env python3
"""Generate the daily ORDER_HEADER and ORDER_DETAIL rows
-> OUTPUT_DIR/<date>/order_header.csv and OUTPUT_DIR/<date>/order_detail.csv

This script is fully standalone: it does not import any other script of this project.

The two tables are generated together, because they belong together: an order (header) has one to four
lines (details), and the order amount in the header is the sum of the prices of its lines.

Every order refers to a location, a truck, menu items and (sometimes) a customer. These are taken from:
    1. the CSV files of the same day (location.csv, truck.csv, menu.csv, customer_loyalty.csv), if they
       exist. They may have no rows: most days no location, truck or menu item is added;
    2. the tables in Snowflake (rows from earlier days), unless --no-snowflake is used.
The scripts that write the CSV files are 1-1-generate-LOCATION / TRUCK / MENU / CUSTOMER_LOYALTY_table_rows.py.
If no row is found at all for one of them, the script stops with a hint.

Usage:
    ./1-1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
    e.g. ./1-1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py 2026-11-08 ./data 500

    YYYY-MM-DD      mandatory, the day to generate data for
    OUTPUT_DIR      optional, base folder for the CSV files (default ./data)
    ORDERS          optional, how many orders to generate (default 500)
    --no-snowflake  do not ask Snowflake for the current highest IDs, number the rows from 1
                    (offline testing only: these IDs will clash with rows that are already loaded)

IDs: the new rows get IDs that are bigger than the current highest ORDER_ID and ORDER_DETAIL_ID in Snowflake,
so they never collide with rows that are already loaded. Snowflake is reached through the CONNECTION variable
(from the environment or from the .env file in the repo root), the same one the loader uses.
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
DEFAULT_ORDERS = 500

# Names of the files this script writes, and their column names (in the order they appear in the files).
HEADER_CSV_FILE_NAME = "order_header.csv"
DETAIL_CSV_FILE_NAME = "order_detail.csv"
HEADER_COLUMNS = [
    "ORDER_ID",
    "TRUCK_ID",
    "LOCATION_ID",
    "CUSTOMER_ID",
    "DISCOUNT_ID",
    "SHIFT_ID",
    "SHIFT_START_TIME",
    "SHIFT_END_TIME",
    "ORDER_CHANNEL",
    "ORDER_TS",
    "SERVED_TS",
    "ORDER_CURRENCY",
    "ORDER_AMOUNT",
    "ORDER_TAX_AMOUNT",
    "ORDER_DISCOUNT_AMOUNT",
    "ORDER_TOTAL",
]
DETAIL_COLUMNS = [
    "ORDER_DETAIL_ID",
    "ORDER_ID",
    "MENU_ITEM_ID",
    "DISCOUNT_ID",
    "LINE_NUMBER",
    "QUANTITY",
    "UNIT_PRICE",
    "PRICE",
    "ORDER_ITEM_DISCOUNT_AMOUNT",
]

# The files of the other tables this script reads (all in the same day folder).
LOCATION_CSV_FILE_NAME = "location.csv"
TRUCK_CSV_FILE_NAME = "truck.csv"
MENU_CSV_FILE_NAME = "menu.csv"
CUSTOMER_CSV_FILE_NAME = "customer_loyalty.csv"

# The location file only holds the country code (e.g. "US"); this is the currency used in each country.
# The two lists are parallel: position 0 in each list belongs together, position 1 the next one, etc.
# (Several cities share a country, so a code appears more than once. That is fine.)
ISO_CODES = ["US", "US", "US", "CA", "CA", "GB", "FR", "DE", "ES", "JP", "AU", "IN", "BR", "KR", "EG"]
CURRENCIES = ["USD", "USD", "USD", "CAD", "CAD", "GBP", "EUR", "EUR", "EUR", "JPY", "AUD", "INR", "BRL", "KRW", "EGP"]

# Every order is served in one of two shifts. A shift has fixed start and end times.
SHIFT_1_START = "08:00:00"
SHIFT_1_END = "14:00:00"
SHIFT_2_START = "15:00:00"
SHIFT_2_END = "22:00:00"

# The 1970-01-01 date is "day 0". The number of days since then is used to seed the random generator.
EPOCH = date(1970, 1, 1)


# ---------------------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------------------

def f_read_command_line():
    """Read the parameters given on the command line and return them (a Namespace object) and the parser."""
    parser = argparse.ArgumentParser(
        description="Generate the daily ORDER_HEADER and ORDER_DETAIL rows as CSV files.",
        epilog="example: %(prog)s 2026-11-08 ./data 500   ->   ./data/2026-11-08/order_header.csv + order_detail.csv")

    # nargs="?" makes a positional parameter optional. We check the date ourselves later,
    # to be able to print a clearer message than the default one.
    parser.add_argument("run_date", nargs="?",
                        help="MANDATORY. The day to generate data for, as YYYY-MM-DD")
    parser.add_argument("output_dir", nargs="?",
                        help="base output directory (default: " + DEFAULT_OUTPUT_DIR + ")")
    parser.add_argument("orders", nargs="?", type=int,
                        help="number of orders (default: " + str(DEFAULT_ORDERS) + ")")
    parser.add_argument("--no-snowflake", action="store_true",
                        help="do not read the highest IDs from Snowflake: number the rows from 1 (offline testing only)")

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
    """Ask Snowflake for the highest ORDER_ID and ORDER_DETAIL_ID that exist today. Return them in a dictionary.

    An empty table gives 0, so the first new row will get ID 1.
    """
    # Database and schema can be overridden with the same TASTY_* settings the loader uses.
    database = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schema = os.environ.get("TASTY_SCHEMA", "RAW_POS")

    # The ID columns that get new numbers: (table, column). The dictionary key is the column name.
    id_columns = [
        ("ORDER_HEADER", "ORDER_ID"),
        ("ORDER_DETAIL", "ORDER_DETAIL_ID"),
    ]

    highest_ids = {}
    session = f_open_session()
    try:
        for table, column in id_columns:
            # COALESCE(MAX(...), 0) turns "no rows yet" (NULL) into 0.
            sql = "SELECT COALESCE(MAX(" + column + "), 0) FROM " + database + "." + schema + "." + table
            rows = session.sql(sql).collect()
            highest_ids[column] = rows[0][0]
            print("  MAX(" + table + "." + column + ") = " + str(highest_ids[column]))
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


def f_read_csv_rows(csv_path):
    """Read a CSV file written by one of the other 1-1-generate-* scripts and return its rows as a list.

    Every row is a dictionary: column name -> value (as text).
    A file that does not exist gives an empty list (that table was not generated today).
    """
    rows = []
    if not csv_path.is_file():
        return rows

    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        # DictReader gives every row as a dictionary: column name -> value.
        reader = csv.DictReader(csv_file)
        for row in reader:
            rows.append(row)
    return rows


def f_read_snowflake_rows(session, table_name, columns, schema_variable, default_schema, sample_rows):
    """Read some rows of a table that is already in Snowflake and return them as a list of tuples.

    sample_rows = 0 reads the whole table, otherwise a random sample of that many rows
    (the big tables have far more rows than we need).
    """
    database = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schema = os.environ.get(schema_variable, default_schema)
    sql = "SELECT " + ", ".join(columns) + " FROM " + database + "." + schema + "." + table_name
    if sample_rows > 0:
        sql = sql + " SAMPLE (" + str(sample_rows) + " ROWS)"

    result = []
    for row in session.sql(sql).collect():
        result.append(tuple(row))
    return result


def f_money(value):
    """Format an amount with 4 decimals, the way the Snowflake table stores it (e.g. 3.1416)."""
    return "%.4f" % value


def f_currency_of_country(iso_code):
    """Return the currency used in a country, e.g. "US" -> "USD"."""
    # Countries that are not in the short list above (they can come from Snowflake) are paid in dollars.
    if iso_code not in ISO_CODES:
        return "USD"
    position = ISO_CODES.index(iso_code)
    return CURRENCIES[position]


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
                       "Usage:   1-1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS]\n"
                       "Example: 1-1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py " + date.today().isoformat() + "\n")

    # The date must be a real calendar date, not just text that looks like one (2026-02-31 is rejected).
    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error("invalid date '" + args.run_date + "', expected YYYY-MM-DD")

    if args.output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    else:
        output_dir = args.output_dir

    if args.orders is None:
        number_of_orders = DEFAULT_ORDERS
    else:
        number_of_orders = args.orders
    if number_of_orders < 1:
        parser.error("orders must be a positive integer")

    # ---- 2. Decide where the files go, and stop if they are already there ---------------------------------
    # Every day gets its own folder: OUTPUT_DIR/<date>/
    day_folder = Path(output_dir) / args.run_date
    header_path = day_folder / HEADER_CSV_FILE_NAME
    detail_path = day_folder / DETAIL_CSV_FILE_NAME

    if f_file_already_generated(header_path) and f_file_already_generated(detail_path):
        print("ORDER_HEADER and ORDER_DETAIL rows for " + args.run_date + " have already been generated in "
              + str(day_folder.resolve()) + ": nothing to do")
        return

    # ---- 3. Read what the orders refer to -----------------------------------------------------------------
    # Done before anything is created, so a missing table stops the script early.
    # For every table the rows of today's CSV file are used first and, unless --no-snowflake was given,
    # a sample of the rows already in Snowflake is added. Nothing is needed when there are no orders to write.
    currency_of_location = {}      # location id -> currency
    location_ids = []
    truck_ids = []
    price_of_item = {}             # menu item id -> sale price
    menu_item_ids = []
    customer_ids = []

    if number_of_orders > 0:
        # Locations (an order is paid in the currency of its location). Columns: LOCATION_ID, ISO_COUNTRY_CODE.
        for row in f_read_csv_rows(day_folder / LOCATION_CSV_FILE_NAME):
            location_id = int(row["LOCATION_ID"])
            if location_id not in currency_of_location:
                location_ids.append(location_id)
                currency_of_location[location_id] = f_currency_of_country(row["ISO_COUNTRY_CODE"])

        # Trucks: only their IDs are needed.
        for row in f_read_csv_rows(day_folder / TRUCK_CSV_FILE_NAME):
            truck_ids.append(int(row["TRUCK_ID"]))

        # Menu items: remember the sale price of each one.
        for row in f_read_csv_rows(day_folder / MENU_CSV_FILE_NAME):
            menu_item_id = int(row["MENU_ITEM_ID"])
            if menu_item_id not in price_of_item:
                menu_item_ids.append(menu_item_id)
                price_of_item[menu_item_id] = float(row["SALE_PRICE_USD"])

        # Customers: only their IDs are needed.
        for row in f_read_csv_rows(day_folder / CUSTOMER_CSV_FILE_NAME):
            customer_ids.append(int(row["CUSTOMER_ID"]))

        # Add the rows that are already in Snowflake.
        if not args.no_snowflake:
            session = f_open_session()
            try:
                for location_id, iso_code in f_read_snowflake_rows(
                        session, "LOCATION", ["LOCATION_ID", "ISO_COUNTRY_CODE"], "TASTY_SCHEMA", "RAW_POS", 1000):
                    location_id = int(location_id)
                    if location_id not in currency_of_location:
                        location_ids.append(location_id)
                        currency_of_location[location_id] = f_currency_of_country(iso_code)

                for row in f_read_snowflake_rows(session, "TRUCK", ["TRUCK_ID"], "TASTY_SCHEMA", "RAW_POS", 1000):
                    if int(row[0]) not in truck_ids:
                        truck_ids.append(int(row[0]))

                # The menu is small, so all of it is read (0 = no sampling).
                for menu_item_id, sale_price in f_read_snowflake_rows(
                        session, "MENU", ["MENU_ITEM_ID", "SALE_PRICE_USD"], "TASTY_SCHEMA", "RAW_POS", 0):
                    menu_item_id = int(menu_item_id)
                    if menu_item_id not in price_of_item and sale_price is not None:
                        menu_item_ids.append(menu_item_id)
                        price_of_item[menu_item_id] = float(sale_price)

                for row in f_read_snowflake_rows(session, "CUSTOMER_LOYALTY", ["CUSTOMER_ID"],
                                                 "TASTY_CUSTOMER_SCHEMA", "RAW_CUSTOMER", 1000):
                    if int(row[0]) not in customer_ids:
                        customer_ids.append(int(row[0]))
            finally:
                session.close()

        # Every table must have at least one row, otherwise there is nothing to pick from.
        # (Customers are the exception: an order can be anonymous, so an empty list is only a smaller choice.)
        if len(location_ids) == 0:
            sys.exit("ERROR: no location found for the orders. Generate some first: 1-1-generate-LOCATION_table_rows.py "
                     + args.run_date + " " + output_dir + " --rows 1")
        if len(truck_ids) == 0:
            sys.exit("ERROR: no truck found for the orders. Generate some first: 1-1-generate-TRUCK_table_rows.py "
                     + args.run_date + " " + output_dir + " --rows 1")
        if len(menu_item_ids) == 0:
            sys.exit("ERROR: no menu item found for the orders. Generate some first: 1-1-generate-MENU_table_rows.py "
                     + args.run_date + " " + output_dir + " --rows 1")

    if args.output_dir is None:
        print("OUTPUT_DIR not provided: the files will be created in the folder " + str(day_folder.resolve()))
    if args.orders is None:
        print("ORDERS not provided: generating the default " + str(DEFAULT_ORDERS) + " orders")

    # parents=True creates missing parent folders too, exist_ok=True is not an error if the folder is already there.
    day_folder.mkdir(parents=True, exist_ok=True)

    # ---- 4. Find out where the numbering of the new rows has to start -------------------------------------
    # The new rows are numbered highest ID + 1, + 2, + 3 ...
    if args.no_snowflake:
        highest_ids = {"ORDER_ID": 0, "ORDER_DETAIL_ID": 0}
        print("--no-snowflake: IDs start from 1 (they may clash with data already in Snowflake)")
    else:
        highest_ids = f_get_highest_ids()

    # ---- 5. Prepare the random generator ------------------------------------------------------------------
    # Seeded with the day number and the table name: the same date always gives the same random values,
    # and this script does not depend on how many random values any other script uses.
    days_since_epoch = (run_date - EPOCH).days
    rng = random.Random(str(days_since_epoch) + ":ORDER_HEADER_ORDER_DETAIL")

    # ---- 6. Write the two CSV files -----------------------------------------------------------------------
    # newline="" and lineterminator="\n" make the files use plain Unix line endings on every operating system.
    # Both files are open at the same time: for every order we write one header row and several detail rows.
    with open(header_path, "w", newline="", encoding="utf-8") as header_file:
        with open(detail_path, "w", newline="", encoding="utf-8") as detail_file:
            header_writer = csv.writer(header_file, lineterminator="\n")
            detail_writer = csv.writer(detail_file, lineterminator="\n")

            # First line of each file: the column names.
            header_writer.writerow(HEADER_COLUMNS)
            detail_writer.writerow(DETAIL_COLUMNS)

            # The detail rows have their own running number, which continues after the highest one in Snowflake.
            detail_id = highest_ids["ORDER_DETAIL_ID"]
            detail_row_count = 0

            # One pass per order. "number" goes 1, 2, 3 ... number_of_orders.
            for number in range(1, number_of_orders + 1):
                order_id = highest_ids["ORDER_ID"] + number

                # Where the order was placed, and so, in which currency it is paid.
                location_id = rng.choice(location_ids)
                currency = currency_of_location[location_id]

                # About 40 percent of the orders belong to a loyalty customer, the rest are anonymous
                # (an empty CUSTOMER_ID).
                if len(customer_ids) > 0 and rng.random() < 0.4:
                    customer_id = rng.choice(customer_ids)
                else:
                    customer_id = ""

                # Half of the orders are served in shift 1 (morning), half in shift 2 (afternoon).
                # The order time falls inside the hours of its shift.
                if rng.random() < 0.5:
                    shift_number = 1
                    shift_start = SHIFT_1_START
                    shift_end = SHIFT_1_END
                    hour = rng.randint(8, 14)
                else:
                    shift_number = 2
                    shift_start = SHIFT_2_START
                    shift_end = SHIFT_2_END
                    hour = rng.randint(15, 21)
                minute = rng.randint(0, 59)
                second = rng.randint(0, 59)
                order_ts = "%s %02d:%02d:%02d" % (args.run_date, hour, minute, second)

                # The shift ID is made from the day number and the shift number (e.g. day 20400, shift 2 -> 204002).
                shift_id = days_since_epoch * 10 + shift_number

                # The detail lines of this order: one to four of them. The order amount adds up their prices.
                order_amount = 0.0
                number_of_lines = rng.randint(1, 4)
                for line_number in range(1, number_of_lines + 1):
                    menu_item_id = rng.choice(menu_item_ids)
                    quantity = rng.randint(1, 3)

                    unit_price = price_of_item[menu_item_id]
                    line_price = unit_price * quantity
                    order_amount = order_amount + line_price

                    detail_id = detail_id + 1
                    detail_row_count = detail_row_count + 1
                    detail_writer.writerow([
                        detail_id,
                        order_id,
                        menu_item_id,
                        "",                         # DISCOUNT_ID: no discounts in this data
                        line_number,
                        quantity,
                        f_money(unit_price),
                        f_money(line_price),
                        "",                         # ORDER_ITEM_DISCOUNT_AMOUNT: no discounts
                    ])

                # The truck that served the order.
                truck_id = rng.choice(truck_ids)

                # There is no tax and no discount in this data, so the total is the same as the amount.
                header_writer.writerow([
                    order_id,
                    truck_id,
                    location_id,
                    customer_id,
                    "",                             # DISCOUNT_ID
                    shift_id,
                    shift_start,
                    shift_end,
                    "",                             # ORDER_CHANNEL
                    order_ts,
                    "",                             # SERVED_TS
                    currency,
                    f_money(order_amount),
                    "",                             # ORDER_TAX_AMOUNT
                    "",                             # ORDER_DISCOUNT_AMOUNT
                    f_money(order_amount),          # ORDER_TOTAL
                ])

    # ---- 7. Tell the user what was done -------------------------------------------------------------------
    print("Generated " + str(header_path) + ": " + str(number_of_orders) + " rows")
    print("Generated " + str(detail_path) + ": " + str(detail_row_count) + " rows")


if __name__ == "__main__":
    main()
