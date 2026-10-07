#!/usr/bin/env python3
"""Add dietary restriction columns to wweia_full.db using WWEIA food categories.

Requires: pandas, openpyxl (build-time deps, not in gunicorn venv)
Run: python3 add_dietary_tags.py [path/to/db]  (defaults to ./wweia_full.db)
"""
import sqlite3
import os
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, 'wweia_full.db')
WWEIA_XLSX = os.path.join(BASE, 'WWEIA_August2021_August2023_foodcat_FNDDS.xlsx')

# ── WWEIA category sets ──────────────────────────────────────────────────────

DAIRY_CATS = {
    1002, 1004, 1006, 1008,          # Milk (whole/reduced fat/lowfat/nonfat)
    1202, 1204, 1206, 1208,          # Flavored milk
    1402,                             # Milk shakes and other dairy drinks
    1602, 1604,                       # Cheese, Cottage/ricotta cheese
    1820, 1822,                       # Yogurt (regular, Greek)
    8002,                             # Butter and animal fats
    8006,                             # Cream cheese, sour cream, whipped cream
    8008,                             # Cream and cream substitutes
    9010,                             # Baby food: yogurt
    9402, 9404,                       # Infant formula (dairy-based)
    9602,                             # Human milk
}

# These are dairy-free despite the milk/yogurt name
PLANT_DAIRY_CATS = {1902, 1904}      # Plant-based milk, plant-based yogurt

# Mixed dishes that nearly always contain dairy
DAIRY_DISH_CATS = {
    3206,                             # Macaroni and cheese
    3806,                             # Soups, cream-based
    4402, 4404,                       # Biscuits/quick breads, pancakes/waffles (butter, milk)
    5402,                             # Cereal bars (often milk powder)
    5502, 5504, 5506,                 # Cakes/pies, cookies/brownies, pastries (butter, milk)
    5802,                             # Ice cream and frozen dairy desserts
    5804,                             # Pudding (milk)
}
# Chocolate candy is typically milk chocolate; dark/bittersweet are vegan-ok
# Applied conditionally in tag_food() below
CHOCOLATE_CANDY_CATS = {5702}

# Keywords that indicate a chocolate item is dairy-free (dark/bittersweet)
DARK_CHOCOLATE_KW = ['dark chocolate', 'bittersweet', 'semi-sweet', 'semisweet', '% cacao', '% cocoa']

MEAT_CATS = {
    2002, 2004,                       # Beef (all cuts, ground)
    2006,                             # Pork
    2008,                             # Lamb, goat, game
    2010,                             # Liver and organ meats
    2202, 2204, 2206,                 # Chicken, turkey, duck
    2402,                             # Fish
    2404,                             # Shellfish
    2602, 2604, 2606, 2608,          # Cold cuts, bacon, frankfurters, sausages
    9008,                             # Baby food: meat and dinners
}

# Mixed dishes whose name encodes meat/poultry/seafood
MEAT_DISH_CATS = {
    3002,                             # Meat mixed dishes
    3004,                             # Poultry mixed dishes
    3006,                             # Seafood mixed dishes
    3703,                             # Frankfurter sandwiches
    3704,                             # Chicken fillet sandwiches
    3730,                             # Seafood sandwiches
    3740,                             # Deli and cured meat sandwiches
    3742,                             # Meat and BBQ sandwiches
}

SHELLFISH_CATS = {2404}              # Shellfish (stand-alone)
SHELLFISH_DISH_CATS = {3006, 3730}   # Seafood dishes (may include shellfish — conservative)

EGG_CATS = {2502}                    # Eggs and omelets
EGG_DISH_CATS = {
    3706,                             # Egg/breakfast sandwiches
    4404,                             # Pancakes, waffles, French toast (eggs)
    5502, 5504, 5506,                 # Cakes/pies, cookies/brownies, pastries (eggs)
}

# Mayonnaise is egg-based; track separately via keyword for mixed dishes
MAY_CATS = {8010}

