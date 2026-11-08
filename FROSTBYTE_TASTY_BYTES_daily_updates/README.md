# FROSTBYTE_TASTY_BYTES daily updates

Generators for a fictional **daily batch of CSV files** for the Tasty Bytes tables (`FROSTBYTE_TASTY_BYTES_2.RAW_POS`). Each run produces one CSV per table, with a header row and the column order of the Terraform table definitions. You can then load the files into Snowflake to simulate data arriving every day.

## Quick start: generate and load in one command

```bash
./0-generate_plus_load.sh 2026-11-08
```

`0-generate_plus_load.sh YYYY-MM-DD` runs step 1 (`1-generate_tasty_bytes_data.py`) and then step 2 (`2-load_tasty_bytes_data.py`) with the same date, using their defaults (`./data`, 500 orders). The date is mandatory: with no date, a malformed or impossible date, or extra arguments, it explains what is needed and exits with code 2. It stops if the generator fails, so the loader never runs on missing files. Loading needs `CONNECTION` (see [Running with uv and loading with Snowpark](#running-with-uv-and-loading-with-snowpark)).

| Step | Script |
|------|--------|
| 0 | `0-generate_plus_load.sh`: runs 1 and then 2 |
| 1 | `1-generate_tasty_bytes_data.py`: writes the CSV files |
| 2 | `2-load_tasty_bytes_data.py`: loads them into Snowflake |

## Generators

There are two generator scripts that do the same job:

| Script | Needs | Date argument |
|--------|-------|---------------|
| `1-generate_tasty_bytes_data.py` | Python 3.7+ (standard library only) | **mandatory** |
| `generate_tasty_bytes_data.sh` | bash, `awk`, GNU `date` (Linux) | optional (defaults to today) |

Use the Python script unless you have a reason not to: it runs anywhere Python does, and it explains a missing date instead of silently using today. All data is made up (names, emails, phone numbers).

### Usage

```bash
./1-generate_tasty_bytes_data.py YYYY-MM-DD [OUTPUT_DIR] [ORDERS]
./1-generate_tasty_bytes_data.py 2026-11-08 ./data 500      # -> ./data/2026-11-08/*.csv

bash ./generate_tasty_bytes_data.sh [YYYY-MM-DD] [OUTPUT_DIR] [ORDERS]
bash ./generate_tasty_bytes_data.sh 2026-11-08 ./data 500
```

| Argument | Meaning | Default |
|----------|---------|---------|
| `YYYY-MM-DD` | The day to generate data for. It sets the folder name, the ID range and the random seed | Python: none, **required**. Shell: today |
| `OUTPUT_DIR` | Base output directory. Files go to `OUTPUT_DIR/<date>/` | `./data` |
| `ORDERS` | Number of orders to generate | `500` |

The `.sh` file is not marked executable, so run it with `bash` (or `chmod +x` it).

**Python script messages**
- With no date, it prints why the date is needed, the usage line and an example, then exits with code 2.
- With the date only, it prints the defaults it is using, for example `OUTPUT_DIR not provided: the files will be created in the folder /abs/path/data/2026-11-08`, and `ORDERS not provided: generating the default 500 orders`.
- At the end both scripts print the files created, with line counts.

## What gets generated

For `ORDERS = 500`, the row counts (excluding the header) are:

| File | Rows | Kind |
|------|------|------|
| `country.csv` | 15 (one per city) | Lookup |
| `franchise.csv` | 20 | Lookup |
| `location.csv` | 60 | Lookup |
| `truck.csv` | 45 | Lookup |
| `menu.csv` | 60 (15 brands × 4 items) | Lookup |
| `customer_loyalty.csv` | `ORDERS / 10 + 1` (51) | New each day |
| `order_header.csv` | `ORDERS` (500) | New each day |
| `order_detail.csv` | 1-4 lines per order (about 1,250) | New each day |

**Records per run (default `ORDERS = 500`):** about **1,800 data rows** in total, excluding headers.
- The five lookup files are fixed at 200 rows (15 + 20 + 60 + 45 + 60), whatever `ORDERS` is.
- The three daily files scale with `ORDERS`: `customer_loyalty` (`ORDERS / 10 + 1`), `order_header` (`ORDERS`) and `order_detail` (1-4 lines per order, so about `2.5 × ORDERS`). At 500 orders that is 51 + 500 + about 1,250 = about 1,800 rows.
- The exact `order_detail` count varies with the date, because each order gets a random number of lines. The same date and `ORDERS` always give the same count.
- Change the volume with the `ORDERS` argument of `1-generate_tasty_bytes_data.py`. `0-generate_plus_load.sh` always uses the default of 500.

How the data behaves:
- **New rows each day:** order headers, order details and customers get IDs from a range based on the date (`day number × 1000`), so loading several days never creates duplicate keys.
- **Lookup tables repeat:** `COUNTRY`, `FRANCHISE`, `LOCATION`, `TRUCK` and `MENU` keep the same IDs every day and their values are regenerated each run. Load them with `MERGE`, not plain inserts.
- **Linked tables:** orders point to existing trucks, locations and menu items, and about 40% of them to that day's new customers.
- **Repeatable:** the random values are seeded from the date, so running the same date twice gives identical files.
- **Empty columns:** `ORDER_CHANNEL`, `DISCOUNT_ID`, `SERVED_TS` and the tax and discount amounts are left empty.

## Running the same date again

The scripts write into `OUTPUT_DIR/<date>/` and overwrite the files that are already there. With the same date and the same `ORDERS` the new files are identical. With a different `ORDERS` the content changes. A different date creates a new folder and leaves earlier days alone. Nothing is ever deleted.

If you have already loaded that day into Snowflake, loading it again inserts duplicates. `COPY INTO` skips files it has already loaded unless you re-`PUT` them with `OVERWRITE = TRUE` or load with `FORCE = TRUE`.

## Differences between the two scripts

- **Values:** the two scripts produce the same tables, columns, row counts and ID scheme, but not the same values. awk and Python use different random number generators. Each script is repeatable on its own.
- **Quoting:** the shell script always quotes brand, location and the health JSON column. The Python script (`csv` module) quotes a field only when it has to. Both load the same with `FIELD_OPTIONALLY_ENCLOSED_BY = '"'`.
- **Day number:** the shell script gets it from `date -d`, which uses your local timezone. The Python script counts days since 1970-01-01 in UTC. In a timezone ahead of UTC they could differ by one day, which shifts the ID range. Pick one script and stay with it for a given set of days.

## Running with uv and loading with Snowpark

This folder is a [uv](https://docs.astral.sh/uv/) project (`pyproject.toml`, `uv.lock`, Python 3.12 in `.python-version`). Dependencies: `snowflake-snowpark-python` and `python-dotenv`. The generator itself needs neither.

```bash
cd FROSTBYTE_TASTY_BYTES_daily_updates
uv sync                                               # creates .venv and installs dependencies
uv run 1-generate_tasty_bytes_data.py 2026-11-08        # 1. generate ./data/2026-11-08/*.csv
uv run 2-load_tasty_bytes_data.py 2026-11-08 --dry-run  # 2. preview the PUT/COPY/MERGE statements (no connection)
uv run 2-load_tasty_bytes_data.py 2026-11-08            # 3. load into Snowflake
```

`2-load_tasty_bytes_data.py YYYY-MM-DD [DATA_DIR] [--force] [--dry-run]` connects with Snowpark, creates the stage, PUTs the day's CSVs and loads them:
- **Lookup tables** (`country`, `franchise`, `location`, `truck`, `menu`): `COPY` into a temporary table, then `MERGE` on `CITY_ID`, `FRANCHISE_ID`, `LOCATION_ID`, `TRUCK_ID` and `MENU_ITEM_ID`. Re-running a day updates rows and creates no duplicates.
- **Fact tables** (`customer_loyalty`, `order_header`, `order_detail`): plain `COPY INTO`. Snowflake skips files it has already loaded, so a re-run does not duplicate rows; `--force` overrides that.
- Columns are matched by the CSV header names, so the target tables must already exist with those column names. The date is mandatory, as in the generator.

Settings come from the environment or the repo's git-ignored `.env` (one level up), like the performance-lab scripts: `CONNECTION` (required, a connection name from `~/.snowflake/config.toml`) and optional `TASTY_DB` (default `FROSTBYTE_TASTY_BYTES_2`), `TASTY_SCHEMA` (`RAW_POS`), `TASTY_CUSTOMER_SCHEMA` (`RAW_CUSTOMER`) and `TASTY_STAGE` (`DAILY_LOAD`). Only the connection **name** is read: the account, user, authentication, **role and warehouse** all come from that connection in `config.toml` (`ROLE` and `WAREHOUSE` in `.env` are ignored by this script). Make sure the connection's role has the needed privileges (`CREATE STAGE`, `CREATE TABLE`, `INSERT`/`UPDATE` on the Tasty Bytes tables).

## Loading by hand (SQL)

An internal stage is needed. Run this in the `FROSTBYTE_TASTY_BYTES_2` database:

```sql
CREATE STAGE IF NOT EXISTS FROSTBYTE_TASTY_BYTES_2.RAW_POS.DAILY_LOAD;
-- PUT file://./data/2026-11-08/*.csv @FROSTBYTE_TASTY_BYTES_2.RAW_POS.DAILY_LOAD/2026-11-08/;

COPY INTO FROSTBYTE_TASTY_BYTES_2.RAW_POS.ORDER_HEADER
  FROM @FROSTBYTE_TASTY_BYTES_2.RAW_POS.DAILY_LOAD/2026-11-08/order_header.csv
  FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' EMPTY_FIELD_AS_NULL = TRUE);
```

Use the same `COPY INTO` for each table.

## Known limitation

`TRUCK_OPENING_DATE` in `truck.csv` is filled with a bare year (for example `2019`), not a full date. If the target column is a `DATE`, loading `truck.csv` will fail on that column. Both scripts behave this way.

See also `generate_tasty_bytes_data.md`, the original notes for the shell script.
