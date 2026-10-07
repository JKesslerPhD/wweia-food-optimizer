#!/usr/bin/env python3
"""Build comprehensive SQLite DB from WWEIA NHANES XPT files."""
import pandas as pd
import sqlite3
import numpy as np
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(BASE, 'wweia_full.db')
SAS_MISSING = 5.397605e-79

# Nutrient column mapping from XPT variable names
NUTRIENT_MAP = {
    'DR1IGRMS': 'grams', 'DR1IKCAL': 'energy_kcal', 'DR1IPROT': 'protein_g',
    'DR1ICARB': 'carbohydrate_g', 'DR1ISUGR': 'total_sugars_g',
    'DR1IFIBE': 'fiber_g', 'DR1ITFAT': 'total_fat_g',
    'DR1ISFAT': 'saturated_fat_g', 'DR1IMFAT': 'monounsaturated_fat_g',
    'DR1IPFAT': 'polyunsaturated_fat_g', 'DR1ICHOL': 'cholesterol_mg',
    'DR1IATOC': 'vitamin_e_mg', 'DR1IRET': 'retinol_ug',
    'DR1IVARA': 'vitamin_a_rae_ug', 'DR1IACAR': 'alpha_carotene_ug',
    'DR1IBCAR': 'beta_carotene_ug', 'DR1ICRYP': 'beta_cryptoxanthin_ug',
    'DR1ILYCO': 'lycopene_ug', 'DR1ILZ': 'lutein_zeaxanthin_ug',
    'DR1IVB1': 'thiamin_mg', 'DR1IVB2': 'riboflavin_mg',
    'DR1INIAC': 'niacin_mg', 'DR1IVB6': 'vitamin_b6_mg',
    'DR1IFOLA': 'folate_total_ug', 'DR1IFA': 'folic_acid_ug',
    'DR1IFF': 'food_folate_ug', 'DR1IFDFE': 'folate_dfe_ug',
    'DR1ICHL': 'choline_mg', 'DR1IVB12': 'vitamin_b12_ug',
    'DR1IB12A': 'vitamin_b12_added_ug', 'DR1IVC': 'vitamin_c_mg',
    'DR1IVD': 'vitamin_d_ug', 'DR1IVK': 'vitamin_k_ug',
    'DR1ICALC': 'calcium_mg', 'DR1IPHOS': 'phosphorus_mg',
    'DR1IMAGN': 'magnesium_mg', 'DR1IIRON': 'iron_mg',
    'DR1IZINC': 'zinc_mg', 'DR1ICOPP': 'copper_mg',
    'DR1ISODI': 'sodium_mg', 'DR1IPOTA': 'potassium_mg',
    'DR1ISELE': 'selenium_ug', 'DR1ICAFF': 'caffeine_mg',
    'DR1ITHEO': 'theobromine_mg', 'DR1IALCO': 'alcohol_g',
    'DR1IMOIS': 'water_g',
}

NON_PERISHABLE_KW = [
    'canned', 'dried', 'jerky', 'nuts', 'peanut butter', 'almond butter',
    'cashew butter', 'honey', 'jam', 'jelly', 'cracker', 'cereal',
    'granola', 'oat', 'rice', 'pasta', 'flour', 'sugar', 'salt',
    'oil', 'vinegar', 'chips', 'pretzel', 'popcorn',
    'trail mix', 'raisin', 'date', 'fig', 'prune',
    'protein bar', 'energy bar', 'granola bar',
    'protein powder', 'supplement', 'shelf-stable', 'powdered', 'instant',
    'candy', 'chocolate', 'cookie', 'brownie',
    'peanut', 'almond', 'walnut', 'cashew', 'pecan', 'pistachio',
    'sunflower seed', 'pumpkin seed',
    'sardine', 'tuna', 'spam', 'tomato sauce', 'tomato paste',
    'bread', 'bagel', 'tortilla', 'pita',
    'ketchup', 'mustard', 'mayonnaise', 'hot sauce', 'soy sauce',
    'syrup', 'molasses', 'agave', 'coffee', 'tea',
    'applesauce', 'fruit cup', 'fruit snack',
]

