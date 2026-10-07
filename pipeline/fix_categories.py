#!/usr/bin/env python3
"""
Fix food_category, pkg_unit_singular, is_prepared_dish, and perishability
using the WWEIA concordance (category_number) rather than keyword-matching on
food description.

Also marks prepared/mixed dishes as not purchasable items (no_cook=0, is_prepared=1).
Also fixes soft cheese perishability (goat, ricotta, cottage, brie, etc.).
"""
import re, sqlite3, os
import openpyxl

BASE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(BASE, 'wweia_full.db')
XLSX    = os.path.join(BASE, 'WWEIA_August2021_August2023_foodcat_FNDDS.xlsx')
CSV     = os.path.join(BASE, 'WWEIA_Days_Without_Refrigeration.csv')

# ---------------------------------------------------------------------------
# WWEIA category_number → display category
# Based on the actual WWEIA food category structure (4-digit codes)
# ---------------------------------------------------------------------------
def wweia_category_to_display(cat_num, cat_desc):
    """Map WWEIA 4-digit category number to a display category name.
    Based on the actual WWEIA food category list from the concordance."""
    if cat_num is None:
        return None
    n = int(cat_num)

    # Dairy (1000–1999)
    if 1000 <= n < 2000:
        if n in (1602,):             return 'Cheese'
        if n in (1604,):             return 'Dairy'   # cottage/ricotta
        return 'Dairy'

    # Meat, Poultry, Seafood, Eggs, Legumes, Nuts (2000–2999)
    if 2000 <= n < 3000:
        if n in (2402, 2404):        return 'Seafood'
        if n in (2502,):             return 'Dairy'    # eggs
        if n in (2602, 2604, 2606, 2608):  return 'Meat & Poultry'  # cold cuts, sausage
        if n in (2802,):             return 'Legumes'
        if n in (2804,):             return 'Nuts & Seeds'
        if n in (2806,):             return 'Legumes'  # soy/meat alternatives
        if 2200 <= n < 2400:         return 'Meat & Poultry'  # chicken, turkey
        return 'Meat & Poultry'

    # Mixed dishes / prepared foods (3000–3999) — dishes, not purchasable items
    if 3000 <= n < 4000:             return 'Prepared Dish'

    # Grains and breads (4000–4999)
    if 4000 <= n < 5000:
        if n in (4602, 4604):        return 'Cereals & Grains'  # RTE cereal
        if n in (4802, 4804):        return 'Cereals & Grains'  # oatmeal, grits
        return 'Cereals & Grains'

    # Snacks, sweets, chips (5000–5999)
    if 5000 <= n < 6000:
        if n in (5002, 5004, 5006, 5008):   return 'Bars & Snacks'  # chips, popcorn, pretzels
        if n in (5202, 5204):               return 'Bars & Snacks'  # crackers
        if n in (5402, 5404):               return 'Bars & Snacks'  # cereal/nutrition bars
        return 'Sweets'   # cakes, cookies, candy, ice cream

    # Fruits (6000–6999)
    if 6000 <= n < 7000:
        if n in (6016,):             return 'Dried Fruit'
        if n in (6402, 6404, 6406, 6407, 6409, 6410, 6411,
                 6412, 6413, 6414, 6416, 6418, 6420, 6430,
                 6432, 6489, 6802, 6804, 6806):
                                     return 'Vegetables'
        return 'Fruits'

    # Beverages (7000–7999)
    if 7000 <= n < 8000:             return 'Beverages'

    # Fats, condiments, sugars (8000–8999)
    if 8000 <= n < 9000:
        if n in (8002, 8004):        return 'Oils & Fats'
        if n in (8006, 8008):        return 'Dairy'    # cream, sour cream
        if n in (8010, 8012):        return 'Condiments'
        if 8400 <= n < 8500:         return 'Condiments'
        if n in (8802, 8804, 8806):  return 'Condiments'  # sugars, syrups
        return 'Condiments'

    # Baby food and formula (9000–9999)
    if 9000 <= n < 10000:            return 'Other'

    # Protein powders etc (9802)
    if n == 9802:                    return 'Bars & Snacks'

    if n == 9999:                    return 'Other'

    return 'Other'


