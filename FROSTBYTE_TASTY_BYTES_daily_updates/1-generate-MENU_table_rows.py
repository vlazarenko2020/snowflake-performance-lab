#!/usr/bin/env python3
"""Generate the daily MENU rows (N_BRANDS brands x 4 items) -> DATA_DIR/<date>/menu.csv

Usage: ./1-generate-MENU_table_rows.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS] [--no-snowflake]
See tasty_common.py for the shared behaviour (arguments, IDs, repeatability).
"""
import tasty_common as c

ID_COLUMNS = [
    ("menu_id", "pos", "MENU", "MENU_ID"),
    ("menu_type_id", "pos", "MENU", "MENU_TYPE_ID"),
    ("menu_item", "pos", "MENU", "MENU_ITEM_ID"),
]


def main():
    b = c.f_start(__file__, "MENU", ["menu.csv"], ID_COLUMNS)
    if b is None:
        return
    f, w = b.writer("menu.csv", ("MENU_ID,MENU_TYPE_ID,MENU_TYPE,TRUCK_BRAND_NAME,MENU_ITEM_ID,MENU_ITEM_NAME,"
                                 "ITEM_CATEGORY,ITEM_SUBCATEGORY,COST_OF_GOODS_USD,SALE_PRICE_USD,"
                                 "MENU_ITEM_HEALTH_METRICS_OBJ"))
    n_menu = 0
    with f:
        for brand_no, brand in enumerate(c.BRANDS[:c.N_BRANDS], start=1):
            menu_type_id = b.ids["menu_type_id"] + brand_no
            for item_no in range(1, 5):
                n_menu += 1
                cost = 0.5 + b.rng.random() * 6
                sale = cost * (1.8 + b.rng.random() * 1.5)
                health = '{"is_healthy":"%s","calories":%d}' % ("Y" if b.rng.random() < 0.4 else "N", b.ri(150, 1200))
                w.writerow([b.ids["menu_id"] + n_menu, menu_type_id, f"Type {menu_type_id}", brand,
                            b.ids["menu_item"] + n_menu, f"{brand} Item {item_no}", c.CATEGORIES[item_no - 1],
                            b.pick(c.SUBCATEGORIES), c.f_money(cost), c.f_money(sale), health])
    b.summary("menu.csv")


if __name__ == "__main__":
    main()
