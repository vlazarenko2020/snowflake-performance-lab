#!/usr/bin/env python3
"""Generate the daily TRUCK rows -> DATA_DIR/<date>/truck.csv

Needs franchise.csv of the same day (each truck belongs to one of the new franchises):
run 1-generate-FRANCHISE_table_rows.py first.

Usage: ./1-generate-TRUCK_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [("truck", "pos", "TRUCK", "TRUCK_ID")]


def main():
    b = c.f_start(__file__, "TRUCK", ["truck.csv"], ID_COLUMNS)
    if b is None:
        return
    franchise_ids = [int(row["FRANCHISE_ID"]) for row in b.read_rows("franchise.csv")]
    f, w = b.writer("truck.csv", ("TRUCK_ID,FRANCHISE_ID,PRIMARY_CITY,REGION,ISO_REGION,COUNTRY,ISO_COUNTRY_CODE,"
                                  "FRANCHISE_FLAG,YEAR,MAKE,MODEL,EV_FLAG,TRUCK_OPENING_DATE,TRUCK_START_DATE"))
    with f:
        for i in range(1, c.N_TRUCKS + 1):
            city, model = b.ri(0, c.N_CITIES - 1), b.ri(0, 4)
            w.writerow([b.ids["truck"] + i, b.pick(franchise_ids), c.CITIES[city], c.CITIES[city], c.ISO_CODES[city],
                        c.COUNTRIES[city], c.ISO_CODES[city], int(b.rng.random() < 0.3), b.ri(2005, 2025),
                        c.MAKES[model], c.MODELS[model], int(b.rng.random() < 0.2), b.ri(2015, 2025),
                        b.rdate(2015, 2025)])
    b.summary("truck.csv")


if __name__ == "__main__":
    main()
