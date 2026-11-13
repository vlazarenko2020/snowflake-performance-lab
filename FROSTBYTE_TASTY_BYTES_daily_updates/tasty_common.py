"""Shared code for the 1-generate-<TABLE>_table_rows.py scripts (one script per table).

Not meant to be run directly. Every script calls f_start() to read the command line, decide whether there is
anything to do, and read the current MAX(id) of its own table(s) from Snowflake; then it writes its CSV file(s).

Run order matters only for tables that refer to other tables. A script that needs rows of another table reads
that table's CSV from the same day folder (Batch.read_rows) and stops with a hint if the file is missing:

    COUNTRY, FRANCHISE, LOCATION, MENU, CUSTOMER_LOYALTY      no dependencies
    TRUCK                                                     needs franchise.csv
    ORDER_HEADER + ORDER_DETAIL                               need location, truck, menu, customer_loyalty CSVs
"""
import argparse
import csv
import os
import random
import sys
from datetime import date
from pathlib import Path

EPOCH = date(1970, 1, 1)

FIRST_NAMES = ("Ava Liam Noah Emma Olivia Mia Lucas Sofia Ethan Chloe Mateo Yuki Amir Lena Raj "
               "Isabella Oliver Amelia Elijah Harper Henry Evelyn Jack Grace Leo Nora Daniel Zoe Samuel Layla "
               "Hugo Freya Mohamed Aisha Chen Mei Hiroshi Akira Priya Arjun Ananya Diego Valentina Santiago Camila "
               "Anders Ingrid Sven Katarina Dmitri Natasha Pavel Olga Luca Giulia Marco Elena Kofi Amara Tunde Zara "
               "Omar Fatima Yusuf Leila Jin Soo Min Hana Tomas Petra Felix Clara Andre Beatriz").split()
LAST_NAMES = ("Smith Garcia Muller Rossi Tanaka Kim Novak Silva Dubois Patel Brown Jensen Lopez Cohen Ali "
              "Johnson Williams Jones Davis Miller Wilson Moore Taylor Anderson Thomas Martin Lee Walker Hall "
              "Fernandez Martinez Gonzalez Rodriguez Hernandez Perez Sanchez Ramirez Torres Flores Costa Pereira Santos "
              "Schmidt Schneider Fischer Weber Wagner Becker Hoffmann Bianchi Ferrari Romano Moreau Laurent Bernard "
              "Ivanov Petrov Kowalski Nowak Nielsen Hansen Larsen Johansson Lindberg Sato Suzuki Watanabe Wang Zhang "
              "Liu Nguyen Tran Singh Sharma Gupta Khan Hassan Ahmed Okafor Mensah Adeyemi Murphy Walsh").split()
# The next five lists are parallel: index i describes the same city.
CITIES = ["Seattle", "Boston", "Denver", "Toronto", "Vancouver", "London", "Paris", "Berlin",
          "Madrid", "Tokyo", "Sydney", "Mumbai", "Sao Paulo", "Seoul", "Cairo"]
COUNTRIES = ["United States", "United States", "United States", "Canada", "Canada", "England", "France",
             "Germany", "Spain", "Japan", "Australia", "India", "Brazil", "South Korea", "Egypt"]
ISO_CODES = "US US US CA CA GB FR DE ES JP AU IN BR KR EG".split()
CURRENCIES = "USD USD USD CAD CAD GBP EUR EUR EUR JPY AUD INR BRL KRW EGP".split()
CURRENCY_BY_ISO = dict(zip(ISO_CODES, CURRENCIES))      # one currency per country code
LANGUAGES = ["English", "French", "German", "Spanish", "Japanese"]
BRANDS = ["Kitakata Ramen Bar", "Freezing Point", "Smoky BBQ", "Guac n Roll", "The Mega Melt", "Tasty Tibs",
          "Le Coin des Crepes", "Better Off Bread", "Plant Palace", "Revenge of the Curds", "Cheeky Greek",
          "Peking Truck", "Nani's Kitchen", "The Mac Shack", "Not the Wurst Hot Dogs"]
GENDERS = ["Male", "Female", "Undisclosed"]
MARITAL = ["Single", "Married", "Divorced", "Undisclosed"]
CATEGORIES = ["Main", "Beverage", "Dessert", "Snack"]
SUBCATEGORIES = ["Hot Option", "Cold Option", "Warm Option"]
MAKES = ["Ford", "Freightliner", "Chevrolet", "Nissan", "Isuzu"]
MODELS = ["Step Van", "Box Truck", "NV200", "NPR", "Utilimaster"]

