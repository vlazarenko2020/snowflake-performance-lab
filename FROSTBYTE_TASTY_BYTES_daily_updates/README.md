# FROSTBYTE_TASTY_BYTES daily updates

Generators for a fictional **daily batch of CSV files** for the Tasty Bytes tables (`FROSTBYTE_TASTY_BYTES_2.RAW_POS`). Each run produces one CSV per table, with a header row and the column order of the Terraform table definitions. You can then load the files into Snowflake to simulate data arriving every day.

## Quick start: generate and load in one command

```bash
./0-generate_plus_load.sh 2026-11-08
```

`0-generate_plus_load.sh YYYY-MM-DD` runs step 1 (`1-generate_tasty_bytes_data.py`) and then step 2 (`2-load_tasty_bytes_data.py`) with the same date, using their defaults (`./data`, 500 orders). The date is mandatory: with no date, a malformed or impossible date, or extra arguments, it explains what is needed and exits with code 2. It stops if the generator fails, so the loader never runs on missing files. Loading needs `CONNECTION` (see [Running with uv and loading with Snowpark](#running-with-uv-and-loading-with-snowpark)). It is safe to run twice for the same date: the generator and the loader each detect work that is already done and skip it (see [Running the same date again](#running-the-same-date-again)).

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

The Python generator needs a Snowflake connection (it reads `MAX(id)`), so run it with `uv run`; `0-generate_plus_load.sh` already does. Use the Python script unless you have a reason not to: it runs anywhere Python does, and it explains a missing date instead of silently using today. All data is made up (names, emails, phone numbers).

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

Only the order tables are big. Everything else is deliberately kept to a few rows per daily batch (the sizes are the `N_*` constants near the top of `1-generate_tasty_bytes_data.py`). For `ORDERS = 500`, the row counts (excluding the header) are:

| File | Rows | Kind |
|------|------|------|
| `country.csv` | 3 (one per city, `N_CITIES`) | Lookup |
| `franchise.csv` | 3 (`N_FRANCHISES`) | Lookup |
| `location.csv` | 5 (`N_LOCATIONS`) | Lookup |
| `truck.csv` | 4 (`N_TRUCKS`) | Lookup |
| `menu.csv` | 12 (3 brands x 4 items, `N_BRANDS`) | Lookup |
| `customer_loyalty.csv` | 5 (`N_CUSTOMERS`) | New each day |
| `order_header.csv` | `ORDERS` (500) | New each day |
| `order_detail.csv` | 1-4 lines per order (about 1,250) | New each day |

**Records per run (default `ORDERS = 500`):** about **1,780 data rows** in total, excluding headers.
- The five lookup files and `customer_loyalty` are fixed at 32 rows (3 + 3 + 5 + 4 + 12 + 5), whatever `ORDERS` is.
- The two order files scale with `ORDERS`: `order_header` (`ORDERS`) and `order_detail` (1-4 lines per order, so about `2.5 x ORDERS`).
- The exact `order_detail` count varies with the date, because each order gets a random number of lines. The same date and `ORDERS` always give the same count.
- Change the volume with the `ORDERS` argument of `1-generate_tasty_bytes_data.py`. `0-generate_plus_load.sh` always uses the default of 500.
- Names come from pools of about 75 first names and 90 last names (plain ASCII, because they are used in the e-mail addresses).

How the data behaves:
- **New IDs for every table, bigger than the current maximum:** before generating, the Python script reads `MAX(id)` of each table from Snowflake (`COUNTRY_ID`, `CITY_ID`, `FRANCHISE_ID`, `LOCATION_ID`, `TRUCK_ID`, `MENU_ID`, `MENU_TYPE_ID`, `MENU_ITEM_ID`, `CUSTOMER_ID`, `ORDER_ID`, `ORDER_DETAIL_ID`) and numbers the new rows `MAX+1, MAX+2, ...`. So a daily batch never reuses an ID that is already loaded (including historical rows) and never overwrites existing rows. This needs `CONNECTION` (same settings as the loader) and the tables to exist; `--no-snowflake` skips the lookup and numbers from 1 (offline testing only).
- **Lookup tables grow by a few rows a day:** `COUNTRY`, `FRANCHISE`, `LOCATION`, `TRUCK` and `MENU` get new IDs too, so each batch adds a few new rows. The loader still MERGEs them (which now simply inserts).
- **Linked tables:** trucks point to the batch's franchises, and orders point to the trucks, locations and menu items of the same batch, and about 40% of them to that day's new customers. Because the lookup sets are small, orders use only 3 cities, 5 locations, 4 trucks and 12 menu items.
- **Repeatable:** the random values are seeded from the date, so running the same date twice gives identical files.
- **Empty columns:** `ORDER_CHANNEL`, `DISCOUNT_ID`, `SERVED_TS` and the tax and discount amounts are left empty.

## Running the same date again

Both Python scripts detect work that is already done, so `0-generate_plus_load.sh <date>` can be run repeatedly.

**Generator (`f_already_generated`).** If `OUTPUT_DIR/<date>/` already holds all 8 CSV files (none empty), it prints `Data for <date> has already been generated ... nothing to do` and exits without rewriting anything. A folder with only some of the files counts as not generated and is rebuilt. There is no `--force`: to regenerate a day, delete its folder. (The old `.sh` generator has no such check and overwrites the files.)

**Loader (`f_loaded_fact_files`).** Before uploading anything it asks Snowflake's `<db>.INFORMATION_SCHEMA.COPY_HISTORY` which fact files of that date are already loaded, and prints one `check>` line per fact table:
- All three fact files loaded: it prints `Data for <date> has already been loaded ... nothing to do` and exits (no PUT, no COPY).
- Only some loaded: those files are skipped (`SKIP <file>: already loaded`, no PUT, no COPY) and only the missing ones are loaded.
- `--force` ignores the history and loads everything again (this creates duplicates if the data is there).
- The lookup tables are always re-MERGEd, which is harmless.

Things to know about this check:
- `COPY_HISTORY` only goes back 14 days. For an older date the loader prints a note and cannot tell, so it loads.
- The history is kept per table: truncating or recreating a table erases it, and the loader will then load that day again. If you delete rows by hand and want them back, reload with `--force`.
- The history lists the file as `<date>/<table>.csv` (no stage name in front); the check matches on that.
- Do not rely on `COPY INTO` alone to skip files: the loader re-`PUT`s the files with `OVERWRITE = TRUE`, and Snowflake then loads them again. That is how a day got loaded twice before this check existed.

The IDs depend on what is in Snowflake when the files are generated. If you delete a day's folder and generate it again after it was loaded, you get the same values under new, bigger IDs: loading that would add the day a second time. Delete the day's rows from Snowflake first.

To check a day for duplicates, compare `COUNT(*)` with `COUNT(DISTINCT id)` over the day's ID range (the IDs of that batch are the CSV's ID column: take its min and max).

## Differences between the two scripts

- **Sizes:** only the Python script has the reduced lookup sizes, the larger name pools and the "already generated" check. The `.sh` script still generates the original, larger lookup sets (15 cities, 20 franchises, 60 locations, 45 trucks, 60 menu items, `ORDERS / 10 + 1` customers).
- **Values:** the two scripts produce the same tables, columns and ID scheme, but not the same values. awk and Python use different random number generators. Each script is repeatable on its own.
- **Quoting:** the shell script always quotes brand, location and the health JSON column. The Python script (`csv` module) quotes a field only when it has to. Both load the same with `FIELD_OPTIONALLY_ENCLOSED_BY = '"'`.
- **Day number:** the shell script gets it from `date -d`, which uses your local timezone. The Python script counts days since 1970-01-01 in UTC. In a timezone ahead of UTC they could differ by one day, which shifts the ID range. Pick one script and stay with it for a given set of days.

## Running with uv and loading with Snowpark

This folder is a [uv](https://docs.astral.sh/uv/) project (`pyproject.toml`, `uv.lock`, Python 3.12 in `.python-version`). Dependencies: `snowflake-snowpark-python` and `python-dotenv`. The generator itself needs neither. In the Python scripts the helper functions are prefixed `f_` (for example `f_pick`, `f_writer`), except `main`.

```bash
cd FROSTBYTE_TASTY_BYTES_daily_updates
uv sync                                               # creates .venv and installs dependencies
uv run 1-generate_tasty_bytes_data.py 2026-11-08        # 1. generate ./data/2026-11-08/*.csv
uv run 2-load_tasty_bytes_data.py 2026-11-08 --dry-run  # 2. preview the PUT/COPY/MERGE statements (no connection)
uv run 2-load_tasty_bytes_data.py 2026-11-08            # 3. load into Snowflake
```

`2-load_tasty_bytes_data.py YYYY-MM-DD [DATA_DIR] [--force] [--dry-run]` connects with Snowpark, creates the stage, PUTs the day's CSVs and loads them:
- **Lookup tables** (`country`, `franchise`, `location`, `truck`, `menu`): `COPY` into a temporary table, then `MERGE` on `CITY_ID`, `FRANCHISE_ID`, `LOCATION_ID`, `TRUCK_ID` and `MENU_ITEM_ID`. Re-running a day updates rows and creates no duplicates.
- **Fact tables** (`customer_loyalty`, `order_header`, `order_detail`): plain `COPY INTO`. Files that `COPY_HISTORY` shows as already loaded are skipped before the upload, so a re-run does not duplicate rows; `--force` overrides that (see [Running the same date again](#running-the-same-date-again)).
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
