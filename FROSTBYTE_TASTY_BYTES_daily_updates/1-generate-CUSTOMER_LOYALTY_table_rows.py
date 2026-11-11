#!/usr/bin/env python3
"""Generate the daily CUSTOMER_LOYALTY rows (new sign-ups for the day) -> DATA_DIR/<date>/customer_loyalty.csv

Usage: ./1-generate-CUSTOMER_LOYALTY_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [("customer", "customer", "CUSTOMER_LOYALTY", "CUSTOMER_ID")]


def main():
    b = c.f_start(__file__, "CUSTOMER_LOYALTY", ["customer_loyalty.csv"], ID_COLUMNS)
    if b is None:
        return
    f, w = b.writer("customer_loyalty.csv", ("CUSTOMER_ID,FIRST_NAME,LAST_NAME,CITY,COUNTRY,POSTAL_CODE,"
                                             "PREFERRED_LANGUAGE,GENDER,FAVOURITE_BRAND,MARITAL_STATUS,CHILDREN_COUNT,"
                                             "SIGN_UP_DATE,BIRTHDAY,E_MAIL,PHONE_NUMBER"))
    with f:
        for i in range(1, c.N_CUSTOMERS + 1):
            customer_id = b.ids["customer"] + i
            city = b.ri(0, c.N_CITIES - 1)
            first, last = b.pick(c.FIRST_NAMES), b.pick(c.LAST_NAMES)
            w.writerow([customer_id, first, last, c.CITIES[city], c.COUNTRIES[city], f"{b.ri(10000, 99999):05d}",
                        b.pick(c.LANGUAGES), b.pick(c.GENDERS), b.pick(c.BRANDS), b.pick(c.MARITAL), b.ri(0, 4),
                        b.run_date, b.rdate(1955, 2005), f"{first.lower()}.{last.lower()}{customer_id}@example.com",
                        b.phone()])
    b.summary("customer_loyalty.csv")


if __name__ == "__main__":
    main()