DEFAULT_OUTPUT_DIR = "./data"
DEFAULT_ORDERS = 500

# Everything except orders is kept small: only a few rows per table per daily batch.
N_CITIES = 3          # first N cities / countries (COUNTRY rows, and the cities used by every other table)
N_FRANCHISES = 3
N_LOCATIONS = 5
N_TRUCKS = 4
N_BRANDS = 3          # menu brands (4 menu items each)
N_CUSTOMERS = 5       # new loyalty sign-ups per day

# Which script writes which CSV (used for the "generate it first" hints).
GENERATORS = {
    "country.csv": "1-generate-COUNTRY_table_rows.py",
    "franchise.csv": "1-generate-FRANCHISE_table_rows.py",
    "location.csv": "1-generate-LOCATION_table_rows.py",
    "truck.csv": "1-generate-TRUCK_table_rows.py",
    "menu.csv": "1-generate-MENU_table_rows.py",
    "customer_loyalty.csv": "1-generate-CUSTOMER_LOYALTY_table_rows.py",
    "order_header.csv": "1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py",
    "order_detail.csv": "1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py",
}


def f_money(value):
    return f"{value:.4f}"


def f_fetch_max_ids(id_columns):
    """Return {key: MAX(id)} for the given ID columns (0 for an empty table), read from Snowflake.

    id_columns is a list of (key, schema kind, table, id column). The kind "pos" / "customer" maps to the
    TASTY_SCHEMA / TASTY_CUSTOMER_SCHEMA settings, like in 2-load_tasty_bytes_data.py.
    """
    try:
        from dotenv import load_dotenv
        from snowflake.snowpark import Session
    except ImportError:
        sys.exit("ERROR: snowflake-snowpark-python and python-dotenv are needed to read MAX(id) from Snowflake.\n"
                 "Run the script with 'uv run' (see README), or use --no-snowflake to number the IDs from 1.")
    connection_from_env = bool(os.environ.get("CONNECTION", "").strip())
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    connection = os.environ.get("CONNECTION", "").strip()
    if not connection:
        sys.exit("ERROR: the CONNECTION variable is not set (or is empty), so MAX(id) cannot be read from Snowflake.\n"
                 "Set it in the repo's .env (CONNECTION=<name from ~/.snowflake/config.toml>), or use --no-snowflake.")
    print(f"Reading MAX(id) with Snowflake connection '{connection}' "
          f"(taken from {'the environment' if connection_from_env else 'the .env file'})")
    db = os.environ.get("TASTY_DB", "FROSTBYTE_TASTY_BYTES_2")
    schemas = {"pos": os.environ.get("TASTY_SCHEMA", "RAW_POS"),
               "customer": os.environ.get("TASTY_CUSTOMER_SCHEMA", "RAW_CUSTOMER")}
    session = Session.builder.configs({"connection_name": connection}).create()
    try:
        ids = {}
        for key, kind, table, col in id_columns:
            ids[key] = session.sql(f"SELECT COALESCE(MAX({col}), 0) FROM {db}.{schemas[kind]}.{table}").collect()[0][0]
            print(f"  MAX({table}.{col}) = {ids[key]}")
        return ids
    finally:
        session.close()