def is_prepared_dish(cat_num):
    """WWEIA 3000-3999 = mixed dishes: sandwiches, soups, pizza, tacos, etc.
    Also 4400-4499 = biscuits/pancakes/waffles (usually home-made/restaurant).
    These are not purchasable grocery items."""
    if cat_num is None:
        return False
    n = int(cat_num)
    return 3000 <= n < 4000 or n in (4402, 4404)  # mixed dishes, pancakes/waffles


# ---------------------------------------------------------------------------
# Better pkg_unit_singular based on WWEIA category, not food name keywords
# ---------------------------------------------------------------------------
def unit_for_category(display_cat, desc):
    desc_l = desc.lower() if desc else ''
    c = display_cat or ''

    if c == 'Dairy':
        if any(k in desc_l for k in ['milk', 'cream', 'kefir']):  return ('carton', 'cartons')
        if any(k in desc_l for k in ['yogurt', 'cottage', 'sour cream', 'cream cheese']): return ('container', 'containers')
        if 'butter' in desc_l:                                      return ('pkg', 'pkgs')
        return ('container', 'containers')
    if c == 'Cheese':
        if any(k in desc_l for k in ['goat', 'brie', 'ricotta', 'cottage', 'feta', 'fresh']): return ('pkg', 'pkgs')
        return ('pkg', 'pkgs')
    if c == 'Meat & Poultry':
        if any(k in desc_l for k in ['canned', 'spam', 'jerky', 'dried']):  return ('can', 'cans')
        return ('pkg', 'pkgs')
    if c == 'Seafood':
        if any(k in desc_l for k in ['canned', 'tuna', 'salmon', 'sardine', 'anchovie']): return ('can', 'cans')
        return ('pkg', 'pkgs')
    if c == 'Cereals & Grains':
        if any(k in desc_l for k in ['bread', 'loaf', 'baguette']): return ('loaf', 'loaves')
        if any(k in desc_l for k in ['tortilla', 'wrap']):           return ('pkg', 'pkgs')
        return ('box', 'boxes')
    if c in ('Sweets', 'Bars & Snacks'):
        if any(k in desc_l for k in ['bar', 'granola bar', 'protein bar']): return ('bar', 'bars')
        if 'cookie' in desc_l:                                       return ('pkg', 'pkgs')
        if any(k in desc_l for k in ['chip', 'pretzel', 'popcorn', 'cracker']): return ('bag', 'bags')
        return ('pkg', 'pkgs')
    if c == 'Nuts & Seeds':
        return ('bag/can', 'bags/cans')
    if c == 'Nut Butters':
        return ('jar', 'jars')
    if c == 'Legumes':
        if 'canned' in desc_l: return ('can', 'cans')
        return ('bag', 'bags')
    if c == 'Vegetables':
        if 'canned' in desc_l: return ('can', 'cans')
        if 'dried' in desc_l:  return ('bag', 'bags')
        return ('pkg', 'pkgs')
    if c == 'Fruits':
        if 'canned' in desc_l or 'applesauce' in desc_l: return ('can', 'cans')
        return ('pkg', 'pkgs')
    if c == 'Dried Fruit':
        return ('bag', 'bags')
    if c == 'Beverages':
        if any(k in desc_l for k in ['milk', 'juice', 'smoothie']): return ('carton', 'cartons')
        if 'water' in desc_l:                                        return ('bottle', 'bottles')
        return ('bottle', 'bottles')
    if c in ('Oils & Fats',):
        return ('bottle', 'bottles')
    if c == 'Condiments':
        if any(k in desc_l for k in ['peanut butter', 'almond butter', 'jam', 'jelly', 'honey',
                                      'mayo', 'sauce', 'salsa', 'syrup']):
            return ('jar', 'jars')
        return ('bottle', 'bottles')
    return ('pkg', 'pkgs')


# ---------------------------------------------------------------------------
# Soft-cheese perishability override
# WWEIA category 1602 "Cheese" maps to Shelf Stable (Hard types) in the CSV,
# but many cheeses under that category are soft/fresh and truly perishable.
# ---------------------------------------------------------------------------
SOFT_CHEESE_KEYWORDS = [
    'goat', 'brie', 'camembert', 'ricotta', 'cottage', 'cream cheese',
    'mascarpone', 'feta', 'queso fresco', 'queso blanco', 'fresh mozzarella',
    'mozzarella, fresh', 'burrata', 'neufchatel', 'farmer',
]

