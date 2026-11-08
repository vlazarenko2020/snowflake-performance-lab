#!/usr/bin/env bash
# Generate a fictional daily batch of CSV files for the TASTY_BYTES tables.
# Usage: ./generate_tasty_bytes_data.sh [YYYY-MM-DD] [OUTPUT_DIR] [ORDERS]
#   e.g. ./generate_tasty_bytes_data.sh 2026-11-08 ./data 500
set -euo pipefail

RUN_DATE="${1:-$(date +%F)}"
OUT_DIR="${2:-./data}/${RUN_DATE}"
N_ORDERS="${3:-500}"

mkdir -p "$OUT_DIR"

# Day-based ID offset keeps IDs unique across daily runs
DAY_NUM=$(( $(date -d "$RUN_DATE" +%s) / 86400 ))
SEED=$DAY_NUM

awk -v out="$OUT_DIR" -v d="$RUN_DATE" -v day="$DAY_NUM" -v seed="$SEED" -v n_orders="$N_ORDERS" '
function pick(arr, n) { return arr[int(rand() * n) + 1] }
function ri(lo, hi)   { return lo + int(rand() * (hi - lo + 1)) }
function money(lo, hi){ return sprintf("%.4f", lo + rand() * (hi - lo)) }
function pad(n)       { return sprintf("%02d", n) }
function rdate(y1, y2){ return sprintf("%d-%s-%s", ri(y1, y2), pad(ri(1, 12)), pad(ri(1, 28))) }

