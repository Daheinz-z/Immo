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
                                area = str(fs.get('value'))
                            elif isinstance(fs, (int, float, str)):
                                area = str(fs)
                        if 'numberOfRooms' in c:
                            rooms = str(c.get('numberOfRooms'))
                        out = {}
                        if title: out['title'] = title
                        if price: out['price_raw'] = str(price)
                        if area: out['area_raw'] = str(area)
                        if rooms: out['rooms_raw'] = str(rooms)
                        if address: out['addr_raw'] = address
                        if lat and lng:
                            out['lat'] = lat; out['lng'] = lng
                        if out:
                            return out
            except Exception:
                continue
        return {}

    def _extract_fallbacks(self, soup, text):
        out = {}
        # title
        title = None
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(strip=True)
        else:
            og = soup.find('meta', property='og:title')
            if og and og.get('content'):
                title = og.get('content')
        if title:
            out['title'] = title

        # price: try specific elements with class names first
        price_text = None
        possible_price = soup.select_one('[class*="price"], [id*="price"], [class*="preis"], [id*="preis"]')
        if possible_price:
            price_text = possible_price.get_text(separator=' ', strip=True)
        if not price_text:
            m = PRICE_RE.search(text[:6000])
            if m:
                price_text = m.group(0)
        if price_text:
            m2 = PRICE_RE.search(price_text)
            out['price_raw'] = m2.group(1) if m2 else price_text

        # living area
        m_area = AREA_RE.search(text)
        if m_area:
            out['area_raw'] = m_area.group(0)
        # land area
        m_land = LAND_RE.search(text)
        if m_land:
            out['land_raw'] = m_land.group(1)
        # rooms
        m_rooms = ROOMS_RE.search(text)
        if m_rooms:
            out['rooms_raw'] = m_rooms.group(1)
        # address heuristics: look for postal code + locality
        m_addr = re.search(r'\b(\d{5})\b\s*,?\s*([A-Za-zÄÖÜäöüß\-\s]{3,60})', text)
        if m_addr:
            out['addr_raw'] = f"{m_addr.group(1)} {m_addr.group(2).strip()}"
        return out

    def fetch_listings(self, start_url):
        print(f'Fetching search page: {start_url}')
        resp = self._get(start_url)
        if resp is None:
            print(f"[WARN] Could not fetch search page {start_url} (likely blocked). Returning empty list.")
            return []

        base_host = urlparse(start_url).netloc
        soup = BeautifulSoup(resp.text, 'html.parser')
        anchors = soup.find_all('a', href=True)

        # 1) Sammle Kategorieseiten unter /immobilienportal/
        category_pages = set()
        for a in anchors:
            href = a['href'].strip()
            full = urljoin(start_url, href)
            if not self._is_same_host(full, base_host):
                continue
            if '/immobilienportal/' in full.lower() and DETAIL_PATH_KEYWORD not in full.lower():
                category_pages.add(full)

        print(f"[DEBUG] Found {len(category_pages)} category pages on start page (limiting to first 10).")

        # limit how many category pages we follow to stay polite
        category_pages_list = list(category_pages)[:10]

        # 2) From each category page, collect detail links
        candidates = set()
        for cp in category_pages_list:
            print(f"[DEBUG] Fetching category page: {cp}")
            self._sleep()
            cr = self._get(cp, referer=start_url)
            if cr is None:
                print(f"[WARN] Could not fetch category page {cp}, skipping.")
                continue
            csoup = BeautifulSoup(cr.text, 'html.parser')
            cans = csoup.find_all('a', href=True)
            for a in cans:
                href = a['href'].strip()
                full = urljoin(cp, href)
                if not self._is_same_host(full, base_host):
                    continue
                if DETAIL_PATH_KEYWORD in full.lower():
                    candidates.add(full)

        # 3) Fallback: also check start page itself for detail links (in case)
        for a in anchors:
            href = a['href'].strip()
            full = urljoin(start_url, href)
            if not self._is_same_host(full, base_host):
                continue
            if DETAIL_PATH_KEYWORD in full.lower():
                candidates.add(full)

        print(f"[DEBUG] Total candidate detail URLs collected: {len(candidates)} (limiting to first 120).")

        # 4) Process candidates as before
        listings = []
        for url in list(candidates)[:120]:
            try:
                print('Fetching detail:', url)
                self._sleep()
                rr = self._get(url, referer=start_url)
                if rr is None:
                    print(f"[WARN] Skipping detail {url} because it could not be fetched.")
                    continue
                detail_soup = BeautifulSoup(rr.text, 'html.parser')
                text = detail_soup.get_text(separator=' ', strip=True)

                parsed = self._extract_from_jsonld(detail_soup) or {}
                fallback = self._extract_fallbacks(detail_soup, text)
                for k, v in fallback.items():
                    if k not in parsed or not parsed.get(k):
                        parsed[k] = v

                if not any(parsed.get(k) for k in ('price_raw', 'area_raw', 'rooms_raw', 'title')):
                    print(f"[INFO] Skipping {url} — not enough listing signals (no price/area/rooms/title).")
                    continue

                item = {
                    'source': 'immofux',
                    'url': url,
                    'title': parsed.get('title'),
                    'raw_text': text,
                    'price_raw': parsed.get('price_raw'),
                    'area_raw': parsed.get('area_raw'),
                    'rooms_raw': parsed.get('rooms_raw'),
                    'land_raw': parsed.get('land_raw') or None,
                    'addr_raw': parsed.get('addr_raw') or None,
                    'lat': parsed.get('lat') if parsed.get('lat') is not None else None,
                    'lng': parsed.get('lng') if parsed.get('lng') is not None else None,
                }
                listings.append(item)
            except Exception as e:
                print('Failed to fetch/parse', url, e)
        return listings
