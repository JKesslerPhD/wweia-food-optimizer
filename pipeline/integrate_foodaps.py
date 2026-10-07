#!/usr/bin/env python3
"""
Integrate FoodAPS data into wweia_full.db:
- Real food names from usdadescmain
- Price per 100g from actual purchase data
- Rural availability flag from household rural status
- Store type flags (supermarket, convenience, dollar, supercenter)
- Perishability classification from food category + description
"""
import pandas as pd
import numpy as np
import sqlite3
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(BASE, 'wweia_full.db')

# FoodAPS primary store type codes
SUPERMARKET_CODES = {121, 106, 107}       # Supermarket, grocery
SUPERCENTER_CODES = {122, 123, 117}       # Walmart, warehouse, mass merch
CONVENIENCE_CODES = {102, 103}            # Convenience stores
DOLLAR_CODES      = {111, 112}            # Dollar stores

# Non-perishable classification from Food Storage Guidelines
# Based on foodbanksbc.org guidelines + USDA FoodKeeper categories
NONPERISHABLE_CATS = {
    # usdafoodcat1 codes that are shelf-stable
    5:  True,   # Grains/cereals
    6:  False,  # Vegetables (mostly perishable, some canned)
    7:  False,  # Fruits (mostly perishable, some dried/canned)
    8:  True,   # Legumes/nuts/seeds
    9:  True,   # Fats/oils
    10: False,  # Dairy (mostly perishable)
    11: False,  # Meat/poultry (mostly perishable)
    12: False,  # Seafood (mostly perishable)
    13: True,   # Mixed dishes - shelf stable components
    14: True,   # Sweets/snacks/beverages
    15: True,   # Beverages/water
}

# Keywords that indicate shelf-stable regardless of category
SHELF_STABLE_KW = [
    'canned', 'dried', 'dry', 'dehydrated', 'jerky', 'nuts', 'peanut butter',
    'almond butter', 'cashew butter', 'honey', 'jam', 'jelly', 'cracker',
    'cereal', 'granola', 'oat', 'rice', 'pasta', 'noodle', 'flour', 'sugar',
    'oil', 'vinegar', 'chips', 'pretzel', 'popcorn', 'trail mix',
    'raisin', 'date', 'fig', 'prune', 'protein bar', 'energy bar', 'granola bar',
    'protein powder', 'instant', 'powdered', 'shelf-stable',
    'candy', 'chocolate', 'cookie', 'brownie', 'cracker',
    'peanut', 'almond', 'walnut', 'cashew', 'pecan', 'pistachio', 'sunflower seed',
    'sardine', 'tuna', 'spam', 'tomato sauce', 'tomato paste',
    'bread', 'bagel', 'tortilla', 'pita',
    'ketchup', 'mustard', 'mayonnaise', 'hot sauce', 'soy sauce',
    'syrup', 'molasses', 'agave', 'coffee', 'tea',
    'applesauce', 'fruit cup', 'fruit snack', 'juice box',
    'soda', 'water', 'sports drink', 'energy drink',
]

# Keywords that indicate perishable
PERISHABLE_KW = [
    'fresh', 'raw', 'refrigerat', 'milk', 'yogurt', 'cheese', 'butter',
    'egg', 'meat', 'chicken', 'beef', 'pork', 'turkey', 'fish', 'shrimp',
    'lettuce', 'spinach', 'salad greens', 'broccoli', 'cauliflower',
    'strawberr', 'blueberr', 'raspberr', 'grape', 'banana', 'avocado',
    'tofu', 'tempeh', 'deli', 'cold cut', 'lunch meat',
]

def is_shelf_stable(desc, cat1):
    if not desc or not isinstance(desc, str):
        return False
    d = desc.lower()
    for kw in PERISHABLE_KW:
        if kw in d:
            return False
    for kw in SHELF_STABLE_KW:
        if kw in d:
            return True
    return NONPERISHABLE_CATS.get(cat1, False)

