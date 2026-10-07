#!/usr/bin/env python3
"""
Build package size and unit pricing data from FoodAPS.
Links to food codes in wweia_full.db.
Adds: typical_pkg_grams, typical_pkg_unit, typical_pkg_price, typical_pkg_label
"""
import pandas as pd
import numpy as np
import sqlite3, os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(BASE, 'wweia_full.db')

# Convert pkgsizeunit to a human-readable label and canonical unit
UNIT_LABELS = {
    'OZ':    ('oz', 'pkg'),  'LBS': ('lb', 'pkg'),
    'LITER': ('L',  'bottle'),'PINT': ('pt','carton'),
    'COUNT': ('ct', 'pkg'),  'PACK': ('pk','pack'),
    'GRAM':  ('g',  'pkg'),  'BAG':  ('bag','bag'),
    'BOX':   ('box','box'),  'CAN':  ('can','can'),
    'LOAF':  ('loaf','loaf'),'PIECE':('pc','piece'),
    'SLICE': ('sl','slice'), 'DRYOZ':('dry oz','pkg'),
    'SMALL': ('sm','pkg'),   'LARGE':('lg','pkg'),
    'MEDIUM':('med','pkg'),
}

# Human-readable unit guesses by food category / description keywords
KEYWORD_UNITS = [
    (['tuna','sardine','salmon, canned','spam','beans, canned','corn, canned',
      'tomato sauce','soup, canned','chicken, canned'], 'can', 'cans'),
    (['peanut butter','almond butter','cashew butter','jam','jelly','honey',
      'mayonnaise','ketchup','mustard','hot sauce','soy sauce','salsa'], 'jar', 'jars'),
    (['bread','loaf'], 'loaf', 'loaves'),
    (['cereal','oat','granola','flour','sugar','rice','pasta','noodle',
      'chips','cracker','pretzel','popcorn','trail mix','dried','raisin',
      'cookie','brownie','coffee','tea'], 'bag/box', 'bags/boxes'),
    (['milk','juice','water','soda','sports drink','energy drink',
      'chocolate milk','almond milk'], 'bottle/carton', 'bottles/cartons'),
    (['yogurt','cottage cheese','cream cheese','sour cream'], 'container', 'containers'),
    (['cheese'], 'pkg', 'pkgs'),
    (['jerky','beef jerky','turkey jerky','meat stick'], 'bag', 'bags'),
    (['protein bar','energy bar','granola bar','candy bar'], 'bar', 'bars'),
    (['nuts','peanut','almond','walnut','cashew','pecan','pistachio',
      'sunflower seed','pumpkin seed'], 'bag/can', 'bags/cans'),
    (['oil','vinegar'], 'bottle', 'bottles'),
    (['egg'], 'dozen', 'dozens'),
]

def get_unit_label(desc):
    if not desc or not isinstance(desc, str):
        return ('pkg', 'pkgs')
    d = desc.lower()
    for keywords, singular, plural in KEYWORD_UNITS:
        for kw in keywords:
            if kw in d:
                return (singular, plural)
    return ('pkg', 'pkgs')

