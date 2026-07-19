#!/usr/bin/env python3
from scrapers.immofux import ImmofuxScraper
from normalizer import normalize_listing
from scoring import score_listing
from exporter_gsheets import export_to_sheet
from geocode import geocode_item, haversine_km
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

# Coordinates for Berlin and Hamburg
BERLIN_COORD = (52.5200, 13.4050)
HAMBURG_COORD = (53.5511, 9.9937)

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
    # price
    if item.get('price_eur') is not None and item['price_eur'] > MAX_PRICE:
        return False
    # living area
    if item.get('living_m2') is not None and item['living_m2'] < MIN_LIVING_M2:
        return False
    # land area
    if item.get('land_m2') is not None and item['land_m2'] < MIN_LAND_M2:
        return False
    # rooms
    if item.get('rooms') is not None and item['rooms'] < MIN_ROOMS:
        return False
    # denkmalschutz
    txt = (item.get('raw_text') or '').lower()
    if 'denkmal' in txt or 'denkmalgeschützt' in txt:
        return False
    # object type heuristics: require keywords indicating house + land
    must_keywords = ['haus', 'einfamilienhaus', 'freistehend', 'freistehendes', 'alleinsteh', 'bauernhaus', 'landhaus', 'bungalow']
    if not any(k in txt for k in must_keywords):
        # If no strong hint of house, don't match
        return False
    # geo distance check (if available)
    if item.get('lat') and item.get('lng'):
        d_berlin = haversine_km(item['lat'], item['lng'], BERLIN_COORD[0], BERLIN_COORD[1])
        d_hamburg = haversine_km(item['lat'], item['lng'], HAMBURG_COORD[0], HAMBURG_COORD[1])
        item['distance_km_berlin'] = round(d_berlin, 1)
        item['distance_km_hamburg'] = round(d_hamburg, 1)
        if d_berlin > MAX_DISTANCE_KM and d_hamburg > MAX_DISTANCE_KM:
            return False
    else:
        # if no geodata, treat as unknown -> don't match automatically
        return False
    # If all checks passed:
    return True

def main():
    db = load_db()
    scraper = ImmofuxScraper()
    raw_list = []
    try:
        raw_list = scraper.fetch_listings(SEARCH_URL)
    except Exception as e:
        print('Search fetch failed:', e)

    new_items = []
    exported_items = []
    for raw in raw_list:
        ident = raw.get('url') or raw.get('title')
        if not ident:
            continue
        if ident in db['seen']:
            continue
        norm = normalize_listing(raw)
        # geocode (with cache)
        norm = geocode_item(norm)
        scored = score_listing(norm)
        scored['date_found'] = datetime.utcnow().isoformat() + 'Z'
        scored['passes_filters'] = matches_must_criteria(scored)
        new_items.append(scored)
        db['listings'].append(scored)
        db['seen'][ident] = True
        if scored['passes_filters']:
            exported_items.append(scored)

    save_db(db)

    if exported_items:
        try:
            export_to_sheet(exported_items)
            print(f"Exported {len(exported_items)} matching items to Google Sheet")
        except Exception as e:
            print('Export failed', e)
    else:
        print('No matching new items to export (found:', len(new_items), 'new items total )')

if __name__ == '__main__':
    main()