NO_COOK_KW = [
    'raw', 'fresh', 'salad', 'fruit', 'apple', 'banana', 'orange', 'grape',
    'berry', 'berries', 'strawberry', 'blueberry', 'raspberry', 'melon',
    'watermelon', 'cantaloupe', 'peach', 'pear', 'plum', 'cherry', 'mango',
    'papaya', 'pineapple', 'kiwi', 'avocado', 'tomato', 'cucumber', 'celery',
    'carrot', 'lettuce', 'spinach', 'cabbage', 'radish',
    'nuts', 'peanut', 'almond', 'walnut', 'cashew', 'pecan', 'pistachio',
    'sunflower seed', 'pumpkin seed', 'trail mix',
    'cheese', 'cottage cheese', 'cream cheese', 'yogurt', 'milk',
    'bread', 'tortilla', 'pita', 'bagel', 'roll', 'muffin', 'cracker',
    'granola', 'cereal', 'oat', 'energy bar', 'protein bar', 'granola bar',
    'jerky', 'beef jerky', 'turkey jerky',
    'canned', 'sardine', 'tuna',
    'peanut butter', 'almond butter', 'jam', 'jelly', 'honey',
    'hummus', 'guacamole', 'salsa', 'dip',
    'dried', 'raisin', 'date', 'fig', 'prune',
    'juice', 'smoothie', 'shake', 'sandwich', 'wrap', 'sub',
    'cold cut', 'deli', 'ham', 'turkey breast', 'salami',
]

RURAL_KW = [
    'apple', 'banana', 'orange', 'grape', 'bread', 'milk', 'cheese',
    'peanut butter', 'jelly', 'jam', 'cereal', 'oat', 'granola',
    'canned', 'tuna', 'sardine', 'salmon', 'beans', 'soup',
    'cracker', 'chips', 'nuts', 'peanut', 'trail mix',
    'jerky', 'beef jerky', 'tortilla', 'rice', 'pasta',
    'yogurt', 'cottage cheese', 'cream cheese',
    'egg', 'butter', 'margarine',
    'carrot', 'celery', 'lettuce', 'tomato', 'onion', 'potato',
    'dried', 'raisin', 'fruit', 'juice', 'water', 'soda',
    'candy', 'chocolate', 'cookie',
    'hot dog', 'sausage', 'bologna', 'deli',
    'frozen', 'ice cream',
    'ketchup', 'mustard', 'mayonnaise',
    'salt', 'pepper', 'sugar', 'flour', 'oil', 'vinegar',
    'coffee', 'tea',
]

CATEGORIES = {
    'Nuts & Seeds': ['nuts', 'peanut', 'almond', 'walnut', 'cashew', 'pecan', 'pistachio', 'sunflower seed', 'pumpkin seed', 'trail mix'],
    'Nut Butters': ['peanut butter', 'almond butter', 'cashew butter'],
    'Canned Protein': ['tuna', 'sardine', 'spam', 'canned chicken', 'canned meat'],
    'Canned Goods': ['canned', 'tomato sauce', 'tomato paste'],
    'Dried Fruit': ['raisin', 'date', 'fig', 'prune', 'dried fruit', 'dried apricot', 'dried cranberry'],
    'Cereals & Grains': ['cereal', 'oat', 'granola', 'rice', 'pasta', 'flour', 'bread', 'bagel', 'tortilla', 'pita', 'cracker', 'pretzel'],
    'Bars & Snacks': ['protein bar', 'energy bar', 'granola bar', 'chips', 'popcorn', 'fruit snack'],
    'Dairy': ['cheese', 'yogurt', 'milk', 'cottage cheese', 'cream cheese', 'butter'],
    'Meat & Jerky': ['jerky', 'beef jerky', 'turkey jerky', 'deli', 'salami', 'ham', 'bologna', 'cold cut', 'sausage', 'hot dog'],
    'Fruits': ['apple', 'banana', 'orange', 'grape', 'berry', 'melon', 'peach', 'pear', 'plum', 'cherry', 'mango', 'papaya', 'pineapple', 'kiwi'],
    'Vegetables': ['carrot', 'celery', 'lettuce', 'tomato', 'cucumber', 'spinach', 'cabbage', 'radish', 'pepper', 'onion', 'potato', 'avocado'],
    'Condiments': ['ketchup', 'mustard', 'mayonnaise', 'hot sauce', 'soy sauce', 'salsa', 'honey', 'jam', 'jelly', 'syrup'],
    'Sweets': ['candy', 'chocolate', 'cookie', 'brownie', 'cake', 'pie', 'ice cream'],
    'Beverages': ['juice', 'coffee', 'tea', 'water', 'soda', 'smoothie', 'shake'],
    'Oils & Fats': ['oil', 'margarine', 'lard', 'shortening'],
    'Spreads & Dips': ['hummus', 'guacamole', 'dip'],
}

