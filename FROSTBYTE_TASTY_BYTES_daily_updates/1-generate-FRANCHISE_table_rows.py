#!/usr/bin/env python3
"""Generate the daily FRANCHISE rows -> DATA_DIR/<date>/franchise.csv

Usage: ./1-generate-FRANCHISE_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [("franchise", "pos", "FRANCHISE", "FRANCHISE_ID")]


def main():
    b = c.f_start(__file__, "FRANCHISE", ["franchise.csv"], ID_COLUMNS)
    if b is None:
        return
    f, w = b.writer("franchise.csv", "FRANCHISE_ID,FIRST_NAME,LAST_NAME,CITY,COUNTRY,E_MAIL,PHONE_NUMBER")
    with f:
        for i in range(1, c.N_FRANCHISES + 1):
            city = b.ri(0, c.N_CITIES - 1)
            first, last = b.pick(c.FIRST_NAMES), b.pick(c.LAST_NAMES)
            w.writerow([b.ids["franchise"] + i, first, last, c.CITIES[city], c.COUNTRIES[city],
                        f"{first.lower()}.{last.lower()}@example.com", b.phone()])
    b.summary("franchise.csv")


if __name__ == "__main__":
    main()
