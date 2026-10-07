# Backpacking Food Optimizer

A web app that builds the lightest, cheapest, or most nutritious resupply basket that still hits a calorie target. It solves a linear program over about 3,000 real foods from US government survey data. Calorie density wins on weight: a basket that needs fewer grams for the same calories is lighter on your back.

Live version: <https://trailpeaches.com/food/>

## What it does

- **Browse** foods by calories per gram, protein, price or popularity, with filters for no-cook, shelf-stable, store type (grocery, convenience, rural, supercenter, dollar store) and diet (vegan, vegetarian, dairy-free, gluten-free, nut-free, shellfish-free, egg-free, soy-free).
- **Optimize** a basket for a number of days, calories per day and body weight. Pick the objective: minimum weight (maximum kcal per gram), minimum cost, maximum diversity, or maximum of any single nutrient.
- **Shop** from the result. Quantities round to real package sizes using typical package weights and prices from purchase data.

## How the optimizer works

Decision variables are grams of each candidate food. The solver is GLOP, the linear solver in [OR-Tools](https://developers.google.com/optimization).

| Piece | Rule |
|:-|:-|
| Calories | Total kcal within ±3% of `calories_per_day × days` |
| Nutrients | Minimums from the dietary reference intakes, scaled by a profile (`optimal`, `reduced`, `none`) and body weight. A few upper limits (for example alcohol) apply unless the profile is `none` |
| Feasibility guard | A nutrient minimum that no mix of candidate foods could come within 50% of is relaxed and reported, instead of making the problem infeasible |
| Per-food cap | Without a diversity setting, each food's mass is capped at roughly 40% of the calorie budget (assuming 3 kcal per gram). With one, each food is capped at `total kcal / minimum foods`, which forces a spread without binary variables |
| Category cap | With a diversity setting, no food category may supply more than `1 − 0.55 × diversity` of the calories |
| Perishability | For multi-day plans, a food must be non-perishable or survive unrefrigerated for the whole trip |
| Near-duplicates | Variants with the same base name and calorie density within 15% of each other are collapsed to the best-documented one |
| Optional | `candy_boost` (minimum share of calories from sweets), `max_item_grams`, per-food caps, blocked foods, a no-chocolate switch |

`POST /api/optimize` takes JSON, for example:

```bash
curl -s -X POST localhost:5000/api/optimize -H 'Content-Type: application/json' \
  -d '{"days":5,"calories_per_day":3000,"store":"grocery","diversity":0.3,
       "dietary_restrictions":["vegan"],"nutrition_profile":"optimal"}'
```

Other endpoints: `GET /api/foods` (search, filters, sort, paging), `GET /api/food/<code>`, `GET /api/dri`, `GET /api/stats`. `/methodology` is the plain-language write-up.

## Data

All of it is public US government data:

| Source | Used for |
|:-|:-|
| [NHANES / WWEIA dietary recall, 2021 to 2023](https://wwwn.cdc.gov/nchs/nhanes/) (CDC) | The food list, about 46 nutrient values per food, and how often each food is eaten |
| [WWEIA food categories and FNDDS](https://www.ars.usda.gov/northeast-area/beltsville-md-bhnrc/beltsville-human-nutrition-research-center/food-surveys-research-group/) (USDA ARS) | Food categories, the concordance behind the diet tags, and extra descriptions |
| [FoodAPS](https://www.ers.usda.gov/data-products/foodaps-national-household-food-acquisition-and-purchase-survey/) (USDA ERS, 2012 to 2013) | Real prices per 100 g, package sizes, and which store types sell what |
| [BLS CPI](https://www.bls.gov/cpi/) | Category-specific multipliers that bring 2013 prices to current dollars |
| `data/WWEIA_Days_Without_Refrigeration.csv` | Days each food category stays safe unrefrigerated (a conservative lower bound; see its `trail_notes` column) |

### `data/wweia_full.db`

The SQLite database the app reads (table `foods`, one row per food code, 93 columns). It is a snapshot of the production database, so the app runs exactly like the live site.

**Heads up on provenance.** The scripts in [`pipeline/`](pipeline/) rebuild the core of this database from the raw public files. Production then received several changes that are not in these scripts, so a fresh rebuild is close but not identical:

- three description columns (`faps_usda_description`, `faps_purchase_examples`, `fndds_additional`) exist only in the snapshot
- `non_perishable`, `faps_shelf_stable`, `no_cook` and `days_without_refrigeration` changed for roughly 230 to 1,650 rows each (outside these scripts)
- a few dozen vegan, vegetarian, egg-free and dairy-free flags were corrected

Treat the snapshot as the reference and the pipeline as the documentation of how most of it was made. See [`pipeline/README.md`](pipeline/README.md).

## Run it

```bash
pip install -r requirements.txt
python3 app.py            # http://localhost:5000
```

Set `PORT` to change the port, `WWEIA_DB` to point at another database, and `FLASK_DEBUG=1` for debug mode. In production run it under a WSGI server, for example `gunicorn -w 2 -b 127.0.0.1:8765 app:app`.

The web manifest and service worker assume the app is served under `/food/`. If you host it at another path, edit `static/manifest.json` and `static/sw.js`.

## Layout

| Path | What |
|:-|:-|
| `app.py` | Flask app and the optimizer |
| `templates/` | `index.html` (the app) and `methodology.html` |
| `static/` | PWA manifest, service worker, icons |
| `data/` | The database and the small reference files |
| `pipeline/` | Scripts that build the database from the raw public data |

## Limits

- Foods are what people reported eating, not a grocery catalog. Prices come from 2012 to 2013 purchases scaled by CPI, so treat them as ballpark.
- Perishability is by food category, not by product.
- The optimizer produces a mathematically valid basket, not a palatable one. Diversity and per-food caps help, and you still have to eat it.
- Nutrition numbers are a planning aid, not medical advice.

## AI and data disclosure

Generative AI was used to help write most of the code developed to create this front end tool. Data were assembled, cleaned, processed, and verified directly before incorporating them into this tool, and were not generated by an LLM. This tool works differently from LLM-generated text. Results and calculations displayed by this tool are directly calculated using hard-coded methods and a fixed, underlying data set. As such, these results are not subject to hallucination, and remain repeatable. Accuracy of displayed results depends on the reliability and accuracy of the underlying data and methods that are used.

The same text appears in a pop-up inside each tool.

## License

Code: MIT, see `LICENSE`. The data is from US government sources and is in the public domain.