def integrate():
    print('=' * 60)
    print('Integrating FoodAPS data into WWEIA database')
    print('=' * 60)

    # --- Load FoodAPS data ---
    print('Loading FoodAPS household data...')
    hh = pd.read_csv(os.path.join(BASE, 'faps_household_puf.csv'),
        usecols=['hhnum','rural','primstoretype','shopconv','shopbigbox','shopdollar','region'],
        encoding='latin1')

    # Classify households by store type
    hh['is_rural']        = hh['rural'] == 1
    hh['is_supermarket']  = hh['primstoretype'].isin(SUPERMARKET_CODES)
    hh['is_supercenter']  = hh['primstoretype'].isin(SUPERCENTER_CODES)
    hh['is_convenience']  = (hh['primstoretype'].isin(CONVENIENCE_CODES)) | (hh['shopconv'] == 1)
    hh['is_dollar']       = (hh['primstoretype'].isin(DOLLAR_CODES))
    print(f'  {len(hh)} households, {hh["is_rural"].sum()} rural')

    # --- Load FoodAPS items for price data ---
    print('Loading FoodAPS FAH items (prices)...')
    fah = pd.read_csv(os.path.join(BASE, 'faps_fahitem_puf.csv'),
        usecols=['hhnum','eventid','itemnum','totgramsunadj','totitemexp'],
        encoding='latin1')
    fah = fah[(fah['totitemexp'] > 0) & (fah['totgramsunadj'] > 0)].copy()
    fah['price_per_100g'] = (fah['totitemexp'] / fah['totgramsunadj']) * 100
    # Cap at $20/100g to remove outliers
    fah = fah[fah['price_per_100g'] <= 20]
    print(f'  {len(fah)} items with valid price+grams')

    # --- Load FoodAPS nutrients for food codes and descriptions ---
    print('Loading FoodAPS nutrient/food code data...')
    nutr = pd.read_csv(os.path.join(BASE, 'faps_fahnutrients.csv'),
        usecols=['hhnum','eventid','itemnum','foodcode','usdadescmain','usdafoodcat1',
                 'totgramsunadj','energy'],
        encoding='latin1')
    nutr['foodcode'] = nutr['foodcode'].astype('Int64')
    nutr = nutr.dropna(subset=['foodcode'])
    print(f'  {len(nutr)} nutrient records, {nutr["foodcode"].nunique()} unique food codes')

    # Build food code -> description and category map
    food_info = nutr[['foodcode','usdadescmain','usdafoodcat1']].dropna(subset=['usdadescmain'])
    food_info = food_info.drop_duplicates('foodcode').set_index('foodcode')
    print(f'  {len(food_info)} food codes with descriptions')

    # --- Merge items with nutrients to get food code per item ---
    print('Merging items with food codes...')
    nutr_key = nutr[['hhnum','eventid','itemnum','foodcode','usdafoodcat1']]
    merged = fah.merge(nutr_key, on=['hhnum','eventid','itemnum'], how='inner')
    merged = merged.merge(hh[['hhnum','is_rural','is_supermarket','is_supercenter',
                               'is_convenience','is_dollar']], on='hhnum', how='left')
    print(f'  {len(merged)} merged records')

    # --- Compute price per 100g by food code + store context ---
    print('Computing price statistics by food code...')

    # Overall median price per 100g by food code
    price_overall = merged.groupby('foodcode')['price_per_100g'].agg(
        price_median='median', price_mean='mean', price_obs='count'
    ).reset_index()

    # Rural price
    price_rural = merged[merged['is_rural']].groupby('foodcode')['price_per_100g'].median().reset_index()
    price_rural.columns = ['foodcode','price_rural_median']

    # Convenience store price
    price_conv = merged[merged['is_convenience']].groupby('foodcode')['price_per_100g'].median().reset_index()
    price_conv.columns = ['foodcode','price_conv_median']

    # Supercenter price
    price_super = merged[merged['is_supercenter']].groupby('foodcode')['price_per_100g'].median().reset_index()
    price_super.columns = ['foodcode','price_super_median']

    # Availability flags: food appears in rural / convenience / grocery purchases
    avail = merged.groupby('foodcode').agg(
        bought_rural=('is_rural','any'),
        bought_convenience=('is_convenience','any'),
        bought_supercenter=('is_supercenter','any'),
        bought_supermarket=('is_supermarket','any'),
        bought_dollar=('is_dollar','any'),
    ).reset_index()

    # Combine all price info
    prices = price_overall.merge(price_rural, on='foodcode', how='left')
    prices = prices.merge(price_conv, on='foodcode', how='left')
    prices = prices.merge(price_super, on='foodcode', how='left')
    prices = prices.merge(avail, on='foodcode', how='left')
    print(f'  Price data for {len(prices)} food codes')
    print(f'  Rural availability: {prices["bought_rural"].sum()} food codes')
    print(f'  Convenience availability: {prices["bought_convenience"].sum()} food codes')

    return food_info, prices

