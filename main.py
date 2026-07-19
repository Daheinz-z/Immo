#!/usr/bin/env python3
from scrapers.immofux import ImmofuxScraper
from scrapers.ebay_kleinanzeigen import EbayKAScraper
from normalizer import normalize_listing
from scoring import score_listing
from exporter_gsheets import export_to_sheet
from geocode import geocode_item, haversine_km
import json
import os
from datetime import datetime

STORAGE_PATH = 'storage/db.json'
# keep previous SEARCH_URL for immofux
IMMOFUX_SEARCH_URL = 'https://immofux.de/'
# seed URLs for eBay Kleinanzeigen (from user)
EBAY_SEEDS = [
    'https://www.kleinanzeigen.de/s-haus-kaufen/c208',
    'https://www.kleinanzeigen.de/s-ferienwohnung-ferienhaus/kaufen/c275+ferienwohnung_ferienhaus.art_s:kaufen',
    'https://www.kleinanzeigen.de/s-immobilien/sonstiges/c198'
]

# Thresholds (anpassbar)
MIN_LIVING_M2 = int(os.environ.get('MIN_LIVING_M2', '90'))
MIN_LAND_M2 = int(os.environ.get('MIN_LAND_M2', '1000'))
MIN_ROOMS = int(os.environ.get('MIN_ROOMS', '2'))
MAX_PRICE = int(os.environ.get('MAX_PRICE', '400000'))
# approximate distance threshold in km (2 hours ~ 180 km at avg 90 km/h)
MAX_DISTANCE_KM = int(os.environ.get('MAX_DISTANCE_KM', '180'))

# eBay run configuration via ENV
# Number of seeds to process starting at SEED_START (0-based). By default process all seeds.
EBAY_SEED_START = int(os.environ.get('EBAY_SEED_START', '0'))
EBAY_SEED_COUNT = int(os.environ.get('EBAY_SEED_COUNT', str(len(EBAY_SEEDS))))
# Max candidate detail URLs per seed (to limit work per run)
EBAY_MAX_CANDIDATES_PER_SEED = int(os.environ.get('EBAY_MAX_CANDIDATES_PER_SEED', '120'))

# keep previous defaults for scraper; ebay scraper will also read EBAY_MAX_PAGES, EBAY_DELAY_MIN/MAX

# Keep main functions load_db, save_db as before

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

    if item.get('offer_type') != 'sale':
        reasons.append('not_for_sale')

    if item.get('price_eur') is None:
        reasons.append('no_price')
    else:
        try:
            if item['price_eur'] > MAX_PRICE:
                reasons.append('price>max')
        except Exception:
            reasons.append('price_parse_error')

    if item.get('living_m2') is None:
        reasons.append('no_living_m2')
    else:
        try:
            if item['living_m2'] < MIN_LIVING_M2:
                reasons.append('living_too_small')
        except Exception:
            reasons.append('living_parse_error')

    if item.get('land_m2') is None:
        reasons.append('no_land_m2')
    else:
        try:
            if item['land_m2'] < MIN_LAND_M2:
                reasons.append('land_too_small')
        except Exception:
            reasons.append('land_parse_error')

    if item.get('rooms') is None:
        reasons.append('no_rooms')
    else:
        try:
            if item['rooms'] < MIN_ROOMS:
                reasons.append('rooms_too_few')
        except Exception:
            reasons.append('rooms_parse_error')

    txt = (item.get('raw_text') or '').lower()
    if 'denkmal' in txt or 'denkmalgeschützt' in txt or 'denkmalschutz' in txt:
        reasons.append('denkmal')

    must_keywords = ['haus', 'einfamilienhaus', 'freistehend', 'freistehendes', 'alleinsteh', 'bauernhaus', 'landhaus', 'bungalow', 'grundstueck', 'grundstück']
    if not any(k in txt for k in must_keywords):
        reasons.append('not_house_keyword')

    lat = item.get('lat'); lng = item.get('lng')
    if lat and lng:
        try:
            d_berlin = haversine_km(lat, lng, 52.5200, 13.4050)
            d_hamburg = haversine_km(lat, lng, 53.5511, 9.9937)
            item['distance_km_berlin'] = round(d_berlin, 1)
            item['distance_km_hamburg'] = round(d_hamburg, 1)
            t_b = item.get('est_travel_time_h_berlin')
            t_h = item.get('est_travel_time_h_hamburg')
            within = False
            if t_b is not None and t_b <= 2.0:
                within = True
            if t_h is not None and t_h <= 2.0:
                within = True
            if item.get('distance_km_berlin') is not None and item['distance_km_berlin'] <= MAX_DISTANCE_KM:
                within = True
            if item.get('distance_km_hamburg') is not None and item['distance_km_hamburg'] <= MAX_DISTANCE_KM:
                within = True
            if not within:
                reasons.append('too_far')
        except Exception:
            reasons.append('distance_calc_error')
    else:
        reasons.append('no_geocode')

    passes = (len(reasons) == 0)
    return passes, reasons


def main():
    db = load_db()

    # run immofux as before
    immofux = ImmofuxScraper()
    try:
        immofux_items = immofux.fetch_listings(IMMOFUX_SEARCH_URL)
    except Exception as e:
        print('Immofux fetch failed:', e)
        immofux_items = []

    # decide which ebay seeds to run this invocation (slice using EBAY_SEED_START/COUNT)
    seed_start = EBAY_SEED_START
    seed_count = max(0, EBAY_SEED_COUNT)
    selected_seeds = EBAY_SEEDS[seed_start:seed_start + seed_count]

    ebay_items = []
    if selected_seeds:
        ebay = EbayKAScraper()
        for seed in selected_seeds:
            try:
                # respect per-seed max candidates
                items = ebay.fetch_listings([seed], max_candidates=EBAY_MAX_CANDIDATES_PER_SEED)
                ebay_items.extend(items)
            except Exception as e:
                print(f'eBay KA fetch failed for seed {seed}:', e)

    combined = []
    for it in immofux_items + ebay_items:
        # simple dedupe by url
        if it.get('url') in db['seen']:
            continue
        combined.append(it)

    new_items = []
    exported_items = []
    review_items = []

    for raw in combined:
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
            # review permissive as before
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
