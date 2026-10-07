#!/usr/bin/env python3
"""Retag foods with convenience_store and grocery_store availability."""
import sqlite3, os

DB_PATH = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'), 'wweia_full.db')

# Convenience stores carry a limited, shelf-stable, ready-to-eat range
CONVENIENCE_KW = [
    'chips', 'pretzel', 'popcorn', 'cracker',
    'peanut', 'nuts', 'trail mix',
    'candy', 'chocolate', 'candy bar', 'gum',
    'jerky', 'beef jerky', 'turkey jerky', 'meat stick',
    'granola bar', 'protein bar', 'energy bar', 'cereal bar',
    'cookie', 'cracker sandwich',
    'peanut butter', 'cheese spread',
    'tuna, canned', 'sardine', 'spam',
    'bread', 'roll', 'hot dog bun', 'hamburger bun',
    'tortilla',
    'banana', 'apple', 'orange',
    'yogurt', 'string cheese', 'cheese stick',
    'milk', 'chocolate milk',
    'juice', 'juice drink', 'fruit punch', 'lemonade',
    'water', 'soda', 'sport drink', 'energy drink', 'coffee', 'tea',
    'hot dog', 'sausage', 'corn dog',
    'ramen', 'instant noodle',
    'sunflower seed', 'pumpkin seed',
    'honey bun', 'donut', 'muffin', 'danish',
    'raisin', 'dried fruit', 'fruit snack',
    'applesauce',
]

# Grocery stores carry everything convenience stores do plus much more
GROCERY_KW = CONVENIENCE_KW + [
    'almond', 'walnut', 'cashew', 'pecan', 'pistachio', 'macadamia',
    'almond butter', 'cashew butter', 'sunflower butter',
    'cereal', 'oat', 'granola', 'oatmeal',
    'rice', 'pasta', 'flour', 'cornmeal',
    'bagel', 'pita', 'english muffin', 'wrap',
    'canned', 'soup', 'beans', 'lentil', 'chickpea',
    'tomato sauce', 'tomato paste', 'salsa',
    'jam', 'jelly', 'honey', 'syrup', 'molasses',
    'peanut butter',
    'dried', 'prune', 'date', 'fig', 'apricot',
    'protein powder', 'supplement',
    'olive oil', 'vegetable oil', 'coconut oil',
    'vinegar', 'ketchup', 'mustard', 'mayonnaise', 'hot sauce', 'soy sauce',
    'sugar', 'salt', 'pepper',
    'hummus', 'guacamole',
    'pouch', 'shelf-stable', 'instant',
    'carrot', 'celery', 'lettuce', 'spinach', 'tomato', 'cucumber',
    'onion', 'potato', 'avocado', 'pepper',
    'apple', 'banana', 'orange', 'grape', 'strawberry', 'blueberry',
    'peach', 'pear', 'plum', 'cherry', 'mango', 'pineapple', 'melon',
    'egg', 'butter', 'margarine',
    'cheese', 'cottage cheese', 'cream cheese', 'yogurt',
    'milk', 'almond milk', 'soy milk', 'oat milk',
    'deli', 'ham', 'turkey breast', 'salami', 'bologna', 'cold cut',
    'hot dog', 'sausage',
    'frozen', 'ice cream',
]

def retag():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add new columns
    for col in ['convenience_store', 'grocery_store']:
        try:
            c.execute(f'ALTER TABLE foods ADD COLUMN {col} INTEGER DEFAULT 0')
            print(f'Added {col}')
        except:
            print(f'{col} already exists')
            c.execute(f'UPDATE foods SET {col} = 0')

    c.execute('SELECT food_code, description FROM foods')
    rows = c.fetchall()

    conv_count = 0
    groc_count = 0
    for food_code, desc in rows:
        d = desc.lower()
        is_conv = int(any(kw in d for kw in CONVENIENCE_KW))
        is_groc = int(any(kw in d for kw in GROCERY_KW))
        if is_conv: conv_count += 1
        if is_groc: groc_count += 1
        c.execute('UPDATE foods SET convenience_store=?, grocery_store=? WHERE food_code=?',
                  (is_conv, is_groc, food_code))

    conn.commit()
    print(f'Convenience store: {conv_count} foods')
    print(f'Grocery store:     {groc_count} foods')

    # Show breakdown with no_cook + non_perishable
    for label, sql in [
        ('Conv + no-cook + non-perish', 'SELECT COUNT(*) FROM foods WHERE convenience_store=1 AND no_cook=1 AND non_perishable=1'),
        ('Groc + no-cook + non-perish', 'SELECT COUNT(*) FROM foods WHERE grocery_store=1 AND no_cook=1 AND non_perishable=1'),
    ]:
        c.execute(sql)
        print(f'  {label}: {c.fetchone()[0]}')

    conn.close()

if __name__ == '__main__':
    retag()