NUT_CATS = {2804}                    # Nuts and seeds
NUT_SANDWICH_CATS = {3722}          # Peanut butter and jelly sandwiches

SOY_CATS = {2806, 8404}             # Soy products, soy-based condiments
SOY_DISH_CATS = {3404}             # Stir-fry and soy-based sauce mixtures

# Categories that always contain gluten (wheat/barley/rye)
GLUTEN_ALWAYS_CATS = {
    4202, 4204, 4206,               # Yeast breads, rolls, bagels/English muffins
    4402, 4404,                      # Biscuits/quick breads, pancakes/waffles
    5008,                            # Pretzels/snack mix
    5202, 5204,                      # Crackers (excl. saltines), saltines
    5402, 5404,                      # Cereal bars, nutrition bars (usually wheat)
    5502, 5504, 5506,               # Cakes/pies, cookies/brownies, doughnuts/pastries
    3206, 3208,                      # Mac and cheese, turnovers/grain-based items
    3602,                            # Pizza (wheat crust)
    3702, 3703, 3704,               # Burgers, frankfurter subs, chicken subs (bun)
    3706, 3720, 3722, 3740, 3742,  # Sandwiches (bread)
    3730, 3744,                      # More sandwiches
    3808,                            # Ramen and Asian broth soups (ramen = wheat noodles)
    3406,                            # Egg rolls, dumplings (wrappers = wheat)
    4802,                            # Oatmeal (oats may be contaminated; conservative)
    9002,                            # Baby food: cereals (often wheat)
    9012,                            # Baby food: snacks and sweets
}

# Gluten-free by category (no wheat, barley, or rye)
GLUTEN_FREE_CATS = {
    4002,                            # Rice (plain cooked rice)
    5002,                            # Potato chips
    5004,                            # Tortilla/corn chips
    5006,                            # Popcorn
    # All fruits, veg, meats, dairy, eggs, beans, nuts → handled by absence of gluten flag
}

# ── Keyword helpers ──────────────────────────────────────────────────────────

DAIRY_KW = [
    'butter', 'cream', 'milk', 'cheese', 'yogurt', 'yoghurt',
    'custard', 'béchamel', 'bechamel', 'au gratin', 'whey', 'casein', 'lactose',
]
DAIRY_EXCLUDE_KW = [
    'peanut butter', 'almond butter', 'cashew butter', 'sunbutter', 'nut butter',
    'butternut', 'butterfly', 'buttercup',      # false positives on "butter"
    'nondairy', 'non-dairy', 'dairy-free', 'plant-based', 'coconut milk',
    'oat milk', 'almond milk', 'soy milk', 'soymilk', 'rice milk',
]

NUT_KW = [
    'peanut', 'almond', 'walnut', 'cashew', 'pecan', 'pistachio',
    'hazelnut', 'macadamia', 'brazil nut', 'pine nut', 'praline',
    'marzipan', 'nut butter', 'nutella', 'mixed nut',
    ' nut,', ' nut ', ' nuts,', ' nuts ', 'with nuts', 'with nut',
]

SOY_KW = ['soy ', 'soymilk', 'soy milk', 'tofu', 'tempeh', 'edamame', 'miso',
          'soybean', ' soya']
SHELLFISH_KW = [
    'shrimp', 'crab', 'lobster', 'clam', 'oyster', 'scallop',
    'mussel', 'squid', 'calamari', 'crayfish', 'crawfish', 'abalone',
]
EGG_KW = ['egg salad', 'deviled egg', 'quiche', 'frittata', 'egg noodle',
          'custard', 'meringue', 'albumin', 'mayonnaise', 'mayo', ' egg ', ' eggs ']
MEAT_KW = [
    'beef', 'pork', 'chicken', 'turkey', 'lamb', 'bacon', 'ham', 'sausage',
    'pepperoni', 'salami', 'anchovy', 'anchovies', 'lard', 'suet', 'jerky',
    'prosciutto', 'chorizo', 'spam', 'canned chicken', 'canned turkey',
]
HONEY_KW = ['honey', 'mead']
GELATIN_KW = ['gelatin', 'gelatine', 'jello', 'gummy', 'gummies', 'marshmallow']

