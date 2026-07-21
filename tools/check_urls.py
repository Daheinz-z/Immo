#!/usr/bin/env python3
"""
check_urls.py

Utility script to fetch a list of eBay Kleinanzeigen detail URLs and print parsed signals
using the same parsing helpers as the EbayKAScraper. Meant for quick debugging in Actions
or locally.

Usage: set environment variable URLS as comma-separated list OR edit the URLS list below.
Optional: set NOMINATIM_USER_AGENT if you want PLZ->state fallback lookups.
"""

import os
import json
from scrapers.ebay_kleinanzeigen import EbayKAScraper
import sys, os sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(file), '..')))
# Example: override via env var URLS="url1,url2"
URLS_ENV = os.environ.get('URLS')
if URLS_ENV:
    URLS = [u.strip() for u in URLS_ENV.split(',') if u.strip()]
else:
    # fill with a few example URLs; the user can edit or pass via env
    URLS = [
        'https://www.kleinanzeigen.de/s-anzeige/immoberlin-de-wunderbares-einfamilienhaus-mit-2-ferienwohnungen-nebengebaeude-ausbaupotenzial/3463774722-208-16638',
        'https://www.kleinanzeigen.de/s-anzeige/landhaus-mit-nebengebaeuden-auf-ueber-6-000-m-grundstueck-in-traumhafter-alleinlage-provisionsfrei/3463679739-208-17686',
        'https://www.kleinanzeigen.de/s-anzeige/zwischen-see-und-wald-wohnen-in-lindow/3458508737-208-7943',
        # add more as needed
    ]

scraper = EbayKAScraper()

out = []
for url in URLS:
    o = {'url': url}
    try:
        print('Fetching', url)
        resp = scraper._get(url)
        if resp is None:
            o['status'] = 'fetch_failed'
            out.append(o)
            print(json.dumps(o, ensure_ascii=False))
            continue
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        parsed = scraper._extract_from_jsonld(soup) or {}
        fallback = scraper._extract_fallbacks(soup, text)
        for k, v in fallback.items():
            if k not in parsed or not parsed.get(k):
                parsed[k] = v
        o['status'] = 'ok'
        o['price_raw'] = parsed.get('price_raw')
        o['area_raw'] = parsed.get('area_raw')
        o['rooms_raw'] = parsed.get('rooms_raw')
        o['addr_raw'] = parsed.get('addr_raw')
        # try plz from addr_raw or text
        plz_candidates = []
        if parsed.get('addr_raw'):
            p = scraper._extract_plz_from_text(parsed.get('addr_raw'))
            if p:
                plz_candidates.append(p)
        p2 = scraper._extract_plz_from_text(url)
        if p2:
            plz_candidates.append(p2)
        p3 = scraper._extract_plz_from_text(text[:500])
        if p3:
            plz_candidates.append(p3)
        o['plz_candidates'] = list(dict.fromkeys(plz_candidates))
        mapped = None
        if o['plz_candidates']:
            mapped = scraper._plz_to_state(o['plz_candidates'][0])
        o['mapped_state'] = mapped
        o['raw_text_snippet'] = text[:400]
        print(json.dumps(o, ensure_ascii=False, indent=2))
        out.append(o)
    except Exception as e:
        o['status'] = 'error'
        o['error'] = str(e)
        out.append(o)
        print(json.dumps(o, ensure_ascii=False))

# write a small summary file for Actions artifact if available
try:
    os.makedirs('storage', exist_ok=True)
    with open('storage/check_urls_result.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
except Exception:
    pass

print('Done')
