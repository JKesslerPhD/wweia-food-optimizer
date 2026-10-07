#!/usr/bin/env python3
"""
Integrate perishability data into wweia_full.db.

Sources:
  - WWEIA_Days_Without_Refrigeration.csv: category_number → days_without_refrigeration, stability_tier
  - WWEIA_August2021_August2023_foodcat_FNDDS.xlsx: food_code → category_number (concordance)

Adds columns:
  - days_without_refrigeration  INTEGER  (conservative lower-bound days food is safe without refrigeration)
  - stability_tier              TEXT     (e.g. "Shelf Stable", "Perishable", "Short-term Stable")
"""
import re
import pandas as pd
import sqlite3
import os

BASE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(BASE, 'wweia_full.db')
CSV_PATH  = os.path.join(BASE, 'WWEIA_Days_Without_Refrigeration.csv')
XLSX_PATH = os.path.join(BASE, 'WWEIA_August2021_August2023_foodcat_FNDDS.xlsx')


def parse_days_conservative(val):
    """
    Convert a days_without_refrigeration string to the conservative (lower-bound) integer.
    "0 days"    → 0
    "1-2 days"  → 1  (lower bound)
    "7-14 days" → 7
    "14+ days"  → 14
    "Varies"    → 0  (treat as unknown / potentially perishable)
    """
    if not isinstance(val, str):
        return 0
    # Remove parenthetical notes like "(opened)"
    cleaned = re.sub(r'\s*\([^)]*\)', '', val).strip()

    if cleaned == 'Varies':
        return 0

    # "14+ days"
    m = re.match(r'^(\d+)\+\s*days?$', cleaned)
    if m:
        return int(m.group(1))

    # "7-14+ days"
    m = re.match(r'^(\d+)-(\d+)\+\s*days?$', cleaned)
    if m:
        return int(m.group(1))

    # "1-2 days"
    m = re.match(r'^(\d+)-(\d+)\s*days?$', cleaned)
    if m:
        return int(m.group(1))

    # "1 day" or "0 days"
    m = re.match(r'^(\d+)\s*days?$', cleaned)
    if m:
        return int(m.group(1))

    return 0


def load_perishability():
    print('Loading perishability CSV...')
    df = pd.read_csv(CSV_PATH)
    df['days_safe'] = df['days_without_refrigeration'].apply(parse_days_conservative)

    # Build category_number → (days_safe, stability_tier)
    result = {}
    for _, row in df.iterrows():
        cat_num = int(row['category_number'])
        result[cat_num] = {
            'days_safe':      int(row['days_safe']),
            'stability_tier': str(row['stability_tier']).strip(),
        }
    print(f'  {len(result)} WWEIA category codes with perishability data')
    return result


def load_concordance():
    print('Loading food code concordance from XLSX...')
    xl = pd.read_excel(XLSX_PATH, sheet_name='Aug2021-Aug2023_FNDDS_foodcat',
                       usecols=['food_code', 'category_number'])
    xl = xl.dropna(subset=['food_code', 'category_number'])
    xl['food_code']       = xl['food_code'].astype(int)
    xl['category_number'] = xl['category_number'].astype(int)

    # One food_code can match multiple categories — take first (most common / survey-primary)
    concordance = xl.drop_duplicates('food_code').set_index('food_code')['category_number'].to_dict()
    print(f'  {len(concordance)} food_code → category_number mappings')
    return concordance


def update_db(perishability, concordance):
    print('Updating database...')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for col, dtype in [('days_without_refrigeration', 'INTEGER'),
                       ('stability_tier', 'TEXT')]:
        try:
            c.execute(f'ALTER TABLE foods ADD COLUMN {col} {dtype}')
            print(f'  Added column {col}')
        except Exception:
            print(f'  Column {col} already exists')

    # Fetch all food codes
    food_codes = [r[0] for r in c.execute('SELECT food_code FROM foods').fetchall()]
    print(f'  {len(food_codes)} foods in DB')

    updated = matched = 0
    for fc in food_codes:
        cat_num = concordance.get(fc)
        if cat_num is None:
            continue
        info = perishability.get(cat_num)
        if info is None:
            continue
        c.execute(
            'UPDATE foods SET days_without_refrigeration = ?, stability_tier = ? WHERE food_code = ?',
            (info['days_safe'], info['stability_tier'], fc)
        )
        matched += 1
        if info['days_safe'] > 0:
            updated += 1

    conn.commit()

    # Report results
    stats = conn.execute('''
        SELECT stability_tier, COUNT(*) as cnt,
               AVG(days_without_refrigeration) as avg_days
        FROM foods
        WHERE stability_tier IS NOT NULL
        GROUP BY stability_tier
        ORDER BY avg_days DESC
    ''').fetchall()

    total_matched = conn.execute(
        'SELECT COUNT(*) FROM foods WHERE days_without_refrigeration IS NOT NULL'
    ).fetchone()[0]
    total_foods = conn.execute('SELECT COUNT(*) FROM foods').fetchone()[0]

    conn.close()

    print(f'\nResults:')
    print(f'  Foods updated:         {matched} / {total_foods}')
    print(f'  Non-perishable (>0d):  {updated}')
    print(f'\nBy stability tier:')
    for tier, cnt, avg in stats:
        print(f'  {tier:<35s} {cnt:4d} foods  avg={avg:.1f}d')

    print(f'\nDB coverage: {total_matched}/{total_foods} foods have perishability data '
          f'({100*total_matched//total_foods}%)')


if __name__ == '__main__':
    perishability = load_perishability()
    concordance   = load_concordance()
    update_db(perishability, concordance)
    print('\nDone.')
