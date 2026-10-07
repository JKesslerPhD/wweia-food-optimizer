# Building the database

These scripts turn the raw public files into `data/wweia_full.db`. Run them from anywhere; they read and write `../data/`.

```bash
pip install -r ../requirements-pipeline.txt
```

## 1. Download the raw inputs into `data/`

| File | Where from |
|:-|:-|
| `DR1IFF_L.xpt`, `DR2IFF_L.xpt`, `drxfcd_L.xpt` | CDC NHANES 2021 to 2023 dietary data: `https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DR1IFF_L.xpt` (and `DR2IFF_L.xpt`, `DRXFCD_L.xpt`). Save `DRXFCD_L.xpt` as `drxfcd_L.xpt` |
| `faps_household_puf.csv`, `faps_fahitem_puf.csv`, `faps_fahnutrients.csv` | USDA ERS FoodAPS public-use files (the `foodaps.zip` download on the [FoodAPS page](https://www.ers.usda.gov/data-products/foodaps-national-household-food-acquisition-and-purchase-survey/)) |

`WWEIA_August2021_August2023_foodcat_FNDDS.xlsx` and `WWEIA_Days_Without_Refrigeration.csv` are already in `data/`. The raw files are large, so they are git-ignored.

## 2. Run, in this order

| Step | Script | What it does |
|:-|:-|:-|
| 1 | `build_full_db.py` | Reads the dietary recall files, averages nutrients per food code, derives calorie density and keyword-based no-cook and non-perishable flags, and creates the `foods` table |
| 2 | `integrate_foodaps.py` | Adds FoodAPS descriptions, price per 100 g (median, rural, convenience, supercenter), store-type and rural flags, and shelf-stable hints |
| 3 | `build_package_data.py` | Adds typical package weight, price and label per food |
| 4 | `integrate_perishability.py` | Adds days without refrigeration and a stability tier from the category concordance |
| 5 | `fix_categories.py` | Re-derives food category, package units and the prepared-dish flag from the WWEIA categories instead of keywords |
| 6 | `retag_availability.py` | Tags convenience-store and grocery availability |
| 7 | `add_dietary_tags.py` | Adds the `is_vegan` ... `is_soy_free` columns |
| 8 | `inflate_prices.py` | Fetches BLS CPI (no key needed) and writes a category price multiplier |

Step 8 needs network access to the BLS API.

## What a rebuild does not include

Production's database was edited after this pipeline ran. See "Heads up on provenance" in the [top-level README](../README.md). In short: a rebuild lacks three description columns and has different shelf-stable, no-cook and perishability values for some foods. The committed snapshot is the reference.
