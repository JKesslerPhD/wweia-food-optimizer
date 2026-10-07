#!/usr/bin/env python3
"""
Adjust FoodAPS prices from 2013 survey dollars to current dollars
using BLS food-category-specific CPI series.

Fetches two ranges from the BLS public API (no key needed):
  2013-2022 for the base year values
  2016-2025 for the latest values
Computes category-specific multipliers and writes them to a
'price_inflation_multiplier' column in the foods table.

Run once, then re-run periodically to refresh multipliers.
"""
import json, sqlite3, os, urllib.request, urllib.error

DB = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'), 'wweia_full.db')
BLS_URL = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'

# BLS series IDs for food-at-home subcategories.
# Source: CPI Detailed Report, Table 1 (U.S. City Average, all urban consumers)
SERIES = {
    'CUUR0000SAF1':   'food_at_home',          # Food at home (fallback)
    'CUUR0000SAF11':  'cereals_bakery',         # Cereals and bakery products
    'CUUR0000SAF111': 'cereals',                # Cereals and cereal products
    'CUUR0000SAF113': 'meat_poultry_fish_eggs', # Meats, poultry, fish, eggs
    'CUUR0000SAF114': 'dairy',                  # Dairy and related products
    'CUUR0000SAF116': 'fruits_vegetables',      # Fruits and vegetables
    'CUUR0000SEFJ':   'other_food',             # Other food at home (incl. sugar, fats, nonalcoholic bev)
}

# Map our food_category values to the most appropriate BLS series.
# 'other_food' covers condiments, beverages, oils, sweets, snacks, etc.
CATEGORY_TO_SERIES = {
    'Cereals & Grains':  'cereals_bakery',
    'Bars & Snacks':     'cereals_bakery',
    'Sweets':            'other_food',
    'Meat & Poultry':    'meat_poultry_fish_eggs',
    'Seafood':           'meat_poultry_fish_eggs',
    'Dairy':             'dairy',
    'Cheese':            'dairy',
    'Eggs':              'meat_poultry_fish_eggs',
    'Fruits':            'fruits_vegetables',
    'Dried Fruit':       'fruits_vegetables',
    'Vegetables':        'fruits_vegetables',
    'Legumes':           'other_food',
    'Nuts & Seeds':      'other_food',
    'Nut Butters':       'other_food',
    'Oils & Fats':       'other_food',
    'Condiments':        'other_food',
    'Beverages':         'other_food',
    'Prepared Dish':     'food_at_home',
    'Other':             'food_at_home',
}


def fetch_series(series_ids, start_year, end_year):
    payload = json.dumps({
        'seriesid': series_ids,
        'startyear': str(start_year),
        'endyear': str(end_year),
    }).encode()
    req = urllib.request.Request(BLS_URL, data=payload,
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def annual_avg(series_data, year):
    """Average of monthly values for a given year, excluding missing '-' entries."""
    vals = [float(r['value']) for r in series_data
            if r['year'] == str(year) and r['period'].startswith('M') and r['value'] != '-']
    return sum(vals) / len(vals) if vals else None


def latest_value(series_data):
    """Most recent monthly value available."""
    monthly = [(r['year'] + r['period'], float(r['value']))
               for r in series_data
               if r['period'].startswith('M') and r['value'] != '-']
    if not monthly:
        return None, None
    k, v = max(monthly)
    return k, v


def compute_multipliers():
    series_ids = list(SERIES.keys())

    print("Fetching BLS data 2013-2022 (base period)...")
    d1 = fetch_series(series_ids, 2013, 2022)

    print("Fetching BLS data 2016-2025 (current period)...")
    d2 = fetch_series(series_ids, 2016, 2025)

    if d1.get('status') != 'REQUEST_SUCCEEDED':
        raise RuntimeError(f"BLS API error: {d1.get('message')}")
    if d2.get('status') != 'REQUEST_SUCCEEDED':
        raise RuntimeError(f"BLS API error: {d2.get('message')}")

    # Build lookup: series_id -> list of data records
    base_data = {s['seriesID']: s['data'] for s in d1['Results']['series']}
    curr_data = {s['seriesID']: s['data'] for s in d2['Results']['series']}

    multipliers = {}
    for sid, label in SERIES.items():
        base = annual_avg(base_data.get(sid, []), 2013)
        curr_k, curr_v = latest_value(curr_data.get(sid, []))
        if base and curr_v:
            mult = curr_v / base
            multipliers[label] = mult
            print(f"  {label:<30} 2013 avg={base:.1f}  latest={curr_k} {curr_v:.1f}  x{mult:.3f}")
        else:
            print(f"  {label:<30} MISSING DATA")

    return multipliers


def main():
    print("Computing food price inflation multipliers from BLS CPI...\n")
    multipliers = compute_multipliers()

    conn = sqlite3.connect(DB)
    try:
        conn.execute('ALTER TABLE foods ADD COLUMN price_inflation_multiplier REAL')
        print("\nAdded price_inflation_multiplier column")
    except Exception:
        print("\nColumn already exists, updating values")

    # Assign multiplier to each food based on its category
    fallback = multipliers.get('food_at_home', 1.45)
    updated = 0
    rows = conn.execute('SELECT food_code, food_category FROM foods').fetchall()
    for food_code, cat in rows:
        series_label = CATEGORY_TO_SERIES.get(cat or 'Other', 'food_at_home')
        mult = multipliers.get(series_label, fallback)
        conn.execute('UPDATE foods SET price_inflation_multiplier=? WHERE food_code=?',
                     (round(mult, 4), food_code))
        updated += 1

    conn.commit()
    conn.close()

    print(f"\nUpdated {updated} foods with category-specific inflation multipliers")
    print("\nMultiplier summary (2013 -> 2025):")
    for label, mult in sorted(multipliers.items()):
        print(f"  {label:<30} x{mult:.3f}  (+{(mult-1)*100:.1f}%)")


if __name__ == '__main__':
    main()