def is_soft_cheese(desc):
    d = desc.lower()
    return any(k in d for k in SOFT_CHEESE_KEYWORDS)


def main():
    # Load concordance: food_code → (category_number, category_description)
    print("Loading WWEIA concordance...")
    wb = openpyxl.load_workbook(XLSX)
    ws = wb['Aug2021-Aug2023_FNDDS_foodcat']
    concordance = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        fc, _, cat_num, cat_desc = row[0], row[1], row[2], row[3]
        if fc and cat_num:
            concordance[int(fc)] = (int(cat_num), str(cat_desc) if cat_desc else '')
    print(f"  {len(concordance)} food_code → category mappings")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add is_prepared_dish column if missing
    try:
        c.execute('ALTER TABLE foods ADD COLUMN is_prepared_dish INTEGER DEFAULT 0')
        print("Added is_prepared_dish column")
    except Exception:
        pass

    # Fetch all foods
    foods = c.execute('SELECT food_code, description, faps_description FROM foods').fetchall()
    print(f"  {len(foods)} foods to update")

    updates = []
    prepared = fixed_soft_cheese = unit_fixed = cat_fixed = 0

    for food_code, description, faps_description in foods:
        desc = faps_description or description or ''
        conc = concordance.get(food_code)

        cat_num   = conc[0] if conc else None
        cat_desc  = conc[1] if conc else ''
        display   = wweia_category_to_display(cat_num, cat_desc)
        prepared_dish = 1 if is_prepared_dish(cat_num) else 0

        # Unit label from category (not keyword on name)
        unit_s, unit_p = unit_for_category(display, desc)

        # Soft cheese perishability override
        days_override  = None
        tier_override  = None
        no_cook_val    = None

        if display == 'Cheese' and is_soft_cheese(desc):
            days_override = 0
            tier_override = 'Perishable'

        # Prepared dishes: mark as not purchasable (not no-cook, not shelf stable)
        if prepared_dish:
            no_cook_val = 0

        updates.append((display, prepared_dish, unit_s, unit_p,
                        days_override, tier_override, no_cook_val, food_code))

        if display: cat_fixed += 1
        if prepared_dish: prepared += 1
        if days_override is not None: fixed_soft_cheese += 1
        unit_fixed += 1

    # Batch update
    print(f"Updating {len(updates)} rows...")
    for display, prep, unit_s, unit_p, days_ov, tier_ov, nc, fc in updates:
        sql_parts = []
        vals = []
        if display:
            sql_parts.append('food_category = ?'); vals.append(display)
        sql_parts.append('is_prepared_dish = ?'); vals.append(prep)
        if unit_s:
            sql_parts.append('pkg_unit_singular = ?'); vals.append(unit_s)
            sql_parts.append('pkg_unit_plural = ?');   vals.append(unit_p)
        if days_ov is not None:
            sql_parts.append('days_without_refrigeration = ?'); vals.append(days_ov)
            sql_parts.append('stability_tier = ?');             vals.append(tier_ov)
        if nc is not None:
            sql_parts.append('no_cook = ?'); vals.append(nc)
        vals.append(fc)
        c.execute(f'UPDATE foods SET {", ".join(sql_parts)} WHERE food_code = ?', vals)

    conn.commit()

    # Report
    print(f"\nResults:")
    print(f"  Category fixed:       {cat_fixed}")
    print(f"  Prepared dishes:      {prepared}")
    print(f"  Soft cheese fixed:    {fixed_soft_cheese}")
    print(f"  Unit labels updated:  {unit_fixed}")

    print("\nCategory distribution:")
    for row in c.execute('SELECT food_category, COUNT(*) FROM foods GROUP BY food_category ORDER BY 2 DESC').fetchall():
        print(f"  {row[0] or 'NULL':<25s} {row[1]}")

    print("\nSample spot-checks:")
    for name in ['grilled cheese', 'Cookie, peanut butter, sugar', 'Cheese, goat']:
        rows = c.execute('''SELECT description, food_category, is_prepared_dish,
                                   days_without_refrigeration, stability_tier, pkg_unit_singular
                            FROM foods WHERE description LIKE ? LIMIT 2''', (f'%{name}%',)).fetchall()
        for r in rows:
            print(f"  {r[0]}: cat={r[1]}, prepared={r[2]}, days={r[3]}, tier={r[4]}, unit={r[5]}")

    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