def update_database(food_info, prices):
    print('Updating SQLite database...')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add new columns if needed
    new_cols = [
        ('faps_description', 'TEXT'),
        ('faps_food_cat1', 'INTEGER'),
        ('price_per_100g_median', 'REAL'),
        ('price_per_100g_rural', 'REAL'),
        ('price_per_100g_conv', 'REAL'),
        ('price_per_100g_super', 'REAL'),
        ('price_obs', 'INTEGER'),
        ('bought_rural', 'INTEGER'),
        ('bought_convenience', 'INTEGER'),
        ('bought_supercenter', 'INTEGER'),
        ('bought_supermarket', 'INTEGER'),
        ('bought_dollar', 'INTEGER'),
        ('faps_shelf_stable', 'INTEGER'),
    ]
    for col, coltype in new_cols:
        try:
            c.execute(f'ALTER TABLE foods ADD COLUMN {col} {coltype}')
        except:
            pass

    # Update from prices dataframe
    updated = 0
    for _, row in prices.iterrows():
        fc = int(row['foodcode'])
        # Get description and cat from food_info
        if fc in food_info.index:
            fi = food_info.loc[fc]
            desc = fi['usdadescmain'] if isinstance(fi['usdadescmain'], str) else None
            cat1 = int(fi['usdafoodcat1']) if not pd.isna(fi.get('usdafoodcat1', float('nan'))) else None
        else:
            desc = None
            cat1 = None

        shelf = 1 if is_shelf_stable(desc, cat1) else 0

        c.execute('''
            UPDATE foods SET
                faps_description    = ?,
                faps_food_cat1      = ?,
                price_per_100g_median = ?,
                price_per_100g_rural  = ?,
                price_per_100g_conv   = ?,
                price_per_100g_super  = ?,
                price_obs             = ?,
                bought_rural          = ?,
                bought_convenience    = ?,
                bought_supercenter    = ?,
                bought_supermarket    = ?,
                bought_dollar         = ?,
                faps_shelf_stable     = ?
            WHERE food_code = ?
        ''', (
            desc,
            cat1,
            round(float(row['price_median']), 4) if not pd.isna(row['price_median']) else None,
            round(float(row['price_rural_median']), 4) if not pd.isna(row.get('price_rural_median', float('nan'))) else None,
            round(float(row['price_conv_median']), 4) if not pd.isna(row.get('price_conv_median', float('nan'))) else None,
            round(float(row['price_super_median']), 4) if not pd.isna(row.get('price_super_median', float('nan'))) else None,
            int(row['price_obs']) if not pd.isna(row['price_obs']) else 0,
            int(row['bought_rural']) if not pd.isna(row.get('bought_rural', float('nan'))) else 0,
            int(row['bought_convenience']) if not pd.isna(row.get('bought_convenience', float('nan'))) else 0,
            int(row['bought_supercenter']) if not pd.isna(row.get('bought_supercenter', float('nan'))) else 0,
            int(row['bought_supermarket']) if not pd.isna(row.get('bought_supermarket', float('nan'))) else 0,
            int(row['bought_dollar']) if not pd.isna(row.get('bought_dollar', float('nan'))) else 0,
            shelf,
            fc,
        ))
        if c.rowcount > 0:
            updated += 1

    conn.commit()
    print(f'Updated {updated} food codes in database')

    # Summary
    print()
    for label, sql in [
        ('Total foods',                  'SELECT COUNT(*) FROM foods WHERE energy_kcal > 0'),
        ('With FoodAPS description',     'SELECT COUNT(*) FROM foods WHERE faps_description IS NOT NULL'),
        ('With real price data',         'SELECT COUNT(*) FROM foods WHERE price_per_100g_median IS NOT NULL'),
        ('Bought rural (FoodAPS)',        'SELECT COUNT(*) FROM foods WHERE bought_rural = 1'),
        ('Bought at convenience store',  'SELECT COUNT(*) FROM foods WHERE bought_convenience = 1'),
        ('Shelf-stable (FoodAPS)',        'SELECT COUNT(*) FROM foods WHERE faps_shelf_stable = 1'),
    ]:
        c.execute(sql)
        print(f'  {label}: {c.fetchone()[0]}')

    print()
    print('Sample foods with real prices:')
    rows = c.execute('''
        SELECT COALESCE(faps_description, description) as name,
               price_per_100g_median, price_per_100g_rural, bought_rural,
               bought_convenience, food_category
        FROM foods
        WHERE price_per_100g_median IS NOT NULL AND energy_kcal > 50
        ORDER BY price_per_100g_median ASC LIMIT 15
    ''').fetchall()
    for r in rows:
        rural = 'rural' if r[3] else ''
        conv  = 'conv'  if r[4] else ''
        print(f'  ${r[1]:.2f}/100g {r[0]} [{r[5]}] {rural} {conv}')

    conn.close()

if __name__ == '__main__':
    food_info, prices = integrate()
    update_database(food_info, prices)
    print('Done!')