GLUTEN_KW = [
    'wheat', 'barley', 'rye ', 'malt', ' flour', 'semolina', 'spelt',
    'farro', 'bulgur', 'triticale', 'seitan', 'bread ', 'breadcrumb',
    ' pasta', 'noodle', 'dumpling', 'wonton', 'soba', 'udon', 'lo mein',
    'chow mein', 'couscous', 'panko', 'croissant', 'pita', 'naan',
    'tortilla flour', 'flour tortilla',
]
GLUTEN_FREE_KW = [
    'gluten-free', 'gluten free', 'gf ', 'gf,',
    'rice noodle', 'rice pasta', 'rice flour', 'corn tortilla',
    'quinoa', 'buckwheat', 'amaranth', 'millet', 'teff', 'sorghum', 'tapioca',
    'tamari',        # GF soy sauce alternative
]
VEGAN_NON_KW = HONEY_KW + GELATIN_KW + ['lard', 'suet', 'anchovy', 'anchovies',
                                           'whey', 'casein', 'albumin', 'collagen']


def any_kw(desc, keywords):
    return any(kw in desc for kw in keywords)


def none_kw(desc, keywords):
    return not any_kw(desc, keywords)


VEGAN_OVERRIDE_KW = ['vegan', 'plant-based', 'dairy-free egg-free']

