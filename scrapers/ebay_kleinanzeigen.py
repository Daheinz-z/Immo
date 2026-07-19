import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time
import random
import json
import os

# Basic regexes similar to immofux
PRICE_RE = re.compile(r'(?:Preis|Kaufpreis|€)\s*[:\-]?\s*([0-9\s\.\,]+)\s*€?', re.IGNORECASE)
AREA_RE = re.compile(r'([0-9]{1,4}(?:[\.,][0-9]+)?)\s*(?:m²|m2|qm)', re.IGNORECASE)
ROOMS_RE = re.compile(r'([0-9]+(?:[.,]5)?)\s*(?:Zimmer|rooms|Zi)', re.IGNORECASE)

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

DETAIL_PATH_KEY = '/s-anzeige/'

class EbayKAScraper:
    def __init__(self, delay_min=2.0, delay_max=5.0, max_retries=3, max_pages=3):
        self.delay_min = float(os.environ.get('EBAY_DELAY_MIN', str(delay_min)))
        self.delay_max = float(os.environ.get('EBAY_DELAY_MAX', str(delay_max)))
        self.max_retries = max_retries
        self.max_pages = int(os.environ.get('EBAY_MAX_PAGES', str(max_pages)))
        self.session = requests.Session()

    def _sleep(self):
        time.sleep(self.delay_min + random.random() * (self.delay_max - self.delay_min))

    def _build_headers(self, referer=None):
        h = COMMON_HEADERS.copy()
        h['User-Agent'] = random.choice(USER_AGENTS)
        if referer:
            h['Referer'] = referer
        return h

    def _get(self, url, referer=None):
        timeout = float(os.environ.get('SCRAPER_TIMEOUT', '20'))
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                headers = self._build_headers(referer=referer or url)
                resp = self.session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 403:
                    print(f"[WARN] 403 for {url} (attempt {attempt})")
                    last_exc = Exception('403')
                    self._sleep()
                    continue
                if resp.status_code >= 400:
                    raise Exception(f"{resp.status_code} Client Error")
                return resp
            except Exception as e:
                print(f"[DEBUG] request exception for {url} (attempt {attempt}): {e}")
                last_exc = e
                self._sleep()
        print(f"[ERROR] Failed to fetch {url} after {self.max_retries} attempts: {last_exc}")
        return None

    def _extract_from_jsonld(self, soup):
        # try to extract common fields from ld+json
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                txt = script.string
                if not txt:
                    continue
                data = json.loads(txt)
                if isinstance(data, dict):
                    title = data.get('name') or data.get('headline')
                    price = None
                    if 'offers' in data:
                        of = data['offers']
                        if isinstance(of, dict):
                            price = of.get('price')
                    area = None
                    if 'floorSize' in data:
                        fs = data['floorSize']
                        if isinstance(fs, dict):
                            area = fs.get('value')
                        else:
                            area = fs
                    out = {}
                    if title: out['title'] = title
                    if price: out['price_raw'] = str(price)
                    if area: out['area_raw'] = str(area)
                    # address
                    if 'address' in data and isinstance(data['address'], dict):
                        a = data['address']
                        parts = []
                        for k in ('streetAddress','postalCode','addressLocality'):
                            if a.get(k): parts.append(str(a.get(k)))
                        out['addr_raw'] = ', '.join(parts)
                    if out:
                        return out
            except Exception:
                continue
        return {}

    def _extract_fallbacks(self, soup, text):
        out = {}
        # title
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True):
            out['title'] = h1.get_text(strip=True)
        # price
        possible = soup.select_one('[class*="price"], [id*="price"], .price')
        if possible:
            out['price_raw'] = possible.get_text(separator=' ', strip=True)
        else:
            m = PRICE_RE.search(text[:4000])
            if m:
                out['price_raw'] = m.group(1)
        # area
        m = AREA_RE.search(text)
        if m:
            out['area_raw'] = m.group(0)
        # rooms
        mr = ROOMS_RE.search(text)
        if mr:
            out['rooms_raw'] = mr.group(1)
        # address / city
        # eBay KA often shows location in a tag with class 'location' or similar
        loc = None
        loc_sel = soup.select_one('[class*="location"], [class*="region"], .adview-location')
        if loc_sel:
            loc = loc_sel.get_text(separator=' ', strip=True)
            out['addr_raw'] = loc
        # fallback: try to find meta property 'og:locality' etc.
        og = soup.find('meta', property='og:locality')
        if og and og.get('content'):
            out['addr_raw'] = og.get('content')
        return out

    def _listing_location_text(self, a_tag):
        # Try to find a nearby location text in the search result teaser
        parent = a_tag.parent
        for _ in range(4):
            if not parent:
                break
            loc = parent.select_one('[class*="location"], [class*="region"], [class*="ort"], .aditem-location, .simple-ad-location, .aditem-main--location')
            if loc and loc.get_text(strip=True):
                return loc.get_text(' ', strip=True)
            parent = parent.parent
        # fallback: next sibling text
        sib = a_tag.find_next_sibling()
        if sib:
            s = sib.get_text(' ', strip=True)
            if s:
                return s
        return None

    def fetch_listings(self, seed_urls, max_candidates=200, allowed_states=None):
        """
        seed_urls: list of search result URLs
        allowed_states: CSV string of allowed state names (e.g. 'Berlin,Brandenburg')
        returns list of raw listing dicts similar to ImmofuxScraper
        """
        if isinstance(seed_urls, str):
            seed_urls = [seed_urls]
        candidates = []
        seen = set()

        # prepare allowed states
        allowed_states_list = []
        if allowed_states:
            allowed_states_list = [s.strip().lower() for s in allowed_states.split(',') if s.strip()]

        for seed in seed_urls:
            print(f"[ebay-ka] Fetching search page: {seed}")
            url = seed
            pages = 0
            while url and pages < self.max_pages and len(candidates) < max_candidates:
                resp = self._get(url)
                if resp is None:
                    break
                soup = BeautifulSoup(resp.text, 'html.parser')
                anchors = soup.find_all('a', href=True)
                for a in anchors:
                    href = a['href'].strip()
                    full = urljoin(seed, href)
                    if DETAIL_PATH_KEY in full and full not in seen:
                        # try to infer location from teaser and skip if outside allowed states
                        loc_text = self._listing_location_text(a)
                        if loc_text and allowed_states_list:
                            # if none of the allowed states appear in the location text, skip
                            if not any(state in loc_text.lower() for state in allowed_states_list):
                                # conservative default: if loc_text exists and doesn't match, skip
                                print(f"[ebay-ka] Skipping {full} due to location '{loc_text}' not in allowed states")
                                continue
                        # if no loc_text, conservative behavior = include
                        seen.add(full)
                        candidates.append(full)
                        if len(candidates) >= max_candidates:
                            break
                # try to find next page link (common pattern: rel="next" or link with 'page')
                next_link = None
                nl = soup.find('a', attrs={'rel':'next'})
                if nl and nl.get('href'):
                    next_link = urljoin(seed, nl.get('href'))
                else:
                    # heuristic: find links with 'page=' in href
                    for a in anchors:
                        h = a['href']
                        if 'page=' in h or 'seite' in h.lower():
                            next_link = urljoin(seed, h)
                            break
                pages += 1
                if next_link and pages < self.max_pages:
                    url = next_link
                    self._sleep()
                else:
                    break

        print(f"[ebay-ka] Total candidate detail URLs collected: {len(candidates)} (limiting to {max_candidates})")

        listings = []
        for url in candidates[:max_candidates]:
            try:
                print('[ebay-ka] Fetching detail:', url)
                self._sleep()
                rr = self._get(url, referer=seed_urls[0])
                if rr is None:
                    print(f"[ebay-ka] Skipping detail {url} because it could not be fetched.")
                    continue
                detail_soup = BeautifulSoup(rr.text, 'html.parser')
                text = detail_soup.get_text(separator=' ', strip=True)

                parsed = self._extract_from_jsonld(detail_soup) or {}
                fallback = self._extract_fallbacks(detail_soup, text)
                for k,v in fallback.items():
                    if k not in parsed or not parsed.get(k):
                        parsed[k] = v

                # minimal signals
                if not any(parsed.get(k) for k in ('price_raw','area_raw','rooms_raw','title')):
                    print(f"[ebay-ka] Skipping {url} — not enough listing signals")
                    continue

                item = {
                    'source': 'ebay_kleinanzeigen',
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
                print('[ebay-ka] Failed to fetch/parse', url, e)
        return listings