PRICE_ESTIMATES = {
    'Nuts & Seeds': 1.50, 'Nut Butters': 0.80, 'Canned Protein': 1.00,
    'Canned Goods': 0.40, 'Dried Fruit': 1.20, 'Cereals & Grains': 0.30,
    'Bars & Snacks': 1.50, 'Dairy': 0.60, 'Meat & Jerky': 2.50,
    'Fruits': 0.40, 'Vegetables': 0.35, 'Condiments': 0.50,
    'Sweets': 0.80, 'Beverages': 0.15, 'Oils & Fats': 0.60,
    'Spreads & Dips': 0.80, 'Other': 0.50,
}

def clean_sas(val):
    """Replace SAS missing values with 0."""
    if val is None or (isinstance(val, float) and (np.isnan(val) or abs(val - SAS_MISSING) < 1e-70)):
        return 0.0
    return val

def tag_keywords(desc_lower, keywords):
    for kw in keywords:
        if kw in desc_lower:
            return 1
    return 0

def categorize(desc_lower):
    for cat, kws in CATEGORIES.items():
        for kw in kws:
            if kw in desc_lower:
                return cat
    return 'Other'

def build_db():
    print('=' * 60)
    print('Building full WWEIA SQLite database')
    print('=' * 60)

    # Load food code descriptions
    print('Loading food code descriptions...')
    fcd = pd.read_sas(os.path.join(BASE, 'drxfcd_L.xpt'), format='xport')
    food_codes = {}
    for _, row in fcd.iterrows():
        code = int(row['DRXFDCD'])
        desc = row['DRXFCLD']
        if isinstance(desc, bytes):
            desc = desc.decode('utf-8', errors='replace')
        food_codes[code] = desc
    print(f'  {len(food_codes)} food codes loaded')

    # Load Day 1 individual foods
    print('Loading Day 1 individual foods (DR1IFF_L.xpt)...')
    df1 = pd.read_sas(os.path.join(BASE, 'DR1IFF_L.xpt'), format='xport')
    print(f'  {len(df1)} records, {df1["DR1IFDCD"].nunique()} unique foods')

    # Load Day 2 individual foods
    print('Loading Day 2 individual foods (DR2IFF_L.xpt)...')
    df2 = pd.read_sas(os.path.join(BASE, 'DR2IFF_L.xpt'), format='xport')
    # Rename DR2 columns to DR1 for consistency
    rename_map = {c: c.replace('DR2', 'DR1') for c in df2.columns if c.startswith('DR2')}
    df2 = df2.rename(columns=rename_map)
    print(f'  {len(df2)} records, {df2["DR1IFDCD"].nunique()} unique foods')

    # Combine
    df = pd.concat([df1, df2], ignore_index=True)
    print(f'Combined: {len(df)} records, {df["DR1IFDCD"].nunique()} unique foods')

    # Aggregate: compute mean nutrients per 100g for each food code
    print('Aggregating nutrients per food code...')
    nutrient_cols = [c for c in NUTRIENT_MAP.keys() if c in df.columns]

    # Clean SAS missing values
    for col in nutrient_cols:
        df[col] = df[col].apply(clean_sas)

    # We need per-100g values. The XPT data has absolute amounts for the portion eaten.
    # Normalize: nutrient_per_100g = nutrient_amount / grams * 100
    food_agg = {}
    for food_code, group in df.groupby('DR1IFDCD'):
        code = int(food_code)
        vals = {}
        total_grams = group['DR1IGRMS'].apply(clean_sas).sum()
        count = len(group)
        if total_grams <= 0:
            continue

        for xpt_col, db_col in NUTRIENT_MAP.items():
            if xpt_col in group.columns and db_col != 'grams':
                total_nutrient = group[xpt_col].apply(clean_sas).sum()
                # per 100g = (total nutrient / total grams) * 100
                vals[db_col] = round((total_nutrient / total_grams) * 100, 4)
            elif db_col == 'grams':
                vals['avg_portion_g'] = round(total_grams / count, 1)

        vals['intake_count'] = count
        food_agg[code] = vals

    print(f'  {len(food_agg)} unique foods with nutrient data')

    # Create database
    print('Creating SQLite database...')
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Build nutrient columns
    all_nutrient_cols = sorted(set(NUTRIENT_MAP.values()) - {'grams'})
    nutrient_col_defs = ', '.join(f'{col} REAL DEFAULT 0' for col in all_nutrient_cols)

    c.execute(f'''CREATE TABLE foods (
        food_code INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        no_cook INTEGER DEFAULT 0,
        non_perishable INTEGER DEFAULT 0,
        rural_available INTEGER DEFAULT 0,
        food_category TEXT DEFAULT '',
        calorie_density REAL DEFAULT 0,
        est_price_per_100g REAL DEFAULT 0.50,
        avg_portion_g REAL DEFAULT 0,
        intake_count INTEGER DEFAULT 0,
        {nutrient_col_defs}
    )''')

    # Insert foods
    print('Inserting foods...')
    inserted = 0
    for code, vals in food_agg.items():
        desc = food_codes.get(code, f'Unknown food {code}')
        desc_lower = desc.lower()

        no_cook = tag_keywords(desc_lower, NO_COOK_KW)
        non_perish = tag_keywords(desc_lower, NON_PERISHABLE_KW)
        rural = tag_keywords(desc_lower, RURAL_KW)
        category = categorize(desc_lower)
        price = PRICE_ESTIMATES.get(category, 0.50)
        energy = vals.get('energy_kcal', 0)
        cal_density = round(energy / 100.0, 4) if energy > 0 else 0
        avg_portion = vals.get('avg_portion_g', 0)
        intake_count = vals.get('intake_count', 0)

        col_names = ['food_code', 'description', 'no_cook', 'non_perishable',
                     'rural_available', 'food_category', 'calorie_density',
                     'est_price_per_100g', 'avg_portion_g', 'intake_count']
        col_vals = [code, desc, no_cook, non_perish, rural, category,
                    cal_density, price, avg_portion, intake_count]

        for nc in all_nutrient_cols:
            col_names.append(nc)
            col_vals.append(vals.get(nc, 0))

        placeholders = ', '.join(['?'] * len(col_names))
        col_str = ', '.join(col_names)
        c.execute(f'INSERT OR REPLACE INTO foods ({col_str}) VALUES ({placeholders})', col_vals)
        inserted += 1

    # Create indexes
    c.execute('CREATE INDEX idx_desc ON foods(description)')
    c.execute('CREATE INDEX idx_nocook ON foods(no_cook)')
    c.execute('CREATE INDEX idx_nonperish ON foods(non_perishable)')
    c.execute('CREATE INDEX idx_rural ON foods(rural_available)')
    c.execute('CREATE INDEX idx_category ON foods(food_category)')
    c.execute('CREATE INDEX idx_caldensity ON foods(calorie_density)')

    conn.commit()

    # Print summary
    print()
    print('=' * 60)
    print(f'Database built: {DB_PATH}')
    for label, sql in [
        ('Total foods', 'SELECT COUNT(*) FROM foods'),
        ('No-cook', 'SELECT COUNT(*) FROM foods WHERE no_cook=1'),
        ('Non-perishable', 'SELECT COUNT(*) FROM foods WHERE non_perishable=1'),
        ('Rural available', 'SELECT COUNT(*) FROM foods WHERE rural_available=1'),
        ('Non-perish + No-cook', 'SELECT COUNT(*) FROM foods WHERE non_perishable=1 AND no_cook=1'),
        ('All three filters', 'SELECT COUNT(*) FROM foods WHERE non_perishable=1 AND no_cook=1 AND rural_available=1'),
        ('Unique categories', 'SELECT COUNT(DISTINCT food_category) FROM foods'),
    ]:
        c.execute(sql)
        print(f'  {label}: {c.fetchone()[0]}')

    # Top calorie-dense non-perishable no-cook foods
    print()
    print('Top 15 calorie-dense non-perishable no-cook rural foods:')
    rows = c.execute('''
        SELECT description, calorie_density, energy_kcal, protein_g, food_category
        FROM foods
        WHERE non_perishable=1 AND no_cook=1 AND rural_available=1 AND energy_kcal > 0
        ORDER BY calorie_density DESC LIMIT 15
    ''').fetchall()
    for r in rows:
        print(f'  {r[0]}: {r[1]} kcal/g, {r[2]} kcal, {r[3]}g protein [{r[4]}]')

    conn.close()
    print()
    print('Done!')

if __name__ == '__main__':
    build_db()