def tag_food(food_code, description, cat_num):
    d = ' ' + description.lower() + ' '   # pad for word-boundary matching

    # Explicitly-labeled vegan products override category inferences
    explicitly_vegan = any_kw(d, VEGAN_OVERRIDE_KW)

    # ── Dairy ──────────────────────────────────────────────────────────────
    # Chocolate candy is milk chocolate by default; dark chocolate is dairy-free
    choc_has_dairy = (cat_num in CHOCOLATE_CANDY_CATS
                      and none_kw(d, DARK_CHOCOLATE_KW)
                      and not explicitly_vegan)
    dairy = (
        cat_num in DAIRY_CATS
        or (cat_num in DAIRY_DISH_CATS and not explicitly_vegan)
        or choc_has_dairy
        or (any_kw(d, DAIRY_KW) and none_kw(d, DAIRY_EXCLUDE_KW))
    ) and cat_num not in PLANT_DAIRY_CATS

    # ── Meat / fish (not vegetarian) ───────────────────────────────────────
    meat = (
        cat_num in MEAT_CATS
        or cat_num in MEAT_DISH_CATS
        or any_kw(d, MEAT_KW)
    )

    # ── Shellfish ──────────────────────────────────────────────────────────
    shellfish = (
        cat_num in SHELLFISH_CATS
        or cat_num in SHELLFISH_DISH_CATS
        or any_kw(d, SHELLFISH_KW)
    )

    # ── Eggs ───────────────────────────────────────────────────────────────
    egg = (
        cat_num in EGG_CATS
        or (cat_num in EGG_DISH_CATS and not explicitly_vegan)
        or cat_num in MAY_CATS          # mayo = egg-based
        or any_kw(d, EGG_KW)
    )

    # ── Nuts (tree nuts + peanuts) ─────────────────────────────────────────
    nut = cat_num in NUT_CATS or cat_num in NUT_SANDWICH_CATS or any_kw(d, NUT_KW)

    # ── Soy ────────────────────────────────────────────────────────────────
    soy = cat_num in SOY_CATS or cat_num in SOY_DISH_CATS or any_kw(d, SOY_KW)

    # ── Gluten ─────────────────────────────────────────────────────────────
    # Positive GF keywords override anything
    explicitly_gf = any_kw(d, GLUTEN_FREE_KW)
    if explicitly_gf:
        gluten = 0
    elif cat_num in GLUTEN_ALWAYS_CATS or any_kw(d, GLUTEN_KW):
        gluten = 1
    elif cat_num in GLUTEN_FREE_CATS:
        gluten = 0
    else:
        # Pasta/noodle mixed dishes are a special case
        if cat_num == 4004:          # Pasta, noodles, cooked grains
            gluten = 0 if any_kw(d, ['rice ', 'quinoa', 'corn', 'potato', 'polenta']) else 1
        elif cat_num == 4208:        # Tortillas
            gluten = 0 if any_kw(d, ['corn tortilla', 'corn ']) else 1
        elif cat_num in {4602, 4604}:   # RTE cereals — usually contain wheat/malt
            # Only GF if explicitly labeled or is a pure rice/corn cereal
            if any_kw(d, GLUTEN_FREE_KW):
                gluten = 0
            elif any_kw(d, ['puffed rice', 'rice krispies', 'rice chex', ' rice cereal',
                            'corn flakes', 'corn pops', 'corn chex', 'frosted flakes',
                            'fruity pebbles', 'cocoa pebbles', 'cocoa puffs',
                            'lucky charms', 'reese\'s puffs', 'cap\'n crunch']) and none_kw(d, ['wheat', 'barley', 'malt', 'oat']):
                gluten = 0
            else:
                gluten = 1   # Conservative: most RTE cereals contain wheat or barley malt
        elif cat_num in {4802, 4804}:   # Oatmeal, grits
            gluten = 0 if any_kw(d, ['grits', 'corn', 'quinoa']) and none_kw(d, ['wheat', 'barley']) else 1
        elif cat_num == 3204:        # Pasta mixed dishes
            gluten = 1
        elif cat_num == 3402:        # Fried rice and lo/chow mein
            gluten = 0 if any_kw(d, ['fried rice']) and none_kw(d, ['noodle', 'mein', 'lo mein', 'chow mein']) else 1
        elif cat_num == 3502:        # Burritos and tacos
            gluten = 0 if any_kw(d, ['corn tortilla', 'corn taco', ' taco ']) else 1
        else:
            gluten = 0              # Default: assume GF unless evidence otherwise

    # ── Vegetarian: no meat, no fish, no shellfish ─────────────────────────
    vegetarian = 0 if (meat or shellfish) else 1

    # ── Vegan: no meat, fish, shellfish, dairy, eggs, + no honey/gelatin ──
    non_vegan_extras = any_kw(d, VEGAN_NON_KW)
    vegan = 0 if (meat or shellfish or dairy or egg or non_vegan_extras) else 1

    # Derive clean boolean flags (1 = restriction-safe, 0 = contains allergen)
    return {
        'wweia_category':   cat_num,
        'is_vegan':         vegan,
        'is_vegetarian':    vegetarian,
        'is_dairy_free':    0 if dairy else 1,
        'is_gluten_free':   0 if gluten else 1,
        'is_nut_free':      0 if nut else 1,
        'is_shellfish_free': 0 if shellfish else 1,
        'is_egg_free':      0 if egg else 1,
        'is_soy_free':      0 if soy else 1,
    }


