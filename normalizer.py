import re

# normalization helpers

def parse_euro(raw):
    if not raw:
        return None
    s = re.sub(r'[^0-9\,\.]','', raw)
    s = s.replace('.', '').replace(',', '.')
    try:
        return int(float(s))
    except Exception:
        return None


def parse_area(raw):
    if not raw:
        return None
    s = re.sub(r'[^0-9\,\.]','', raw)
    s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def normalize_listing(raw):
    out = {}
    out['source'] = raw.get('source')
    out['url'] = raw.get('url')
    out['title'] = raw.get('title')
    out['price_eur'] = parse_euro(raw.get('price_raw'))
    out['living_m2'] = parse_area(raw.get('area_raw'))
    try:
        out['rooms'] = float(raw.get('rooms_raw')) if raw.get('rooms_raw') else None
    except Exception:
        out['rooms'] = None
    out['raw_text'] = raw.get('raw_text')
    # placeholders for later enrichment
    out['address'] = None
    out['postal_code'] = None
    out['city'] = None
    out['lat'] = None
    out['lng'] = None
    return out
