import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time
import random
import json
import os

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    " Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
              "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

DETAIL_PATH_KEYWORD = '/immobilienportal/detail/'

PRICE_RE = re.compile(r'(?:Preis|Kaufpreis|€)\s*[:\-]?\s*([0-9\s\.\,]+)\s*€?', re.IGNORECASE)
AREA_RE = re.compile(r'([0-9]{1,4}(?:[.,][0-9]+)?)\s*(?:m²|m2|qm)', re.IGNORECASE)
LAND_RE = re.compile(r'(?:Grundstück|Grundst(ü|ue)ck|Grundstueck(?:sfläche)?)[:]?[\s]*([0-9\.\s,]+)\s*(?:m²|m2|qm|m)?', re.IGNORECASE)
ROOMS_RE = re.compile(r'([0-9]+(?:[.,]5)?)\s*(?:Zimmer|rooms)', re.IGNORECASE)


class ImmofuxScraper:
    def __init__(self, delay_min=1.0, delay_max=3.0, max_retries=3):
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_retries = max_retries
        self.session = requests.Session()

    def _sleep(self):
        time.sleep(self.delay_min + random.random() * (self.delay_max - self.delay_min))

    def _build_headers(self, referer=None):
        h = COMMON_HEADERS.copy()
        h["User-Agent"] = random.choice(USER_AGENTS)
        if referer:
            h["Referer"] = referer
        return h

    def _get(self, url, referer=None):
        last_exc = None
        timeout = float(os.environ.get('SCRAPER_TIMEOUT', '20'))
        for attempt in range(1, self.max_retries + 1):
            try:
                headers = self._build_headers(referer=referer or url)
                resp = self.session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 403:
                    print(f"[WARN] 403 for {url} (attempt {attempt})")
                    last_exc = requests.exceptions.HTTPError("403")
                    self._sleep()
                    continue
                if resp.status_code >= 400:
                    # allow caller to handle 404 for single pages gracefully
                    raise requests.exceptions.HTTPError(f"{resp.status_code} Client Error: {resp.reason} for url: {url}")
                return resp
            except requests.exceptions.RequestException as e:
                print(f"[DEBUG] request exception for {url} (attempt {attempt}): {e}")
                last_exc = e
                self._sleep()
        print(f"[ERROR] Failed to fetch {url} after {self.max_retries} attempts: {last_exc}")
        return None

    def _is_same_host(self, url, base_host):
        try:
            return urlparse(url).netloc == base_host
        except Exception:
            return False

    def _extract_from_jsonld(self, soup):
        # return dict with possible keys: title, price_raw, area_raw, land_raw, rooms_raw, address_raw, lat, lng
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                txt = script.string
                if not txt:
                    continue
                data = json.loads(txt)
                docs = data if isinstance(data, list) else [data]
                for doc in docs:
                    if not isinstance(doc, dict):
                        continue
                    candidates = [doc]
                    if 'mainEntity' in doc and isinstance(doc['mainEntity'], dict):
                        candidates.append(doc['mainEntity'])
                    for c in candidates:
                        if not isinstance(c, dict):
                            continue
                        title = c.get('name') or c.get('headline') or None
                        price = None
                        if 'offers' in c:
                            offers = c['offers']
                            if isinstance(offers, dict):
                                price = offers.get('price') or (offers.get('priceSpecification') or {}).get('price')
                        if not price and 'price' in c:
                            price = c.get('price')
                        address = None
                        if 'address' in c and isinstance(c['address'], dict):
                            a = c['address']
                            addr_parts = []
                            for k in ('streetAddress', 'postalCode', 'addressLocality', 'addressRegion', 'addressCountry'):
                                if a.get(k):
                                    addr_parts.append(str(a.get(k)))
                            address = ', '.join(addr_parts) if addr_parts else None
                        lat = None; lng = None
                        if 'geo' in c and isinstance(c['geo'], dict):
                            try:
                                lat = float(c['geo'].get('latitude') or c['geo'].get('lat'))
                                lng = float(c['geo'].get('longitude') or c['geo'].get('lon') or c['geo'].get('lng'))
                            except Exception:
                                lat = None; lng = None
                        area = None
                        rooms = None
                        if 'floorSize' in c:
                            fs = c['floorSize']
                            if isinstance(fs, dict) and 'value' in fs:
                                area = str*

