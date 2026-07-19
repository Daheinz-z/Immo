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

# Average driving speed used to estimate travel time (km/h)
AVERAGE_SPEED_KMH = float(os.environ.get('TRAVEL_SPEED_KMH', '80'))

# Coordinates for Berlin and Hamburg (lat, lon)
BERLIN_COORD = (52.5200, 13.4050)
HAMBURG_COORD = (53.5511, 9.9937)

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
    params = {'q': query, 'format': 'json', 'limit': 1, 'addressdetails': 1, 'countrycodes': 'de'}
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
    """
    Try address -> postal_code+city -> city -> title+city -> raw_text
    If still no coords but city exists, geocode city explicitly (city centroid).
    Add fields: lat, lng, geocode_display_name, geocode_level ('address'|'city'|'fallback')
    Also compute distance_km_berlin/distance_km_hamburg and est_travel_time_h_berlin/est_travel_time_h_hamburg.
    """
    queries = []
    if item.get('addr_raw'):
        queries.append(item.get('addr_raw'))
    pc = item.get('postal_code')
    city = item.get('city')
    if pc and city:
        queries.append(f"{pc} {city}, Germany")
    if city:
        queries.append(f"{city}, Germany")
    if item.get('title') and city:
        queries.append(f"{item.get('title')}, {city}, Germany")
    rt = (item.get('raw_text') or '')[:200]
    if rt:
        queries.append(rt)

    geocoded = False
    for q in queries:
        if not q:
            continue
        res = geocode_query(q)
        if res:
            item['lat'] = res['lat']
            item['lng'] = res['lng']
            item['geocode_display_name'] = res.get('display_name')
            # guess geocode level
            if item.get('addr_raw') and q == item.get('addr_raw'):
                item['geocode_level'] = 'address'
            elif pc and q.startswith(pc):
                item['geocode_level'] = 'postalcode'
            else:
                item['geocode_level'] = 'city_or_fallback'
            geocoded = True
            break

    # Explicit city geocode fallback (if nothing matched earlier)
    if not geocoded and city:
        q_city = f"{city}, Germany"
        res_city = geocode_query(q_city)
        if res_city:
            item['lat'] = res_city['lat']
            item['lng'] = res_city['lng']
            item['geocode_display_name'] = res_city.get('display_name')
            item['geocode_level'] = 'city'
            geocoded = True

    # Compute distances & estimated travel times if we have coords
    if item.get('lat') is not None and item.get('lng') is not None:
        try:
            d_b = haversine_km(item['lat'], item['lng'], BERLIN_COORD[0], BERLIN_COORD[1])
            d_h = haversine_km(item['lat'], item['lng'], HAMBURG_COORD[0], HAMBURG_COORD[1])
            item['distance_km_berlin'] = round(d_b, 1)
            item['distance_km_hamburg'] = round(d_h, 1)
            # estimated driving time in hours (rough)
            if AVERAGE_SPEED_KMH > 0:
                item['est_travel_time_h_berlin'] = round(d_b / AVERAGE_SPEED_KMH, 2)
                item['est_travel_time_h_hamburg'] = round(d_h / AVERAGE_SPEED_KMH, 2)
        except Exception:
            pass

    return item

def haversine_km(lat1, lon1, lat2, lon2):
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km
