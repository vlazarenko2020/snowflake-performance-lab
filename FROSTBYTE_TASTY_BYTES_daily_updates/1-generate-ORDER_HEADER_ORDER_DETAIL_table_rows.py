#!/usr/bin/env python3
"""Generate the daily ORDER_HEADER and ORDER_DETAIL rows -> DATA_DIR/<date>/order_header.csv + order_detail.csv

These two tables are generated together: a header's amount is the sum of its detail lines.

Needs the CSVs of the same day for the tables the orders refer to, so run these first:
    1-generate-LOCATION_table_rows.py, 1-generate-TRUCK_table_rows.py (which needs FRANCHISE),
    1-generate-MENU_table_rows.py, 1-generate-CUSTOMER_LOYALTY_table_rows.py

Usage: ./1-generate-ORDER_HEADER_ORDER_DETAIL_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [
    ("order", "pos", "ORDER_HEADER", "ORDER_ID"),
    ("detail", "pos", "ORDER_DETAIL", "ORDER_DETAIL_ID"),
]


def main():
    b = c.f_start(__file__, "ORDER_HEADER and ORDER_DETAIL", ["order_header.csv", "order_detail.csv"], ID_COLUMNS,
                  uses_orders=True)
    if b is None:
        return

    # What the orders refer to, read from the CSVs of the other tables.
    location_currency = {int(row["LOCATION_ID"]): c.CURRENCY_BY_ISO[row["ISO_COUNTRY_CODE"]]
                         for row in b.read_rows("location.csv")}
    location_ids = list(location_currency)
    truck_ids = [int(row["TRUCK_ID"]) for row in b.read_rows("truck.csv")]
    item_price = {int(row["MENU_ITEM_ID"]): float(row["SALE_PRICE_USD"]) for row in b.read_rows("menu.csv")}
    item_ids = list(item_price)
    customer_ids = [int(row["CUSTOMER_ID"]) for row in b.read_rows("customer_loyalty.csv")]

    fh, wh = b.writer("order_header.csv", ("ORDER_ID,TRUCK_ID,LOCATION_ID,CUSTOMER_ID,DISCOUNT_ID,SHIFT_ID,"
                                           "SHIFT_START_TIME,SHIFT_END_TIME,ORDER_CHANNEL,ORDER_TS,SERVED_TS,"
                                           "ORDER_CURRENCY,ORDER_AMOUNT,ORDER_TAX_AMOUNT,ORDER_DISCOUNT_AMOUNT,"
                                           "ORDER_TOTAL"))
    fd, wd = b.writer("order_detail.csv", ("ORDER_DETAIL_ID,ORDER_ID,MENU_ITEM_ID,DISCOUNT_ID,LINE_NUMBER,QUANTITY,"
                                           "UNIT_PRICE,PRICE,ORDER_ITEM_DISCOUNT_AMOUNT"))
    with fh, fd:
        detail_id = b.ids["detail"]
        for o in range(1, b.n_orders + 1):
            order_id = b.ids["order"] + o
            location_id = b.pick(location_ids)
            customer_id = b.pick(customer_ids) if b.rng.random() < 0.4 else ""
            shift = 1 if b.rng.random() < 0.5 else 2
            hour = b.ri(8, 14) if shift == 1 else b.ri(15, 21)
            order_ts = f"{b.run_date} {hour:02d}:{b.ri(0, 59):02d}:{b.ri(0, 59):02d}"
            amount = 0.0
            for line in range(1, b.ri(1, 4) + 1):
                item_id, qty = b.pick(item_ids), b.ri(1, 3)
                unit_price = item_price[item_id]
                line_price = unit_price * qty
                amount += line_price
                detail_id += 1
                wd.writerow([detail_id, order_id, item_id, "", line, qty, c.f_money(unit_price), c.f_money(line_price), ""])
            start, end = ("08:00:00", "14:00:00") if shift == 1 else ("15:00:00", "22:00:00")
            wh.writerow([order_id, b.pick(truck_ids), location_id, customer_id, "", b.day * 10 + shift, start, end, "",
                         order_ts, "", location_currency[location_id], c.f_money(amount), "", "", c.f_money(amount)])
    b.summary("order_header.csv", "order_detail.csv")


if __name__ == "__main__":
    main()