BEGIN {
  srand(seed)
  split("Ava Liam Noah Emma Olivia Mia Lucas Sofia Ethan Chloe Mateo Yuki Amir Lena Raj", FN, " "); nFN = 15
  split("Smith Garcia Muller Rossi Tanaka Kim Novak Silva Dubois Patel Brown Jensen Lopez Cohen Ali", LN, " "); nLN = 15
  split("Seattle|Boston|Denver|Toronto|Vancouver|London|Paris|Berlin|Madrid|Tokyo|Sydney|Mumbai|Sao Paulo|Seoul|Cairo", CITY, "|"); nC = 15
  split("United States|United States|United States|Canada|Canada|England|France|Germany|Spain|Japan|Australia|India|Brazil|South Korea|Egypt", CTRY, "|")
  split("US|US|US|CA|CA|GB|FR|DE|ES|JP|AU|IN|BR|KR|EG", ISO, "|")
  split("USD|USD|USD|CAD|CAD|GBP|EUR|EUR|EUR|JPY|AUD|INR|BRL|KRW|EGP", CUR, "|")
  split("English|French|German|Spanish|Japanese", LANG, "|")
  split("Kitakata Ramen Bar|Freezing Point|Smoky BBQ|Guac n Roll|The Mega Melt|Tasty Tibs|Le Coin des Crepes|Better Off Bread|Plant Palace|Revenge of the Curds|Cheeky Greek|Peking Truck|Nani'"'"'s Kitchen|The Mac Shack|Not the Wurst Hot Dogs", BRAND, "|"); nB = 15
  split("Male|Female|Undisclosed", GEN, "|")
  split("Single|Married|Divorced|Undisclosed", MAR, "|")
  split("Main|Beverage|Dessert|Snack", CAT, "|")
  split("Hot Option|Cold Option|Warm Option", SUB, "|")
  split("Ford|Freightliner|Chevrolet|Nissan|Isuzu", MAKE, "|")
  split("Step Van|Box Truck|NV200|NPR|Utilimaster", MODEL, "|")

  base = day * 1000   # unique ID range per day

  # ---------- COUNTRY (one row per city) ----------
  f = out "/country.csv"
  print "COUNTRY_ID,COUNTRY,ISO_CURRENCY,ISO_COUNTRY,CITY_ID,CITY,CITY_POPULATION" > f
  for (i = 1; i <= nC; i++)
    printf "%d,%s,%s,%s,%d,%s,%d\n", i, CTRY[i], CUR[i], ISO[i], 100 + i, CITY[i], ri(500000, 12000000) > f
  close(f)

  # ---------- FRANCHISE ----------
  nFr = 20
  f = out "/franchise.csv"
  print "FRANCHISE_ID,FIRST_NAME,LAST_NAME,CITY,COUNTRY,E_MAIL,PHONE_NUMBER" > f
  for (i = 1; i <= nFr; i++) {
    c = ri(1, nC); fn = pick(FN, nFN); ln = pick(LN, nLN)
    printf "%d,%s,%s,%s,%s,%s.%s@example.com,%03d-%03d-%04d\n", i, fn, ln, CITY[c], CTRY[c], tolower(fn), tolower(ln), ri(200,999), ri(100,999), ri(0,9999) > f
  }
  close(f)

  # ---------- LOCATION ----------
  nLoc = 60
  f = out "/location.csv"
  print "LOCATION_ID,PLACEKEY,LOCATION,CITY,REGION,ISO_COUNTRY_CODE,COUNTRY" > f
  for (i = 1; i <= nLoc; i++) {
    c = ri(1, nC); locCity[i] = c
    printf "%d,zz%04d@abc-def-ghi,\"%s Square %d\",%s,%s,%s,%s\n", i, i, CITY[c], i, CITY[c], CITY[c], ISO[c], CTRY[c] > f
  }
  close(f)

  # ---------- TRUCK ----------
  nTr = 45
  f = out "/truck.csv"
  print "TRUCK_ID,FRANCHISE_ID,PRIMARY_CITY,REGION,ISO_REGION,COUNTRY,ISO_COUNTRY_CODE,FRANCHISE_FLAG,YEAR,MAKE,MODEL,EV_FLAG,TRUCK_OPENING_DATE,TRUCK_START_DATE" > f
  for (i = 1; i <= nTr; i++) {
    c = ri(1, nC); m = ri(1, 5)
    printf "%d,%d,%s,%s,%s,%s,%s,%d,%d,%s,%s,%d,%d,%s\n", i, ri(1, nFr), CITY[c], CITY[c], ISO[c], CTRY[c], ISO[c], (rand() < 0.3), ri(2005, 2025), MAKE[m], MODEL[m], (rand() < 0.2), ri(2015, 2025), rdate(2015, 2025) > f
  }
  close(f)

  # ---------- MENU ----------
  nMenu = 0
  f = out "/menu.csv"
  print "MENU_ID,MENU_TYPE_ID,MENU_TYPE,TRUCK_BRAND_NAME,MENU_ITEM_ID,MENU_ITEM_NAME,ITEM_CATEGORY,ITEM_SUBCATEGORY,COST_OF_GOODS_USD,SALE_PRICE_USD,MENU_ITEM_HEALTH_METRICS_OBJ" > f
  for (b = 1; b <= nB; b++) {
    for (k = 1; k <= 4; k++) {
      nMenu++
      cost = 0.5 + rand() * 6; sale = cost * (1.8 + rand() * 1.5)
      price[nMenu] = sale
      printf "%d,%d,Type %d,\"%s\",%d,\"%s Item %d\",%s,%s,%.4f,%.4f,\"{\"\"is_healthy\"\":\"\"%s\"\",\"\"calories\"\":%d}\"\n", 10000 + nMenu, b, b, BRAND[b], nMenu, BRAND[b], k, CAT[k], pick(SUB, 3), cost, sale, (rand() < 0.4 ? "Y" : "N"), ri(150, 1200) > f
    }
  }
  close(f)

  # ---------- CUSTOMER_LOYALTY (new sign-ups for the day) ----------
  nCust = int(n_orders / 10) + 1
  f = out "/customer_loyalty.csv"
  print "CUSTOMER_ID,FIRST_NAME,LAST_NAME,CITY,COUNTRY,POSTAL_CODE,PREFERRED_LANGUAGE,GENDER,FAVOURITE_BRAND,MARITAL_STATUS,CHILDREN_COUNT,SIGN_UP_DATE,BIRTHDAY,E_MAIL,PHONE_NUMBER" > f
  for (i = 1; i <= nCust; i++) {
    id = base + i; cust[i] = id
    c = ri(1, nC); fn = pick(FN, nFN); ln = pick(LN, nLN)
    printf "%d,%s,%s,%s,%s,%05d,%s,%s,\"%s\",%s,%s,%s,%s,%s.%s%d@example.com,%03d-%03d-%04d\n", id, fn, ln, CITY[c], CTRY[c], ri(10000, 99999), pick(LANG, 5), pick(GEN, 3), pick(BRAND, nB), pick(MAR, 4), ri(0, 4), d, rdate(1955, 2005), tolower(fn), tolower(ln), id, ri(200,999), ri(100,999), ri(0,9999) > f
  }
  close(f)

  # ---------- ORDER_HEADER + ORDER_DETAIL ----------
  fh = out "/order_header.csv"; fd = out "/order_detail.csv"
  print "ORDER_ID,TRUCK_ID,LOCATION_ID,CUSTOMER_ID,DISCOUNT_ID,SHIFT_ID,SHIFT_START_TIME,SHIFT_END_TIME,ORDER_CHANNEL,ORDER_TS,SERVED_TS,ORDER_CURRENCY,ORDER_AMOUNT,ORDER_TAX_AMOUNT,ORDER_DISCOUNT_AMOUNT,ORDER_TOTAL" > fh
  print "ORDER_DETAIL_ID,ORDER_ID,MENU_ITEM_ID,DISCOUNT_ID,LINE_NUMBER,QUANTITY,UNIT_PRICE,PRICE,ORDER_ITEM_DISCOUNT_AMOUNT" > fd
  detail_id = base * 10
  for (o = 1; o <= n_orders; o++) {
    oid = base + o; loc = ri(1, nLoc)
    custId = (rand() < 0.4) ? cust[ri(1, nCust)] : ""
    shift = (rand() < 0.5) ? 1 : 2
    hh = (shift == 1) ? ri(8, 14) : ri(15, 21)
    ts = sprintf("%s %s:%s:%s", d, pad(hh), pad(ri(0, 59)), pad(ri(0, 59)))
    lines = ri(1, 4); amt = 0
    for (l = 1; l <= lines; l++) {
      mi = ri(1, nMenu); q = ri(1, 3); up = price[mi]; p = up * q; amt += p
      printf "%d,%d,%d,,%d,%d,%.4f,%.4f,\n", ++detail_id, oid, mi, l, q, up, p > fd
    }
    printf "%d,%d,%d,%s,,%d,%s,%s,,%s,,%s,%.4f,,,%.4f\n", oid, ri(1, nTr), loc, custId, day * 10 + shift, (shift == 1 ? "08:00:00" : "15:00:00"), (shift == 1 ? "14:00:00" : "22:00:00"), ts, CUR[locCity[loc]], amt, amt > fh
  }
  close(fh); close(fd)
}'

echo "Generated files in $OUT_DIR:"
wc -l "$OUT_DIR"/*.csv
