#!/usr/bin/env python3
"""Generate the daily LOCATION rows -> DATA_DIR/<date>/location.csv

Usage: ./1-generate-LOCATION_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [("location", "pos", "LOCATION", "LOCATION_ID")]


def main():
    b = c.f_start(__file__, "LOCATION", ["location.csv"], ID_COLUMNS)
    if b is None:
        return
    f, w = b.writer("location.csv", "LOCATION_ID,PLACEKEY,LOCATION,CITY,REGION,ISO_COUNTRY_CODE,COUNTRY")
    with f:
        for i in range(1, c.N_LOCATIONS + 1):
            city = b.ri(0, c.N_CITIES - 1)
            location_id = b.ids["location"] + i
            w.writerow([location_id, f"zz{location_id:04d}@abc-def-ghi", f"{c.CITIES[city]} Square {location_id}",
                        c.CITIES[city], c.CITIES[city], c.ISO_CODES[city], c.COUNTRIES[city]])
    b.summary("location.csv")


if __name__ == "__main__":
    main()
