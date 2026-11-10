#!/usr/bin/env python3
"""Generate a fictional daily batch of CSV files for the TASTY_BYTES tables.

Python port of generate_tasty_bytes_data.sh (same tables, columns, row counts and ID scheme).

Usage:
    ./1-generate_tasty_bytes_data.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS]
    e.g. ./1-generate_tasty_bytes_data.py 2026-11-08 ./data 500   # -> ./data/2026-11-08/*.csv

The date is mandatory. OUTPUT_DIR (default ./data) and ORDERS (default 500) are optional; when they
are left out, the script says which defaults it is using and where the files will be created.

IDs: every table gets NEW IDs, always bigger than the current MAX(id) in Snowflake. Before generating,
the script reads the maximum ID of each table (needs CONNECTION, same settings as 2-load_tasty_bytes_data.py)
and numbers the new rows MAX+1, MAX+2, ... so they never collide with rows that are already loaded.
Use --no-snowflake to skip that lookup and number from 1 (offline testing only: the IDs will clash with
existing data if loaded).

Repeatable: the random values are seeded from the date, so the same date gives the same values. The IDs
depend on what is in Snowflake when the files are generated, so regenerating a day after it was loaded
would give the same rows under new IDs (the existing files are kept: see f_already_generated).
(Not byte-identical to the .sh version: awk and Python use different random number generators.)
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


def f_money(value):
    return f"{value:.4f}"


# Where the current MAX(id) is read from: (key, schema kind, table, id column). "pos" / "customer" map to the
# TASTY_SCHEMA / TASTY_CUSTOMER_SCHEMA settings, like in 2-load_tasty_bytes_data.py.
ID_COLUMNS = [
    ("country_id", "pos", "COUNTRY", "COUNTRY_ID"),
    ("city_id", "pos", "COUNTRY", "CITY_ID"),
    ("franchise", "pos", "FRANCHISE", "FRANCHISE_ID"),
    ("location", "pos", "LOCATION", "LOCATION_ID"),
    ("truck", "pos", "TRUCK", "TRUCK_ID"),
    ("menu_id", "pos", "MENU", "MENU_ID"),
    ("menu_type_id", "pos", "MENU", "MENU_TYPE_ID"),
    ("menu_item", "pos", "MENU", "MENU_ITEM_ID"),
    ("customer", "customer", "CUSTOMER_LOYALTY", "CUSTOMER_ID"),
    ("order", "pos", "ORDER_HEADER", "ORDER_ID"),
    ("detail", "pos", "ORDER_DETAIL", "ORDER_DETAIL_ID"),
]


def f_fetch_max_ids():
    """Return {key: MAX(id)} for every ID column in ID_COLUMNS (0 for an empty table), read from Snowflake."""
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
        for key, kind, table, col in ID_COLUMNS:
            ids[key] = session.sql(f"SELECT COALESCE(MAX({col}), 0) FROM {db}.{schemas[kind]}.{table}").collect()[0][0]
            print(f"  MAX({table}.{col}) = {ids[key]}")
        return ids
    finally:
        session.close()


EXPECTED_FILES = ["country.csv", "franchise.csv", "location.csv", "truck.csv", "menu.csv",
                  "customer_loyalty.csv", "order_header.csv", "order_detail.csv"]


def f_already_generated(out_dir):
    """True if the day's folder already holds every expected CSV file (each non-empty)."""
    return all((out_dir / name).is_file() and (out_dir / name).stat().st_size > 0 for name in EXPECTED_FILES)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a fictional daily batch of TASTY_BYTES CSV files.",
        epilog="example: %(prog)s 2026-11-08 ./data 500   ->   ./data/2026-11-08/*.csv")
    parser.add_argument("run_date", nargs="?", help="MANDATORY. The day to generate data for, as YYYY-MM-DD")
    parser.add_argument("output_dir", nargs="?", help=f"base output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("orders", nargs="?", type=int, help=f"number of orders (default: {DEFAULT_ORDERS})")
    parser.add_argument("--no-snowflake", action="store_true",
                        help="do not read MAX(id) from Snowflake: number every ID from 1 (offline testing only)")
    args = parser.parse_args()

    if args.run_date is None:
        parser.exit(2, (
            "ERROR: the date is mandatory.\n"
            "Provide the day to generate data for as the first argument, in the format YYYY-MM-DD.\n"
            "It decides the folder name and the random seed. (The IDs are numbered after the current MAX(id)\n"
            "of each table in Snowflake.)\n\n"
            "Usage:   1-generate_tasty_bytes_data.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS]\n"
            f"Example: 1-generate_tasty_bytes_data.py {date.today().isoformat()}\n"))

    try:
        run_date = date.fromisoformat(args.run_date)
    except ValueError:
        parser.error(f"invalid date '{args.run_date}', expected YYYY-MM-DD")

    output_dir = args.output_dir if args.output_dir is not None else DEFAULT_OUTPUT_DIR
    n_orders = args.orders if args.orders is not None else DEFAULT_ORDERS
    if n_orders < 1:
        parser.error("orders must be a positive integer")

    out_dir = Path(output_dir) / args.run_date
    if f_already_generated(out_dir):
        print(f"Data for {args.run_date} has already been generated in {out_dir.resolve()}: nothing to do")
        return
    if args.output_dir is None:
        print(f"OUTPUT_DIR not provided: the files will be created in the folder {out_dir.resolve()}")
    if args.orders is None:
        print(f"ORDERS not provided: generating the default {DEFAULT_ORDERS} orders")
    out_dir.mkdir(parents=True, exist_ok=True)

    # First IDs of this batch: every new row is numbered after the current MAX(id) of its table.
    if args.no_snowflake:
        ids = {key: 0 for key, *_ in ID_COLUMNS}
        print("--no-snowflake: IDs start from 1 (they may clash with data already in Snowflake)")
    else:
        ids = f_fetch_max_ids()

    day = (run_date - EPOCH).days         # seeds the RNG (and the shift id)
    rng = random.Random(day)
    ri = rng.randint                      # ri(lo, hi): inclusive, like the awk helper
    n_cities = N_CITIES

    def f_pick(seq):
        return rng.choice(seq)

    def f_rdate(y1, y2):
        return f"{ri(y1, y2)}-{ri(1, 12):02d}-{ri(1, 28):02d}"

    def f_phone():
        return f"{ri(200, 999):03d}-{ri(100, 999):03d}-{ri(0, 9999):04d}"

    def f_writer(name, header):
        f = open(out_dir / name, "w", newline="", encoding="utf-8")
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        return f, w

    # ---------- COUNTRY (one row per city) ----------
    f, w = f_writer("country.csv", "COUNTRY_ID,COUNTRY,ISO_CURRENCY,ISO_COUNTRY,CITY_ID,CITY,CITY_POPULATION".split(","))
    with f:
        for i in range(n_cities):
            w.writerow([ids["country_id"] + i + 1, COUNTRIES[i], CURRENCIES[i], ISO_CODES[i], ids["city_id"] + i + 1, CITIES[i],
                        ri(500000, 12000000)])

    # ---------- FRANCHISE ----------
    f, w = f_writer("franchise.csv", "FRANCHISE_ID,FIRST_NAME,LAST_NAME,CITY,COUNTRY,E_MAIL,PHONE_NUMBER".split(","))
    with f:
        for i in range(1, N_FRANCHISES + 1):
            c = ri(0, n_cities - 1)
            fn, ln = f_pick(FIRST_NAMES), f_pick(LAST_NAMES)
            w.writerow([ids["franchise"] + i, fn, ln, CITIES[c], COUNTRIES[c], f"{fn.lower()}.{ln.lower()}@example.com", f_phone()])

    # ---------- LOCATION ----------
    loc_city = {}                          # location_id -> city index (used for the order currency)
    f, w = f_writer("location.csv", "LOCATION_ID,PLACEKEY,LOCATION,CITY,REGION,ISO_COUNTRY_CODE,COUNTRY".split(","))
    with f:
        for i in range(1, N_LOCATIONS + 1):
            c = ri(0, n_cities - 1)
            lid = ids["location"] + i
            loc_city[lid] = c
            w.writerow([lid, f"zz{lid:04d}@abc-def-ghi", f"{CITIES[c]} Square {lid}", CITIES[c], CITIES[c],
                        ISO_CODES[c], COUNTRIES[c]])

    # ---------- TRUCK ----------
    f, w = f_writer("truck.csv", ("TRUCK_ID,FRANCHISE_ID,PRIMARY_CITY,REGION,ISO_REGION,COUNTRY,ISO_COUNTRY_CODE,"
                                "FRANCHISE_FLAG,YEAR,MAKE,MODEL,EV_FLAG,TRUCK_OPENING_DATE,TRUCK_START_DATE").split(","))
    with f:
        for i in range(1, N_TRUCKS + 1):
            c, m = ri(0, n_cities - 1), ri(0, 4)
            w.writerow([ids["truck"] + i, ids["franchise"] + ri(1, N_FRANCHISES), CITIES[c], CITIES[c], ISO_CODES[c], COUNTRIES[c], ISO_CODES[c],
                        int(rng.random() < 0.3), ri(2005, 2025), MAKES[m], MODELS[m], int(rng.random() < 0.2),
                        ri(2015, 2025), f_rdate(2015, 2025)])

    # ---------- MENU ----------
    price = {}                             # menu_item_id -> sale price (unrounded, used by the order lines)
    n_menu = 0
    f, w = f_writer("menu.csv", ("MENU_ID,MENU_TYPE_ID,MENU_TYPE,TRUCK_BRAND_NAME,MENU_ITEM_ID,MENU_ITEM_NAME,"
                               "ITEM_CATEGORY,ITEM_SUBCATEGORY,COST_OF_GOODS_USD,SALE_PRICE_USD,"
                               "MENU_ITEM_HEALTH_METRICS_OBJ").split(","))
    with f:
        for b, brand in enumerate(BRANDS[:N_BRANDS], start=1):
            for k in range(1, 5):
                n_menu += 1
                item_id = ids["menu_item"] + n_menu
                cost = 0.5 + rng.random() * 6
                sale = cost * (1.8 + rng.random() * 1.5)
                price[item_id] = sale
                health = '{"is_healthy":"%s","calories":%d}' % ("Y" if rng.random() < 0.4 else "N", ri(150, 1200))
                w.writerow([ids["menu_id"] + n_menu, ids["menu_type_id"] + b, f"Type {ids['menu_type_id'] + b}", brand, item_id, f"{brand} Item {k}", CATEGORIES[k - 1],
                            f_pick(SUBCATEGORIES), f_money(cost), f_money(sale), health])

    # ---------- CUSTOMER_LOYALTY (new sign-ups for the day) ----------
    n_cust = N_CUSTOMERS
    customers = []
    f, w = f_writer("customer_loyalty.csv", ("CUSTOMER_ID,FIRST_NAME,LAST_NAME,CITY,COUNTRY,POSTAL_CODE,"
                                           "PREFERRED_LANGUAGE,GENDER,FAVOURITE_BRAND,MARITAL_STATUS,CHILDREN_COUNT,"
                                           "SIGN_UP_DATE,BIRTHDAY,E_MAIL,PHONE_NUMBER").split(","))
    with f:
        for i in range(1, n_cust + 1):
            cid = ids["customer"] + i
            customers.append(cid)
            c = ri(0, n_cities - 1)
            fn, ln = f_pick(FIRST_NAMES), f_pick(LAST_NAMES)
            w.writerow([cid, fn, ln, CITIES[c], COUNTRIES[c], f"{ri(10000, 99999):05d}", f_pick(LANGUAGES),
                        f_pick(GENDERS), f_pick(BRANDS), f_pick(MARITAL), ri(0, 4), args.run_date, f_rdate(1955, 2005),
                        f"{fn.lower()}.{ln.lower()}{cid}@example.com", f_phone()])

    # ---------- ORDER_HEADER + ORDER_DETAIL ----------
    fh, wh = f_writer("order_header.csv", ("ORDER_ID,TRUCK_ID,LOCATION_ID,CUSTOMER_ID,DISCOUNT_ID,SHIFT_ID,"
                                         "SHIFT_START_TIME,SHIFT_END_TIME,ORDER_CHANNEL,ORDER_TS,SERVED_TS,"
                                         "ORDER_CURRENCY,ORDER_AMOUNT,ORDER_TAX_AMOUNT,ORDER_DISCOUNT_AMOUNT,"
                                         "ORDER_TOTAL").split(","))
    fd, wd = f_writer("order_detail.csv", ("ORDER_DETAIL_ID,ORDER_ID,MENU_ITEM_ID,DISCOUNT_ID,LINE_NUMBER,QUANTITY,"
                                         "UNIT_PRICE,PRICE,ORDER_ITEM_DISCOUNT_AMOUNT").split(","))
    with fh, fd:
        detail_id = ids["detail"]
        for o in range(1, n_orders + 1):
            oid = ids["order"] + o
            loc = ids["location"] + ri(1, N_LOCATIONS)
            cust_id = rng.choice(customers) if rng.random() < 0.4 else ""
            shift = 1 if rng.random() < 0.5 else 2
            hh = ri(8, 14) if shift == 1 else ri(15, 21)
            ts = f"{args.run_date} {hh:02d}:{ri(0, 59):02d}:{ri(0, 59):02d}"
            amount = 0.0
            for line in range(1, ri(1, 4) + 1):
                item, qty = ids["menu_item"] + ri(1, n_menu), ri(1, 3)
                unit_price = price[item]
                line_price = unit_price * qty
                amount += line_price
                detail_id += 1
                wd.writerow([detail_id, oid, item, "", line, qty, f_money(unit_price), f_money(line_price), ""])
            start, end = ("08:00:00", "14:00:00") if shift == 1 else ("15:00:00", "22:00:00")
            wh.writerow([oid, ids["truck"] + ri(1, N_TRUCKS), loc, cust_id, "", day * 10 + shift, start, end, "", ts, "",
                         CURRENCIES[loc_city[loc]], f_money(amount), "", "", f_money(amount)])

    # ---------- summary (like `wc -l`) ----------
    print(f"Generated files in {out_dir}:")
    total = 0
    for path in sorted(out_dir.glob("*.csv")):
        with open(path, encoding="utf-8") as fh_:
            n = sum(1 for _ in fh_)
        total += n
        print(f"{n:8d} {path}")
    print(f"{total:8d} total")


if __name__ == "__main__":
    main()
