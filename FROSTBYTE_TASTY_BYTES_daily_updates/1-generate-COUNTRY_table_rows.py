#!/usr/bin/env python3
"""Generate the daily COUNTRY rows (one row per city) -> DATA_DIR/<date>/country.csv

Usage: ./1-generate-COUNTRY_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [
    ("country_id", "pos", "COUNTRY", "COUNTRY_ID"),
    ("city_id", "pos", "COUNTRY", "CITY_ID"),
]


def main():
    b = c.f_start(__file__, "COUNTRY", ["country.csv"], ID_COLUMNS)
    if b is None:
        return
    f, w = b.writer("country.csv", "COUNTRY_ID,COUNTRY,ISO_CURRENCY,ISO_COUNTRY,CITY_ID,CITY,CITY_POPULATION")
    with f:
        for i in range(c.N_CITIES):
            w.writerow([b.ids["country_id"] + i + 1, c.COUNTRIES[i], c.CURRENCIES[i], c.ISO_CODES[i],
                        b.ids["city_id"] + i + 1, c.CITIES[i], b.ri(500000, 12000000)])
    b.summary("country.csv")


if __name__ == "__main__":
    main()
