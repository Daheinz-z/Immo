import requests
import time
import json
import os
from math import radians, cos, sin, asin, sqrt

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
CACHE_PATH = 'storage/geocode_cache.json'
SLEEP_BETWEEN_LOOKUPS = float(os.environ.get('NOMINATIM_SLEEP', '1.1'))
# Read user agent from env (recommended to set as secret)
USER_AGENT = os.environ.get('NOMINATIM_USER_AGENT', 'immo-scraper/1.0 (david.heinz92@gmail.com)')

def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def geocode_query(query):
    cache = load_cache()
    if not query:
        return None
    key = query.strip().lower()
    if key in cache:
        return cache[key]
    params = {'q': query, 'format': 'json', 'limit': 1, 'addressdetails': 1}
    headers = {'User-Agent': USER_AGENT, 'Accept-Language': 'de'}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                item = data[0]
                out = {'lat': float(item['lat']), 'lng': float(item['lon']), 'display_name': item.get('display_name')}
                cache[key] = out
                save_cache(cache)
                time.sleep(SLEEP_BETWEEN_LOOKUPS)
                return out
    except Exception as e:
        print('[WARN] Geocode failed for:', query, e)
    cache[key] = None
    save_cache(cache)
    time.sleep(SLEEP_BETWEEN_LOOKUPS)
    return None

def geocode_item(item):
    # Prefer most precise fields: addr_raw (street + plz + city), then postal_code+city, then city, then short raw_text.
    cache = load_cache()
    # Build candidate queries in order
    queries = []
    if item.get('addr_raw'):
        queries.append(item.get('addr_raw'))
    # try postal_code + city
    pc = item.get('postal_code')
    city = item.get('city')
    if pc and city:
        queries.append(f"{pc} {city}, Germany")
    if city:
        queries.append(f"{city}, Germany")
    # short title + city
    if item.get('title') and city:
        queries.append(f"{item.get('title')}, {city}, Germany")
    # fallback: short raw_text prefix
    rt = (item.get('raw_text') or '')[:200]
    if rt:
        queries.append(rt)

    for q in queries:
        if not q:
            continue
        res = geocode_query(q)
        if res:
            item['lat'] = res['lat']
            item['lng'] = res['lng']
            item['geocode_display_name'] = res.get('display_name')
            return item
    # if none matched, leave lat/lng as None
    return item

def haversine_km(lat1, lon1, lat2, lon2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km
