
Bash script that generates a fictional daily batch of CSV files, one per table, matching the column layout from the Terraform file.

Sript name: `generate_tasty_bytes_data.sh`. 
A test run made one CSV per table (8 in total), each with a header row and the same column order as your Terraform table definitions.

**Usage:**
```bash
./generate_tasty_bytes_data.sh [YYYY-MM-DD] [OUTPUT_DIR] [NUM_ORDERS]
./generate_tasty_bytes_data.sh 2026-11-08 ./data 500   # -> ./data/2026-11-08/*.csv
```

**How the daily data works:**
- **New rows each day:** `ORDER_HEADER`, `ORDER_DETAIL` and `CUSTOMER_LOYALTY` get new IDs taken from a range based on the date, so loading several days won't create duplicate keys.
- **Lookup tables stay the same:** `COUNTRY`, `FRANCHISE`, `LOCATION`, `TRUCK` and `MENU` keep the same IDs every day, and their values are regenerated each run. Treat them as updates to existing rows (MERGE) rather than inserts.
- **Repeatable:** the random values come from the date, so running the same date twice gives identical files.
- **Links between tables:** orders point to existing trucks, locations, menu items and that day's new customers.
- **Fake names:** all names, emails and phone numbers are made up.
- **Empty columns:** `ORDER_CHANNEL`, `DISCOUNT_ID`, `SERVED_TS` and the tax/discount amount columns are left empty.

**Loading the files:** Database to load: "FROSTBYTE_TASTY_BYTES_2".  An internal stage is needed, which this sketch creates:
```sql
CREATE STAGE IF NOT EXISTS FROSTBYTE_TASTY_BYTES_2.RAW_POS.DAILY_LOAD;
-- PUT file://./data/2026-11-08/*.csv @FROSTBYTE_TASTY_BYTES_2.RAW_POS.DAILY_LOAD/2026-11-08/;

COPY INTO FROSTBYTE_TASTY_BYTES_2.RAW_POS.ORDER_HEADER
  FROM @FROSTBYTE_TASTY_BYTES_2.RAW_POS.DAILY_LOAD/2026-11-08/order_header.csv
  FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' EMPTY_FIELD_AS_NULL = TRUE);
```

Use the same `COPY INTO` for each table.