def main():
    import pandas as pd

    print(f'Loading WWEIA categories from {WWEIA_XLSX}...')
    xl = pd.ExcelFile(WWEIA_XLSX)
    cat_df = xl.parse('Aug2021-Aug2023_FNDDS_foodcat')
    cat_map = dict(zip(cat_df['food_code'].astype(int), cat_df['category_number'].astype(int)))
    print(f'  {len(cat_map)} food-code → category mappings')

    print(f'Opening database {DB_PATH}...')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add new columns (idempotent)
    new_cols = [
        'wweia_category INTEGER DEFAULT 0',
        'is_vegan INTEGER DEFAULT 0',
        'is_vegetarian INTEGER DEFAULT 0',
        'is_dairy_free INTEGER DEFAULT 0',
        'is_gluten_free INTEGER DEFAULT 0',
        'is_nut_free INTEGER DEFAULT 0',
        'is_shellfish_free INTEGER DEFAULT 0',
        'is_egg_free INTEGER DEFAULT 0',
        'is_soy_free INTEGER DEFAULT 0',
    ]
    existing = {row[1] for row in c.execute('PRAGMA table_info(foods)').fetchall()}
    for col_def in new_cols:
        col_name = col_def.split()[0]
        if col_name not in existing:
            c.execute(f'ALTER TABLE foods ADD COLUMN {col_def}')
            print(f'  Added column: {col_name}')

    # Tag every food
    rows = c.execute('SELECT food_code, description FROM foods').fetchall()
    print(f'Tagging {len(rows)} foods...')
    updated = 0
    unmatched_cat = 0
    for food_code, desc in rows:
        cat_num = cat_map.get(food_code, 9999)
        if cat_num == 9999 and food_code not in cat_map:
            unmatched_cat += 1
        tags = tag_food(food_code, desc, cat_num)
        c.execute('''UPDATE foods SET
            wweia_category   = :wweia_category,
            is_vegan         = :is_vegan,
            is_vegetarian    = :is_vegetarian,
            is_dairy_free    = :is_dairy_free,
            is_gluten_free   = :is_gluten_free,
            is_nut_free      = :is_nut_free,
            is_shellfish_free = :is_shellfish_free,
            is_egg_free      = :is_egg_free,
            is_soy_free      = :is_soy_free
            WHERE food_code = :fc''', {**tags, 'fc': food_code})
        updated += 1

    # Add indexes for fast filtering
    new_indexes = [
        ('idx_vegan',        'foods(is_vegan)'),
        ('idx_vegetarian',   'foods(is_vegetarian)'),
        ('idx_dairy_free',   'foods(is_dairy_free)'),
        ('idx_gluten_free',  'foods(is_gluten_free)'),
        ('idx_nut_free',     'foods(is_nut_free)'),
        ('idx_shellfish_free', 'foods(is_shellfish_free)'),
        ('idx_egg_free',     'foods(is_egg_free)'),
        ('idx_soy_free',     'foods(is_soy_free)'),
        ('idx_wweia_cat',    'foods(wweia_category)'),
    ]
    for idx_name, idx_on in new_indexes:
        c.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_on}')

    conn.commit()
    conn.close()

    # Summary
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute('SELECT COUNT(*) FROM foods').fetchone()[0]
    print(f'\nTagged {updated} foods ({unmatched_cat} used fallback category 9999)')
    print(f'\nDietary restriction counts (out of {total} total):')
    for col, label in [
        ('is_vegan', 'Vegan'),
        ('is_vegetarian', 'Vegetarian'),
        ('is_dairy_free', 'Dairy-free'),
        ('is_gluten_free', 'Gluten-free'),
        ('is_nut_free', 'Nut-free'),
        ('is_shellfish_free', 'Shellfish-free'),
        ('is_egg_free', 'Egg-free'),
        ('is_soy_free', 'Soy-free'),
    ]:
        n = c.execute(f'SELECT COUNT(*) FROM foods WHERE {col}=1').fetchone()[0]
        pct = 100 * n / total if total else 0
        print(f'  {label}: {n} ({pct:.1f}%)')

    # Sanity checks
    print('\nSanity checks:')
    for desc_like, expected_col, expected_val in [
        ('Milk, whole', 'is_dairy_free', 0),
        ('Almonds', 'is_nut_free', 0),
        ('Chicken', 'is_vegetarian', 0),
        ('Shrimp', 'is_shellfish_free', 0),
        ('Pasta', 'is_gluten_free', 0),
        ('Rice', 'is_gluten_free', 1),
        ('Apple, raw', 'is_vegan', 1),
        ('Tofu', 'is_soy_free', 0),
    ]:
        row = c.execute(
            f'SELECT description, {expected_col} FROM foods WHERE description LIKE ? LIMIT 1',
            (f'%{desc_like}%',)
        ).fetchone()
        if row:
            status = 'OK' if row[1] == expected_val else f'FAIL (got {row[1]}, want {expected_val})'
            print(f'  [{status}] "{row[0]}": {expected_col}={row[1]}')
        else:
            print(f'  [SKIP] No food matching {desc_like!r}')

    conn.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
