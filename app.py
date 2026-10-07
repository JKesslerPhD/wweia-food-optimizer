#!/usr/bin/env python3
"""WWEIA Food Optimizer - with FoodAPS real prices, descriptions, rural/store flags."""
import sqlite3, os, math
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from ortools.linear_solver import pywraplp

app = Flask(__name__)
# When served under a reverse proxy at a subpath, trust the forwarded headers
# so url_for() and redirects generate correct /food/... paths.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_prefix=1)
DB_PATH = os.environ.get('WWEIA_DB', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'wweia_full.db'))

NUTRITION_PROFILES = {
    'optimal': {
        'protein_g': 1.0, 'fiber_g': 1.0, 'calcium_mg': 1.0,
        'iron_mg': 1.0, 'vitamin_c_mg': 1.0, 'vitamin_d_ug': 1.0,
        'potassium_mg': 0.75, 'zinc_mg': 0.75, 'magnesium_mg': 0.75,
        'folate_total_ug': 0.75, 'vitamin_b12_ug': 0.75, 'choline_mg': 0.5,
    },
    'reduced': {
        'protein_g': 0.5, 'fiber_g': 0.5, 'calcium_mg': 0.25,
        'iron_mg': 0.25, 'vitamin_c_mg': 0.25, 'vitamin_d_ug': 0.25,
        'potassium_mg': 0.25, 'zinc_mg': 0.0, 'magnesium_mg': 0.0,
        'folate_total_ug': 0.0, 'vitamin_b12_ug': 0.0, 'choline_mg': 0.0,
    },
    'none': {},
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_price(f, store):
    """Get best price for food given store context."""
    if store == 'convenience' and f.get('price_per_100g_conv'):
        return f['price_per_100g_conv']
    if store == 'rural' and f.get('price_per_100g_rural'):
        return f['price_per_100g_rural']
    if store == 'supercenter' and f.get('price_per_100g_super'):
        return f['price_per_100g_super']
    if f.get('price_per_100g_median'):
        return f['price_per_100g_median']
    return f.get('est_price_per_100g') or 0.50

def compute_dri(weight_kg=70.0, days=1.0):
    d, w = days, weight_kg
    return {
        'protein_g':         {'min': 0.8*w*d,    'max': 2.5*w*d,    'label': 'Protein',       'unit': 'g'},
        'total_fat_g':       {'min': None,        'max': None,       'label': 'Total Fat',     'unit': 'g'},
        'carbohydrate_g':    {'min': 130*d,       'max': None,       'label': 'Carbs',         'unit': 'g'},
        'fiber_g':           {'min': 25*d,        'max': None,       'label': 'Fiber',         'unit': 'g'},
        'total_sugars_g':    {'min': None,        'max': 50*d,       'label': 'Total Sugars',  'unit': 'g'},
        'calcium_mg':        {'min': 1000*d,      'max': 2500*d,     'label': 'Calcium',       'unit': 'mg'},
        'iron_mg':           {'min': 8*d,         'max': 45*d,       'label': 'Iron',          'unit': 'mg'},
        'magnesium_mg':      {'min': 4*w*d,       'max': None,       'label': 'Magnesium',     'unit': 'mg'},
        'phosphorus_mg':     {'min': 700*d,       'max': 4000*d,     'label': 'Phosphorus',    'unit': 'mg'},
        'potassium_mg':      {'min': 2600*d,      'max': None,       'label': 'Potassium',     'unit': 'mg'},
        'zinc_mg':           {'min': 8*d,         'max': 40*d,       'label': 'Zinc',          'unit': 'mg'},
        'vitamin_c_mg':      {'min': 75*d,        'max': None,       'label': 'Vitamin C',     'unit': 'mg'},
        'vitamin_a_rae_ug':  {'min': 700*d,       'max': 3000*d,     'label': 'Vitamin A',     'unit': 'ug'},
        'vitamin_d_ug':      {'min': 15*d,        'max': 100*d,      'label': 'Vitamin D',     'unit': 'ug'},
        'vitamin_e_mg':      {'min': 15*d,        'max': 1000*d,     'label': 'Vitamin E',     'unit': 'mg'},
        'thiamin_mg':        {'min': 1.1*d,       'max': None,       'label': 'Thiamin',       'unit': 'mg'},
        'riboflavin_mg':     {'min': 1.1*d,       'max': None,       'label': 'Riboflavin',    'unit': 'mg'},
        'niacin_mg':         {'min': 14*d,        'max': 35*d,       'label': 'Niacin',        'unit': 'mg'},
        'vitamin_b6_mg':     {'min': 1.3*d,       'max': 100*d,      'label': 'Vitamin B6',    'unit': 'mg'},
        'folate_total_ug':   {'min': 400*d,       'max': 1000*d,     'label': 'Folate',        'unit': 'ug'},
        'vitamin_b12_ug':    {'min': 2.4*d,       'max': None,       'label': 'Vitamin B12',   'unit': 'ug'},
        'vitamin_k_ug':      {'min': 90*d,        'max': None,       'label': 'Vitamin K',     'unit': 'ug'},
        'choline_mg':        {'min': 425*d,       'max': 3500*d,     'label': 'Choline',       'unit': 'mg'},
        'sodium_mg':         {'min': None,        'max': None,       'label': 'Sodium',        'unit': 'mg'},
        'cholesterol_mg':    {'min': None,        'max': None,       'label': 'Cholesterol',   'unit': 'mg'},
        'alcohol_g':         {'min': None,        'max': 0,          'label': 'Alcohol',       'unit': 'g'},
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/methodology')
def methodology():
    return render_template('methodology.html')

@app.route('/api/dri')
def api_dri():
    w = float(request.args.get('weight_kg', 70))
    d = float(request.args.get('days', 1))
    return jsonify(compute_dri(w, d))

VALID_DIETARY = {'vegan','vegetarian','dairy_free','gluten_free','nut_free','shellfish_free','egg_free','soy_free'}

@app.route('/api/foods')
def api_foods():
    q             = request.args.get('q','').strip()
    no_cook       = request.args.get('no_cook','0')
    shelf_stable  = request.args.get('shelf_stable','0')
    store         = request.args.get('store','')
    page          = int(request.args.get('page', 1))
    per_page      = int(request.args.get('per_page', 50))
    sort          = request.args.get('sort','calorie_density')
    offset        = (page-1)*per_page
    dietary_raw   = request.args.get('dietary','')
    dietary       = [d.strip() for d in dietary_raw.split(',') if d.strip() in VALID_DIETARY]

    conditions = ['energy_kcal > 0', '(is_prepared_dish IS NULL OR is_prepared_dish = 0)']
    params = []

    if q:
        conditions.append('(description LIKE ? OR faps_description LIKE ?)')
        params += [f'%{q}%', f'%{q}%']
    if no_cook == '1':
        conditions.append('no_cook = 1')
    if shelf_stable == '1':
        conditions.append('(non_perishable = 1 OR faps_shelf_stable = 1)')
    if store == 'convenience':
        conditions.append('(convenience_store = 1 OR bought_convenience = 1)')
    elif store == 'grocery':
        conditions.append('(grocery_store = 1 OR bought_supermarket = 1)')
    elif store == 'rural':
        conditions.append('(rural_available = 1 OR bought_rural = 1)')
    elif store == 'supercenter':
        conditions.append('bought_supercenter = 1')
    elif store == 'dollar':
        conditions.append('bought_dollar = 1')
    for d in dietary:
        conditions.append(f'is_{d} = 1')

    where = 'WHERE ' + ' AND '.join(conditions)
    valid_sorts = {
        'calorie_density':'calorie_density DESC',
        'calories':'energy_kcal DESC',
        'protein':'protein_g DESC',
        'price':'COALESCE(price_per_100g_median, est_price_per_100g, 0.5) ASC',
        'popularity':'intake_count DESC',
        'description':'description ASC',
    }
    order = valid_sorts.get(sort,'calorie_density DESC')

    conn = get_db()
    total = conn.execute(f'SELECT COUNT(*) FROM foods {where}', params).fetchone()[0]
    rows  = conn.execute(
        f'SELECT *, COALESCE(faps_description, faps_usda_description, description) as display_name,'
        f' COALESCE(price_per_100g_median, est_price_per_100g, 0.50) * COALESCE(price_inflation_multiplier, 1.45) as effective_price'
        f' FROM foods {where} ORDER BY {order} LIMIT ? OFFSET ?',
        params + [per_page, offset]).fetchall()
    conn.close()
    return jsonify({'foods':[dict(r) for r in rows], 'total':total, 'page':page,
                    'per_page':per_page, 'pages':max(1,math.ceil(total/per_page))})

@app.route('/api/food/<int:food_code>')
def api_food_detail(food_code):
    conn = get_db()
    row = conn.execute(
        'SELECT *, COALESCE(faps_description, faps_usda_description, description) as display_name,'
        ' COALESCE(price_per_100g_median, est_price_per_100g, 0.50) * COALESCE(price_inflation_multiplier, 1.45) as effective_price'
        ' FROM foods WHERE food_code=?', (food_code,)).fetchone()
    conn.close()
    if not row: return jsonify({'error':'Not found'}), 404
    return jsonify({'food': dict(row)})

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    stats = {}
    for lbl, sql in [
        ('total_foods',         'SELECT COUNT(*) FROM foods WHERE energy_kcal>0'),
        ('no_cook',             'SELECT COUNT(*) FROM foods WHERE no_cook=1 AND energy_kcal>0'),
        ('shelf_stable',        'SELECT COUNT(*) FROM foods WHERE (non_perishable=1 OR faps_shelf_stable=1) AND energy_kcal>0'),
        ('rural',               'SELECT COUNT(*) FROM foods WHERE (rural_available=1 OR bought_rural=1) AND energy_kcal>0'),
        ('convenience_store',   'SELECT COUNT(*) FROM foods WHERE (convenience_store=1 OR bought_convenience=1) AND energy_kcal>0'),
        ('grocery_store',       'SELECT COUNT(*) FROM foods WHERE (grocery_store=1 OR bought_supermarket=1) AND energy_kcal>0'),
        ('with_real_prices',    'SELECT COUNT(*) FROM foods WHERE price_per_100g_median IS NOT NULL'),
    ]:
        stats[lbl] = conn.execute(sql).fetchone()[0]
    top = conn.execute('''
        SELECT COALESCE(faps_description,description) as name,
               calorie_density, energy_kcal, protein_g, food_category,
               COALESCE(price_per_100g_median, est_price_per_100g, 0.50) as price
        FROM foods
        WHERE (non_perishable=1 OR faps_shelf_stable=1)
          AND no_cook=1 AND energy_kcal>0
        ORDER BY calorie_density DESC LIMIT 20''').fetchall()
    stats['top_calorie_dense'] = [dict(r) for r in top]
    conn.close()
    return jsonify(stats)

@app.route('/api/optimize', methods=['POST'])
def api_optimize():
    """
    GLOP LP optimizer.
    Decision variables: grams_i for each food i.
    TRUE calorie density objective: minimize total grams subject to calorie target.
    This gives the lightest basket that meets your calorie goal = maximum kcal/g.
    """
    data = request.get_json() or {}

    objective       = data.get('objective', 'calorie_density')
    no_cook         = data.get('no_cook', True)
    shelf_stable    = data.get('shelf_stable', True)
    store           = data.get('store', 'grocery')
    cal_per_day     = float(data.get('calories_per_day', 2000))
    days            = float(data.get('days', 7))
    weight_kg       = float(data.get('weight_kg', 70))
    diversity       = float(data.get('diversity', 0.3))
    nutr_profile    = data.get('nutrition_profile', 'optimal')
    nutr_scales     = data.get('nutrient_scales', NUTRITION_PROFILES.get(nutr_profile, {}))
    selected_ids    = data.get('selected_food_ids', None)
    blocked_ids     = data.get('blocked_food_ids', None) or []
    capped_foods    = data.get('capped_foods', {})  # food_code (str) -> max_grams
    no_chocolate    = data.get('no_chocolate', False)
    candy_boost     = float(data.get('candy_boost', 0.0))      # 0–1: fraction of cals from Sweets
    max_item_grams  = float(data.get('max_item_grams', 0.0))   # 0 = no limit
    dietary_raw     = data.get('dietary_restrictions', [])
    dietary         = [d for d in dietary_raw if d in VALID_DIETARY]

    # Calorie bounds for whole period (tight ±3%)
    total_cal_lo = cal_per_day * days * 0.97
    total_cal_hi = cal_per_day * days * 1.03

    # Max grams per food — relaxed when diversity minimum is active so the
    # solver has room to spread calories across many items without hitting
    # an individual food cap. At diversity=0 the old 40% cap applies; at
    # diversity=1 we allow up to 100% of total calories from one food
    # (the category cap and minimum-items constraint do the real work).
    diversity_cap = max(0.40, min(1.0, 0.40 + diversity * 0.60))
    max_g_per_food = (cal_per_day * days * diversity_cap) / 3.0

    # Compute DRI for period and apply nutrition scales.
    # nutr_scales controls which nutrients get min constraints and how strict.
    # If nutr_profile is 'none', nutr_scales is empty — we skip ALL nutrient min constraints.
    # Upper-bound (max) constraints are only applied when profile is not 'none',
    # to avoid infeasibility from e.g. alcohol_g max=0 conflicting with calorie density goals.
    apply_nutrient_constraints = (nutr_profile != 'none')
    dri = compute_dri(weight_kg, days)
    for nutrient, scale in nutr_scales.items():
        if nutrient in dri:
            mn = dri[nutrient]['min']
            dri[nutrient]['min'] = mn * float(scale) if mn else None

    # Build food candidate list
    conn = get_db()
    conditions = ['energy_kcal > 0', '(is_prepared_dish IS NULL OR is_prepared_dish = 0)']
    params = []
    if no_cook:     conditions.append('no_cook = 1')
    if shelf_stable:conditions.append('(non_perishable=1 OR faps_shelf_stable=1)')
    if store == 'convenience': conditions.append('(convenience_store=1 OR bought_convenience=1)')
    elif store == 'grocery':   conditions.append('(grocery_store=1 OR bought_supermarket=1)')
    elif store == 'rural':     conditions.append('(rural_available=1 OR bought_rural=1)')
    elif store == 'supercenter':conditions.append('bought_supercenter=1')
    elif store == 'dollar':    conditions.append('bought_dollar=1')
    # Perishability: exclude foods that won't last the full planning window.
    # Non-perishable foods bypass this check entirely -- days_without_refrigeration=0
    # in the USDA data is a data artifact for many truly shelf-stable items (nuts, etc.)
    # and should not cause them to be excluded when non_perishable=1.
    if days > 1:
        conditions.append(
            '(non_perishable = 1 OR days_without_refrigeration IS NULL OR days_without_refrigeration >= ?)'
        )
        params.append(int(days))
    if selected_ids:
        ph = ','.join(['?']*len(selected_ids))
        conditions.append(f'food_code IN ({ph})')
        params.extend(selected_ids)
    if blocked_ids:
        ph = ','.join(['?']*len(blocked_ids))
        conditions.append(f'food_code NOT IN ({ph})')
        params.extend(blocked_ids)
    if no_chocolate:
        conditions.append("COALESCE(faps_description, faps_usda_description, description) NOT LIKE '%chocolate%'")
        conditions.append("COALESCE(faps_description, faps_usda_description, description) NOT LIKE '%cocoa%'")
    for d in dietary:
        conditions.append(f'is_{d} = 1')

    where = 'WHERE ' + ' AND '.join(conditions)
    foods = [dict(r) for r in conn.execute(
        f'SELECT *, COALESCE(faps_description, faps_usda_description, description) as display_name,'
        f' COALESCE(price_per_100g_median, est_price_per_100g, 0.50) * COALESCE(price_inflation_multiplier, 1.45) as effective_price'
        f' FROM foods {where} ORDER BY calorie_density DESC', params).fetchall()]
    conn.close()

    # Deduplicate near-identical food variants (e.g. "Pecans, NFS" / "Pecans, unroasted" / "Pecans, unsalted").
    # For groups sharing the same base name AND calorie density within 15%, keep the best-documented item.
    import re as _re
    def _food_base(f):
        base = (f.get('display_name') or f['description']).split(',')[0].strip().lower()
        base = _re.sub(r'\s*\([^)]+\)\s*$', '', base)  # strip trailing (Brand Name)
        return _re.sub(r'\b(nfs|regular|plain)\b', '', base).strip()

    _buckets = {}
    for _f in foods:
        _buckets.setdefault(_food_base(_f), []).append(_f)

    _deduped = []
    for _grp in _buckets.values():
        if len(_grp) == 1:
            _deduped.append(_grp[0])
            continue
        _pos = [_f.get('calorie_density') or 0 for _f in _grp if (_f.get('calorie_density') or 0) > 0]
        if _pos and max(_pos) / max(min(_pos), 0.001) <= 1.15:
            _deduped.append(sorted(_grp, key=lambda _f: (
                1 if _f.get('price_per_100g_median') else 0,
                _f.get('intake_count') or 0
            ), reverse=True)[0])
        else:
            _deduped.extend(_grp)
    foods = _deduped

    if not foods:
        return jsonify({'error':'No foods match filters (perishability or other filters may be too restrictive). '
                        'Try reducing the number of days or relaxing shelf-stable filters.',
                        'candidate_count':0,
                        'cal_target':{'lo':total_cal_lo,'hi':total_cal_hi}})

    def coeff(f, col):
        """Per-gram nutrient coefficient (DB stores per 100g)."""
        return (f.get(col) or 0.0) / 100.0

    # Categories for category-cap diversity constraint
    cats = list(set((f.get('food_category') or 'Other') for f in foods))
    num_cats = max(len(cats), 1)

    # Minimum number of distinct foods required by diversity slider.
    # Slider 0→no minimum, 1.0→20 foods. Capped at candidate count.
    min_foods = 0
    if diversity > 0.05:
        raw_min = round(diversity * 20)   # 0.1→2, 0.5→10, 1.0→20
        min_foods = min(raw_min, len(foods))

    # GLOP (LP) only — no SCIP/MIP. Diversity is enforced by capping each food's
    # calorie contribution to total_calories / min_foods. This forces the LP to
    # spread across at least min_foods items to meet the calorie target, without
    # needing binary indicator variables.
    solver = pywraplp.Solver.CreateSolver('GLOP')
    solver.SuppressOutput()

    # Decision vars: grams of each food.
    # When min_foods > 0, cap each food to total_cal / min_foods calories.
    # This forces the LP to use at least min_foods foods to hit the calorie target.
    # When diversity is off, fall back to the global abs_ub.
    total_cal_mid = (total_cal_lo + total_cal_hi) / 2.0
    abs_ub = min(max_g_per_food, max_item_grams) if max_item_grams > 0 else max_g_per_food
    gvars = {}
    for f in foods:
        if min_foods > 0:
            cd = max(f.get('calorie_density') or 0.001, 0.001)
            ub = (total_cal_mid / min_foods) / cd
            if max_item_grams > 0:
                ub = min(ub, max_item_grams)
        else:
            ub = abs_ub
        gvars[f['food_code']] = solver.NumVar(0.0, ub, f"g_{f['food_code']}")
    # Apply per-food upper bound caps from user overrides.
    for fc_str, cap_g in capped_foods.items():
        fc = int(fc_str)
        if fc in gvars:
            gvars[fc].SetUb(min(float(cap_g), gvars[fc].ub()))

    # CALORIE CONSTRAINT: sum(kcal/100 * g) in [lo, hi]
    cal_ct = solver.Constraint(total_cal_lo, total_cal_hi)
    for f in foods:
        cal_ct.SetCoefficient(gvars[f['food_code']], coeff(f, 'energy_kcal'))

    # NUTRIENT CONSTRAINTS from DRI * scale
    # Only apply when profile is not 'none'. Upper-bound (max) constraints are also
    # skipped for 'none' to avoid e.g. alcohol_g<=0 creating infeasibility.
    relaxed_nutrients = []
    if apply_nutrient_constraints:
        for nutrient, d in dri.items():
            lo = d.get('min')
            hi = d.get('max')
            if lo and lo > 0:
                # Feasibility guard: compute max achievable for this nutrient across all foods.
                # If even filling every food to its individual max_g_per_food can't hit lo,
                # skip this constraint (it would make the problem infeasible).
                max_achievable = sum(coeff(f, nutrient) * max_g_per_food for f in foods)
                if max_achievable < lo * 0.5:
                    # Can't get within 50% of target — skip to avoid guaranteed infeasibility
                    relaxed_nutrients.append(nutrient)
                    continue
                ct = solver.Constraint(float(lo), solver.infinity())
                for f in foods:
                    ct.SetCoefficient(gvars[f['food_code']], coeff(f, nutrient))
            if hi is not None and hi >= 0:
                ct = solver.Constraint(-solver.infinity(), float(hi))
                for f in foods:
                    ct.SetCoefficient(gvars[f['food_code']], coeff(f, nutrient))

    # DIVERSITY CONSTRAINTS
    if diversity > 0.05 and num_cats > 1:
        total_cal_budget = (total_cal_lo + total_cal_hi) / 2.0
        # 1. Category calorie cap: no single category can dominate the basket.
        max_cat_fraction = 1.0 - (diversity * 0.55)
        max_cat_kcal = total_cal_budget * max_cat_fraction
        for cat in cats:
            cat_foods = [f for f in foods if (f.get('food_category') or 'Other') == cat]
            if len(cat_foods) < 2: continue
            ct = solver.Constraint(-solver.infinity(), max_cat_kcal)
            for f in cat_foods:
                ct.SetCoefficient(gvars[f['food_code']], coeff(f, 'energy_kcal'))

    # CANDY BOOST: require a minimum fraction of calories from Sweets category.
    # candy_boost=0.5 → ≥10% of calories from Sweets; candy_boost=1.0 → ≥20%.
    if candy_boost > 0.01:
        candy_foods = [f for f in foods if f.get('food_code', 0) >= 91700000]
        if candy_foods:
            candy_min_kcal = (total_cal_lo + total_cal_hi) / 2.0 * (candy_boost * 0.20)
            ct = solver.Constraint(candy_min_kcal, solver.infinity())
            for f in candy_foods:
                ct.SetCoefficient(gvars[f['food_code']], coeff(f, 'energy_kcal'))
    # OBJECTIVE
    obj = solver.Objective()
    if objective == 'calorie_density':
        # TRUE calorie density maximization:
        # Minimize total grams subject to calorie target.
        # Fewer grams to hit the same calories = higher kcal/g.
        for f in foods:
            obj.SetCoefficient(gvars[f['food_code']], 1.0)
        obj.SetMinimization()
    elif objective == 'cost':
        for f in foods:
            obj.SetCoefficient(gvars[f['food_code']], (f.get('effective_price') or 0.5) / 100.0)
        obj.SetMinimization()
    elif objective == 'diversity':
        cat_counts = {}
        for f in foods:
            c = f.get('food_category','Other') or 'Other'
            cat_counts[c] = cat_counts.get(c,0)+1
        for f in foods:
            c = f.get('food_category','Other') or 'Other'
            obj.SetCoefficient(gvars[f['food_code']], 1.0/max(cat_counts.get(c,1),1))
        obj.SetMaximization()
    else:
        # Maximize a specific nutrient
        for f in foods:
            obj.SetCoefficient(gvars[f['food_code']], coeff(f, objective))
        obj.SetMaximization()

    status = solver.Solve()
    STATUS = {
        pywraplp.Solver.OPTIMAL:'optimal', pywraplp.Solver.FEASIBLE:'feasible',
        pywraplp.Solver.INFEASIBLE:'infeasible', pywraplp.Solver.UNBOUNDED:'unbounded',
        pywraplp.Solver.ABNORMAL:'abnormal', pywraplp.Solver.NOT_SOLVED:'not_solved',
    }

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return jsonify({
            'status': STATUS.get(status,'unknown'),
            'error': 'No feasible solution. Try: more days, higher calories, lower nutrition profile, or switch store type.',
            'candidate_count': len(foods),
            'cal_target': {'lo':round(total_cal_lo,0),'hi':round(total_cal_hi,0)},
        })

    # Extract solution
    all_nutrients = list(dri.keys())
    solution_foods = []
    total_n = {n:0.0 for n in all_nutrients}
    total_g = total_cost = total_kcal = 0.0
    cats_used = set()
    perishable_count = nonperishable_count = 0

    for f in foods:
        g = gvars[f['food_code']].solution_value()
        if g < 0.5: continue

        # --- Purchase-unit rounding ---
        pkg_g      = f.get('typical_pkg_grams')
        pkg_price  = f.get('typical_pkg_price')
        price_g    = (f.get('effective_price') or 0.5) / 100.0

        if pkg_g and pkg_g > 0:
            num_pkgs  = g / pkg_g
            n_pkgs    = round(num_pkgs)
            if n_pkgs > 0:
                g_rounded = round(n_pkgs * pkg_g, 1)
                unit_s    = f.get('pkg_unit_singular') or 'pkg'
                unit_p    = f.get('pkg_unit_plural')   or 'pkgs'
                pkg_label = f'{n_pkgs} {unit_s if n_pkgs == 1 else unit_p}'
                if pkg_price and pkg_price > 0:
                    cost = round(n_pkgs * pkg_price, 2)
                else:
                    cost = round(g_rounded * price_g, 2)
            else:
                g_rounded = round(g, 1)
                n_pkgs    = None
                pkg_label = f'{g_rounded:.0f}g'
                cost      = round(g_rounded * price_g, 2)
        else:
            g_rounded = round(g, 1)
            n_pkgs    = None
            pkg_label = f'{g_rounded:.0f}g'
            cost      = round(g_rounded * price_g, 2)
        kcal = round(coeff(f, 'energy_kcal') * g_rounded, 1)

        food_safe_days = f.get('days_without_refrigeration')
        stability_tier = f.get('stability_tier') or 'Unknown'
        is_perishable  = not (f.get('non_perishable') or f.get('faps_shelf_stable')) and (food_safe_days is None or food_safe_days == 0)
        if is_perishable:
            perishable_count += 1
        else:
            nonperishable_count += 1

        item = {
            'food_code':                 f['food_code'],
            'description':               f.get('display_name') or f['description'],
            'food_category':             f.get('food_category', 'Other'),
            'grams':                     g_rounded,
            'cost':                      cost,
            'kcal':                      kcal,
            'calorie_density':           round((f.get('calorie_density') or 0), 3),
            'price_per_100g':            round(f.get('effective_price') or 0.5, 3),
            'has_real_price':            f.get('price_per_100g_median') is not None,
            'bought_rural':              bool(f.get('bought_rural')),
            'bought_conv':               bool(f.get('bought_convenience')),
            'purchase_qty':              n_pkgs,
            'purchase_label':            pkg_label,
            'days_without_refrigeration': food_safe_days,
            'stability_tier':            stability_tier,
            'fndds_additional':          f.get('fndds_additional'),
            'purchase_examples':         f.get('faps_purchase_examples'),
            'nutrients':                 {},
        }
        for n in all_nutrients:
            val = round(coeff(f, n) * g_rounded, 3)
            item['nutrients'][n] = val
            total_n[n] = round(total_n.get(n, 0) + val, 3)
        total_g    += g_rounded
        total_cost += cost
        total_kcal += kcal
        cats_used.add(f.get('food_category', 'Other'))
        solution_foods.append(item)

    solution_foods.sort(key=lambda x: x['grams'], reverse=True)
    total_n = {k:round(v,2) for k,v in total_n.items()}

    dri_coverage = {}
    for n,d in dri.items():
        mn = d.get('min')
        dri_coverage[n] = round(total_n.get(n,0)/mn*100,1) if mn and mn>0 else None

    safe_days_values = [
        f['days_without_refrigeration']
        for f in solution_foods
        if f['days_without_refrigeration'] is not None
    ]
    basket = {
        'total_grams':         round(total_g, 1),
        'total_lbs':           round(total_g / 453.592, 2),
        'total_kg':            round(total_g / 1000, 2),
        'total_cost':          round(total_cost, 2),
        'total_kcal':          round(total_kcal, 1),
        'calorie_density':     round(total_kcal / max(total_g, 1), 3),
        'cost_per_1000kcal':   round(total_cost / max(total_kcal / 1000, 0.001), 2),
        'num_items':           len(solution_foods),
        'num_categories':      len(cats_used),
        'categories':          sorted(list(cats_used)),
        'days':                days,
        'cal_per_day':         cal_per_day,
        'target_kcal':         round(cal_per_day * days, 0),
        'perishable_items':    perishable_count,
        'nonperishable_items': nonperishable_count,
        'avg_food_safe_days':  round(sum(safe_days_values) / len(safe_days_values), 1) if safe_days_values else 0,
    }

    return jsonify({
        'status':             STATUS.get(status, 'unknown'),
        'objective':          objective,
        'num_foods':          len(solution_foods),
        'candidate_count':    len(foods),
        'foods':              solution_foods,
        'total_nutrients':    total_n,
        'dri_coverage':       dri_coverage,
        'dri':                {k:{'label':v['label'],'unit':v['unit'],'min':v['min'],'max':v['max']} for k,v in dri.items()},
        'basket':             basket,
        'relaxed_nutrients':  relaxed_nutrients,
        'min_foods_required': min_foods,
        'solver_used':        'GLOP',
    })

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory(app.static_folder, 'manifest.json'), 200, {
        'Content-Type': 'application/manifest+json'
    }

@app.route('/sw.js')
def serve_sw():
    return send_from_directory(app.static_folder, 'sw.js'), 200, {
        'Content-Type': 'application/javascript'
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', port=port)