class Batch:
    """Everything one script needs to generate its table(s) for one day."""

    def __init__(self, run_date, out_dir, n_orders, ids, rng):
        self.run_date = run_date          # 'YYYY-MM-DD'
        self.out_dir = out_dir            # DATA_DIR/<run_date>/
        self.n_orders = n_orders
        self.ids = ids                    # {key: MAX(id)}; new rows are numbered ids[key] + 1, + 2, ...
        self.rng = rng
        self.day = (date.fromisoformat(run_date) - EPOCH).days    # days since 1970-01-01 (also used in SHIFT_ID)

    def ri(self, lo, hi):
        """Random integer, both ends included."""
        return self.rng.randint(lo, hi)

    def pick(self, seq):
        return self.rng.choice(seq)

    def rdate(self, y1, y2):
        return f"{self.ri(y1, y2)}-{self.ri(1, 12):02d}-{self.ri(1, 28):02d}"

    def phone(self):
        return f"{self.ri(200, 999):03d}-{self.ri(100, 999):03d}-{self.ri(0, 9999):04d}"

    def writer(self, name, header):
        """Open DATA_DIR/<date>/<name> for writing and write the header row. Returns (file, csv writer)."""
        f = open(self.out_dir / name, "w", newline="", encoding="utf-8")
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header.split(","))
        return f, w

    def read_rows(self, name):
        """Rows (as dicts) of another table's CSV from the same day folder; stops with a hint if it is missing."""
        path = self.out_dir / name
        if not path.is_file():
            sys.exit(f"ERROR: {path.resolve()} does not exist, and this table refers to its rows.\n"
                     f"Generate it first: {GENERATORS[name]} {self.run_date} {self.out_dir.parent}")
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def summary(self, *names):
        """Print how many data rows each written CSV holds."""
        for name in names:
            with open(self.out_dir / name, encoding="utf-8") as f:
                n = sum(1 for _ in f) - 1          # minus the header row
            print(f"Generated {self.out_dir / name}: {n} rows")


def f_start(script_file, table, csv_files, id_columns, uses_orders=False):
    """Read the command line and prepare one script's run. Returns a Batch, or None if there is nothing to do.

    Same parameters for every script:  YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
    ORDERS only matters to the ORDER_HEADER / ORDER_DETAIL script; the other scripts accept it and ignore it.
    """
    script = Path(script_file).name
    parser = argparse.ArgumentParser(
        prog=script,
        description=f"Generate the daily {table} rows as CSV ({', '.join(csv_files)}).",
        epilog="example: %(prog)s 2026-11-08 ./data 500   ->   ./data/2026-11-08/" + csv_files[0])
    parser.add_argument("run_date", nargs="?", help="MANDATORY. The day to generate data for, as YYYY-MM-DD")
    parser.add_argument("output_dir", nargs="?", help=f"base output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("orders", nargs="?", type=int,
                        help=f"number of orders (default: {DEFAULT_ORDERS}); only used by the ORDER_HEADER/ORDER_DETAIL script")
    parser.add_argument("--no-snowflake", action="store_true",
                        help="do not read MAX(id) from Snowflake: number every ID from 1 (offline testing only)")
    args = parser.parse_args()

    if args.run_date is None:
        parser.exit(2, (
            "ERROR: the date is mandatory.\n"
            "Provide the day to generate data for as the first argument, in the format YYYY-MM-DD.\n"
            "It decides the folder name and the random seed. (The IDs are numbered after the current MAX(id)\n"
            "of the table in Snowflake.)\n\n"
            f"Usage:   {script} YYYY-MM-DD [OUTPUT_DIR] [ORDERS]\n"
            f"Example: {script} {date.today().isoformat()}\n"))
    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error(f"invalid date '{args.run_date}', expected YYYY-MM-DD")

    output_dir = args.output_dir if args.output_dir is not None else DEFAULT_OUTPUT_DIR
    n_orders = args.orders if args.orders is not None else DEFAULT_ORDERS
    if n_orders < 1:
        parser.error("orders must be a positive integer")

    out_dir = Path(output_dir) / args.run_date
    if all((out_dir / name).is_file() and (out_dir / name).stat().st_size > 0 for name in csv_files):
        print(f"{table} rows for {args.run_date} have already been generated in {out_dir.resolve()}: nothing to do")
        return None
    if args.output_dir is None:
        print(f"OUTPUT_DIR not provided: the files will be created in the folder {out_dir.resolve()}")
    if uses_orders and args.orders is None:
        print(f"ORDERS not provided: generating the default {DEFAULT_ORDERS} orders")
    out_dir.mkdir(parents=True, exist_ok=True)

    # First IDs of this batch: every new row is numbered after the current MAX(id) of its table.
    if args.no_snowflake:
        ids = {key: 0 for key, *_ in id_columns}
        print("--no-snowflake: IDs start from 1 (they may clash with data already in Snowflake)")
    else:
        ids = f_fetch_max_ids(id_columns)

    # Seeded from the date AND the table, so each script is repeatable on its own and does not depend on
    # the order or number of random values drawn by the other scripts.
    rng = random.Random(f"{(run_date - EPOCH).days}:{table}")
    return Batch(args.run_date, out_dir, n_orders, ids, rng)
