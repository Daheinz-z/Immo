# normalizer.py
import re

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

def extract_postcode_and_city(text):
    # Suche nach PLZ (deutsche 5-stellige) + Ort direkt danach
    m = re.search(r'\\b(\\d{5})\\b\\s*,?\\s*([A-Za-zÄÖÜäöüß\\-\\s]+)', text)
    if m:
        postcode = m.group(1).strip()
        city = m.group(2).strip()
        # clean city (take first token)
        city = city.split('\\n')[0].split(',')[0].strip()
        return postcode, city
    # fallback: nur Stadt (z. B. "in Musterstadt")
    m2 = re.search(r'in\\s+([A-Za-zÄÖÜäöüß\\-\\s]{3,50})', text, re.IGNORECASE)
    if m2:
        city = m2.group(1).strip().split('\\n')[0].split(',')[0].strip()
        return None, city
    return None, None

def condition_from_text(text):
    t = (text or '').lower()
    # heuristische Erkennung (einfach)
    if any(k in t for k in ['neuwertig', 'top', 'sehr gepflegt', 'bezugsfrei']):
        return 'Top'
    if any(k in t for k in ['renoviert', 'teilweise renoviert', 'modernisiert']):
        return 'Renoviert'
    if any(k in t for k in ['renovierungsbedürftig', 'renovierungsbeduerftig', 'sanierungsbedürftig', 'sanierungsbeduerftig', 'abbruchreif']):
        return 'Renovierungsbedürftig'
    return 'Unbekannt'

def normalize_listing(raw):
    out = {}
    out['source'] = raw.get('source')
    out['url'] = raw.get('url')
    out['title'] = raw.get('title')
    out['price_eur'] = parse_euro(raw.get('price_raw'))
    out['living_m2'] = parse_area(raw.get('area_raw'))
    # land area not always available; try to extract from raw_text via common patterns
    land_m2 = None
    rt = raw.get('raw_text') or ''
    m_land = re.search(r'Grundstück[:]?\\s*([0-9\\s\\.,]+)\\s*m', rt, re.IGNORECASE)
    if not m_land:
        m_land = re.search(r'(?:Grundstücksfläche|Grundstueck|Fläche)[:]?\\s*([0-9\\s\\.,]+)\\s*(m2|m²|m)', rt, re.IGNORECASE)
    if m_land:
        land_m2 = m_land.group(1)
    out['land_m2'] = parse_area(land_m2)
    try:
        out['rooms'] = float(raw.get('rooms_raw')) if raw.get('rooms_raw') else None
    except Exception:
        out['rooms'] = None
    out['raw_text'] = rt
    out['condition'] = condition_from_text(rt)
    # Try to extract postcode and city
    postcode, city = extract_postcode_and_city(rt)
    out['postal_code'] = postcode
    out['city'] = city
    # placeholders for geodata
    out['lat'] = None
    out['lng'] = None
    return out
