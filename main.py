#!/usr/bin/env python3
from scrapers.immofux import ImmofuxScraper
from normalizer import normalize_listing
from scoring import score_listing
from exporter_gsheets import export_to_sheet
from geocode import geocode_item
import json
import os
from datetime import datetime

STORAGE_PATH = 'storage/db.json'
SEARCH_URL = 'https://immofux.de/'

# Thresholds (anpassbar)
MIN_LIVING_M2 = 90
MIN_LAND_M2 = 1000
MIN_ROOMS = 2
MAX_PRICE = 400000
# approximate distance threshold in km (2 hours ~ 180 km at avg 90 km/h)
MAX_DISTANCE_KM = 180

def load_db():
    if os.path.exists(STORAGE_PATH):
        with open(STORAGE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'seen': {}, 'listings': []}

def save_db(db):
    os.makedirs(os.path.dirname(STORAGE_PATH), exist_ok=True)
    with open(STORAGE_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def matches_must_criteria(item):
    reasons = []

    # price
    if item.get('price_eur') is None:
        reasons.append('no_price')
    else:
        try:
            if item['price_eur'] > MAX_PRICE:
                reasons.append('price>max')
        except Exception:
            reasons.append('price_parse_error')

    # living area
    if item.get('living_m2') is None:
        reasons.append('no_living_m2')
    else:
        try:
            if item['living_m2'] < MIN_LIVING_M2:
                reasons.append('living_too_small')
        except Exception:
            reasons.append('living_parse_error')

    # land area (only check if present)
    if item.get('land_m2') is None:
        reasons.append('no_land_m2')
    else:
        try:
            if item['land_m2'] < MIN_LAND_M2:
                reasons.append('land_too_small')
        except Exception:
            reasons.append('land_parse_error')

    # rooms
    if item.get('rooms') is None:
        reasons.append('no_rooms')
    else:
        try:
            if item['rooms'] < MIN_ROOMS:
                reasons.append('rooms_too_few')
        except Exception:
            reasons.append('rooms_parse_error')

    # denkmalschutz
    txt = (item.get('raw_text') or '').lower()
    if 'denkmal' in txt or 'denkmalgeschützt' in txt or 'denkmalschutz' in txt:
        reasons.append('denkmal')

    # object type heuristics: require keywords indicating house + land
    must_keywords = ['haus', 'einfamilienhaus', 'freistehend', 'freistehendes', 'alleinsteh', 'bauernhaus', 'landhaus', 'bungalow', 'grundstueck', 'grundstück']
    if not any(k in txt for k in must_keywords):
        reasons.append('not_house_keyword')

    # distance / travel time check: prefer estimated travel time if available
    lat = item.get('lat'); lng = item.get('lng')
    if lat and lng:
        t_b = item.get('est_travel_time_h_berlin')
        t_h = item.get('est_travel_time_h_hamburg')
        d_b = item.get('distance_km_berlin')
        d_h = item.get('distance_km_hamburg')
        within = False
        # check travel time first (<= 2.0 hours)
        if t_b is not None and t_b <= 2.0:
            within = True
        if t_h is not None and t_h <= 2.0:
            within = True
        # fallback to distance if travel time not available
        if d_b is not None and d_b <= MAX_DISTANCE_KM:
            within = True
        if d_h is not None and d_h <= MAX_DISTANCE_KM:
            within = True
        if not within:
            reasons.append('too_far')
    else:
        reasons.append('no_geocode')

    passes = (len(reasons) == 0)
    return passes, reasons

def main():
    db = load_db()
    scraper = ImmofuxScraper()
    try:
        raw_list = scraper.fetch_listings(SEARCH_URL)
    except Exception as e:
        print('Search fetch failed:', e)
        raw_list = []

    new_items = []
    exported_items = []
    review_items = []
    for raw in raw_list:
        ident = raw.get('url') or raw.get('title')
        if not ident:
            continue
        if ident in db['seen']:
            continue
        norm = normalize_listing(raw)
        norm = geocode_item(norm)
        scored = score_listing(norm)
        scored['date_found'] = datetime.utcnow().isoformat() + 'Z'
        passes, reasons = matches_must_criteria(scored)
        scored['passes_filters'] = passes
        scored['filter_reasons'] = reasons
        new_items.append(scored)
        db['listings'].append(scored)
        db['seen'][ident] = True
        if scored['passes_filters']:
            exported_items.append(scored)
        else:
            # Review criteria (more permissive):
            reason_set = set(reasons)
            fatal_reasons = {'price>max','living_too_small','rooms_too_few','no_price','no_rooms','not_house_keyword','denkmal'}
            review_allowed = {'no_land_m2','no_geocode','land_too_small'}
            txt_lower = ((scored.get('raw_text') or '') + ' ' + (scored.get('title') or '')).lower()
            looks_like_house = any(k in txt_lower for k in ['haus','einfamilienhaus','freistehend','freisteh','bauernhaus','landhaus','bungalow','grundstueck','grundstück'])
            if reason_set and reason_set.isdisjoint(fatal_reasons) and reason_set.issubset(review_allowed):
                review_items.append(scored)
            elif looks_like_house and reason_set.isdisjoint(fatal_reasons):
                review_items.append(scored)

    save_db(db)

    try:
        export_to_sheet(new_items, exported_items, review_items if review_items else None)
        print(f"Exported parsed {len(new_items)} items; exported {len(exported_items)} matching items; {len(review_items)} review items to Google Sheet")
    except Exception as e:
        print('Export failed', e)

if __name__ == '__main__':
    main()
