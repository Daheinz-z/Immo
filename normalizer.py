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
    # Existing simpler extractor (kept for compatibility)
    m = re.search(r'\b(\d{5})\b\s*,?\s*([A-Za-zÄÖÜäöüß\-\s]+)', text)
    if m:
        postcode = m.group(1).strip()
        city = m.group(2).strip().split('\n')[0].split(',')[0].strip()
        return postcode, city
    m2 = re.search(r'in\s+([A-Za-zÄÖÜäöüß\-\s]{3,50})', text, re.IGNORECASE)
    if m2:
        city = m2.group(1).strip().split('\n')[0].split(',')[0].strip()
        return None, city
    return None, None

def extract_postcode_and_city_from_text(text):
    if not text:
        return None, None
    m = re.search(r'\b(\d{5})\b[\s\-_/,]*([A-Za-zÄÖÜäöüß\-\s]{2,60})', text)
    if m:
        postcode = m.group(1).strip()
        city = m.group(2).strip().split('/')[0].split('-')[-1].strip()
        return postcode, city
    m2 = re.search(r'(?:in|bei|,)\s+([A-Za-zÄÖÜäöüß\-\s]{3,60})', text, re.IGNORECASE)
    if m2:
        city = m2.group(1).strip().split(',')[0].strip()
        return None, city
    return None, None

def extract_land_from_text(text):
    if not text:
        return None
    s = text.replace('\xa0', ' ')
    # match patterns like "728 m²", "1155 qm", "1,1751 ha", "1155-qm", "1155 qm"
    m = re.search(r'(\d{1,3}(?:[.,]\d+)?(?:[.\s]\d{3})?)\s*(m²|m2|qm)\b', s, re.IGNORECASE)
    if m:
        val = m.group(1)
        val = val.replace('.', '').replace(' ', '').replace(',', '.')
        try:
            return float(val)
        except:
            pass
    # ha -> m2
    m2 = re.search(r'([\d\.,]+)\s*ha\b', s, re.IGNORECASE)
    if m2:
        v = m2.group(1).replace(',', '.')
        try:
            return float(v) * 10000.0
        except:
            pass
    # slug-like patterns: 1155-qm or 1155_qm
    m3 = re.search(r'(\d{3,6})(?:[^\w]|_|\-)?(?:qm|m2|m\u00B2)', s, re.IGNORECASE)
    if m3:
        v = m3.group(1).replace('.', '').replace(' ', '')
        try:
            return float(v)
        except:
            pass
    return None

def condition_from_text(text):
    t = (text or '').lower()
    if any(k in t for k in ['neuwertig', 'top', 'sehr gepflegt', 'bezugsfrei']):
        return 'Top'
    if any(k in t for k in ['renoviert', 'teilweise renoviert', 'modernisiert']):
        return 'Renoviert'
    if any(k in t for k in ['renovierungsbedürftig', 'renovierungsbeduerftig', 'sanierungsbedürftig', 'sanierungsbeduerftig', 'abbruchreif']):
        return 'Renovierungsbedürftig'
    return 'Unbekannt'

def _detect_offer_type(title, text):
    s = ((title or '') + ' ' + (text or '')).lower()
    # Keywords für Miete
    rent_kw = [
        'miete', 'mieten', 'vermiet', 'kaltmiete', 'warmmiete', 'monat', 'mietpreis',
        'zu vermieten', 'gesucht: mieter', 'pro monat', 'monatliche'
    ]
    # Keywords für Kauf
    sale_kw = [
        'kauf', 'kaufen', 'verkauf', 'verkaufen', 'kaufpreis', 'zum kauf', 'zu verkaufen',
        'kaufobjekt', 'verkaufsobjekt', 'provisionsfrei', 'verkauf wird'
    ]
    # Prefer explicit sale keywords
    if any(k in s for k in sale_kw):
        return 'sale'
    # If rental keywords present and no sale keyword, mark as rent
    if any(k in s for k in rent_kw) and not any(k in s for k in sale_kw):
        return 'rent'
    # If price mentions only rent units (€/Monat etc.), mark rent
    if '€/monat' in s or '€ pro monat' in s or 'monatl' in s:
        return 'rent'
    # fallback unknown
    return 'unknown'

def normalize_listing(raw):
    out = {}
    out['source'] = raw.get('source')
    out['url'] = raw.get('url')
    out['title'] = raw.get('title')
    out['price_eur'] = parse_euro(raw.get('price_raw'))
    out['living_m2'] = parse_area(raw.get('area_raw'))

    # land area: try raw land_raw first, then search in raw_text/title/url
    land_val = None
    if raw.get('land_raw'):
        land_val = raw.get('land_raw')
    rt = raw.get('raw_text') or ''
    if not land_val:
        land_val = extract_land_from_text(rt)
    if not land_val and raw.get('title'):
        land_val = extract_land_from_text(raw.get('title'))
    if not land_val and raw.get('url'):
        land_val = extract_land_from_text(raw.get('url'))
    out['land_m2'] = parse_area(str(land_val)) if land_val is not None else None

    # rooms
    try:
        out['rooms'] = float(raw.get('rooms_raw')) if raw.get('rooms_raw') else None
    except Exception:
        # fallback: try extract from title
        rooms_m = re.search(r'([0-9]+(?:[,\.]5)?)\s*(?:zimmer|zi\b|zimm|zkb)', (raw.get('title') or '').lower())
        if rooms_m:
            out['rooms'] = float(rooms_m.group(1).replace(',', '.'))
        else:
            out['rooms'] = None

    out['raw_text'] = rt
    out['condition'] = condition_from_text(rt)

    # Try to extract postcode and city from raw_text, then title, then url
    postcode, city = extract_postcode_and_city(rt or '')
    if (not postcode and not city) and raw.get('title'):
        p2, c2 = extract_postcode_and_city_from_text(raw.get('title'))
        postcode = postcode or p2
        city = city or c2
    if (not postcode and not city) and raw.get('url'):
        p3, c3 = extract_postcode_and_city_from_text(raw.get('url'))
        postcode = postcode or p3
        city = city or c3
    out['postal_code'] = postcode
    out['city'] = city

    # ensure lat/lng placeholders exist
    out['lat'] = raw.get('lat') if raw.get('lat') is not None else None
    out['lng'] = raw.get('lng') if raw.get('lng') is not None else None

    # detect offer type (sale/rent/unknown)
    out['offer_type'] = _detect_offer_type(out.get('title'), out.get('raw_text'))

    return out