def build():
    print('Loading FoodAPS items...')
    fah = pd.read_csv(os.path.join(BASE,'faps_fahitem_puf.csv'), encoding='latin1',
        usecols=['hhnum','eventid','itemnum','totgramsunadj','totitemexp',
                 'pkgsize','pkgsizeunit','quantity'])

    print('Loading FoodAPS food codes...')
    nutr = pd.read_csv(os.path.join(BASE,'faps_fahnutrients.csv'), encoding='latin1',
        usecols=['hhnum','eventid','itemnum','foodcode','usdadescmain'])
    nutr['foodcode'] = nutr['foodcode'].astype('Int64')
    nutr = nutr.dropna(subset=['foodcode'])

    # Merge items with food codes
    merged = fah.merge(nutr[['hhnum','eventid','itemnum','foodcode','usdadescmain']],
                       on=['hhnum','eventid','itemnum'], how='inner')
    print(f'Merged: {len(merged)} records')

    # Filter to valid rows
    valid = merged[
        (merged['quantity'] >= 1) &
        (merged['totgramsunadj'] > 0) &
        (merged['totitemexp'] > 0)
    ].copy()

    valid['grams_per_unit'] = valid['totgramsunadj'] / valid['quantity']
    valid['price_per_unit'] = valid['totitemexp'] / valid['quantity']

    # Remove extreme outliers (bulk purchases)
    valid = valid[(valid['grams_per_unit'] > 5) & (valid['grams_per_unit'] < 10000)]
    valid = valid[(valid['price_per_unit'] > 0.05) & (valid['price_per_unit'] < 50)]

    print(f'Valid records after filtering: {len(valid)}')

    # Aggregate by food code
    print('Computing package statistics per food code...')
    agg = valid.groupby('foodcode').agg(
        typical_pkg_grams     = ('grams_per_unit', 'median'),
        typical_pkg_price     = ('price_per_unit', 'median'),
        pkg_price_min         = ('price_per_unit', 'min'),
        pkg_price_max         = ('price_per_unit', 'max'),
        pkg_obs               = ('grams_per_unit', 'count'),
        top_unit              = ('pkgsizeunit', lambda x: x.mode().iloc[0] if len(x)>0 else 'OZ'),
        food_desc             = ('usdadescmain', 'first'),
    ).reset_index()

    agg['typical_pkg_grams'] = agg['typical_pkg_grams'].round(1)
    agg['typical_pkg_price'] = agg['typical_pkg_price'].round(2)

    # Generate human-readable unit labels
    agg['pkg_unit_singular'] = agg['food_desc'].apply(lambda d: get_unit_label(d)[0])
    agg['pkg_unit_plural']   = agg['food_desc'].apply(lambda d: get_unit_label(d)[1])

    print(f'Package data for {len(agg)} food codes')
    print()
    print('Sample data:')
    sample = agg.nlargest(20,'pkg_obs')[['foodcode','food_desc','typical_pkg_grams',
                                          'typical_pkg_price','pkg_unit_singular','pkg_obs']]
    print(sample.to_string())
    return agg

def update_db(agg):
    print('\nUpdating database...')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add package columns
    for col, coltype in [
        ('typical_pkg_grams',   'REAL'),
        ('typical_pkg_price',   'REAL'),
        ('pkg_price_min',       'REAL'),
        ('pkg_price_max',       'REAL'),
        ('pkg_obs',             'INTEGER'),
        ('pkg_unit_singular',   'TEXT'),
        ('pkg_unit_plural',     'TEXT'),
    ]:
        try:
            c.execute(f'ALTER TABLE foods ADD COLUMN {col} {coltype}')
        except:
            pass

    updated = 0
    for _, row in agg.iterrows():
        fc = int(row['foodcode'])
        c.execute('''
            UPDATE foods SET
                typical_pkg_grams = ?,
                typical_pkg_price = ?,
                pkg_price_min     = ?,
                pkg_price_max     = ?,
                pkg_obs           = ?,
                pkg_unit_singular = ?,
                pkg_unit_plural   = ?
            WHERE food_code = ?
        ''', (
            round(float(row['typical_pkg_grams']), 1),
            round(float(row['typical_pkg_price']), 2),
            round(float(row['pkg_price_min']), 2),
            round(float(row['pkg_price_max']), 2),
            int(row['pkg_obs']),
            str(row['pkg_unit_singular']),
            str(row['pkg_unit_plural']),
            fc,
        ))
        if c.rowcount > 0:
            updated += 1

    conn.commit()
    print(f'Updated {updated} food codes with package data')

    # Summary
    c.execute('SELECT COUNT(*) FROM foods WHERE typical_pkg_grams IS NOT NULL')
    print(f'Foods with package data: {c.fetchone()[0]}')

    # Show sample shelf-stable no-cook foods with package info
    print()
    print('=== Sample shelf-stable foods with package data ===')
    rows = c.execute('''
        SELECT COALESCE(faps_description,description) as name,
               typical_pkg_grams, typical_pkg_price, pkg_unit_singular,
               calorie_density, energy_kcal, food_category
        FROM foods
        WHERE typical_pkg_grams IS NOT NULL
          AND (non_perishable=1 OR faps_shelf_stable=1)
          AND no_cook=1 AND energy_kcal > 50
        ORDER BY pkg_obs DESC LIMIT 25
    ''').fetchall()
    for r in rows:
        cal_per_pkg = round((r[2] or 0) / 100.0 * (r[1] or 0), 0)
        print(f'  {r[0]}: {r[1]:.0f}g/{r[3]} @ ${r[3+1]:.2f} = {cal_per_pkg:.0f} kcal [{r[6]}]')

    conn.close()

if __name__ == '__main__':
    agg = build()
    update_db(agg)
    print('\nDone!')
