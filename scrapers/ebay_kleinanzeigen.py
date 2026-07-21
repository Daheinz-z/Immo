import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time
import random
import json
import os
import unicodedata

# Basic regexes similar to immofux
PRICE_RE = re.compile(r'(?:Preis|Kaufpreis|€)\s*[:\-]?\s*([0-9\s\.\,]+)\s*€?', re.IGNORECASE)
AREA_RE = re.compile(r'([0-9]{1,4}(?:[\.,][0-9]+)?)\s*(?:m²|m2|qm)', re.IGNORECASE)
ROOMS_RE = re.compile(r'([0-9]+(?:[.,]5)?)\s*(?:Zimmer|rooms|Zi)', re.IGNORECASE)
PLZ_RE = re.compile(r'\b(\d{5})\b')

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

# tokens that commonly appear in teaser location fields but are not real locations
NON_LOCATION_TOKENS = set(['video','top','neu','bild','bilder','image','images','mehr','anzeigen','vor 1 stunde','vor 2 stunden'])

# Default skip cache path
DEFAULT_SKIP_CACHE = 'storage/ebay_skip_cache.json'
DEFAULT_PLZ_CACHE = 'storage/plz_state_cache.json'

# how many parent levels to scan for teaser info
TEASER_SCAN_LEVELS = int(os.environ.get('EBAY_TEASER_SCAN_LEVELS', '5'))
# enable verbose debug logs from eBay scraper
EBAY_VERBOSE = os.environ.get('EBAY_VERBOSE', os.environ.get('EBAY_DEBUG', '0')) == '1'

class EbayKAScraper:
    def __init__(self, delay_min=2.0, delay_max=5.0, max_retries=3, max_pages=3):
        self.delay_min = float(os.environ.get('EBAY_DELAY_MIN', str(delay_min)))
        self.delay_max = float(os.environ.get('EBAY_DELAY_MAX', str(delay_max)))
        self.max_retries = max_retries
        self.max_pages = int(os.environ.get('EBAY_MAX_PAGES', str(max_pages)))
        self.session = requests.Session()
        self.skip_cache_path = os.environ.get('EBAY_SKIP_CACHE', DEFAULT_SKIP_CACHE)
        self.plz_cache_path = os.environ.get('EBAY_PLZ_CACHE', DEFAULT_PLZ_CACHE)
        self.skip_cache = set()
        self.plz_cache = {}
        self._load_skip_cache()
        self._load_plz_cache()

    def _debug(self, *args, **kwargs):
        if EBAY_VERBOSE:
            print('[ebay-ka][DEBUG]', *args, **kwargs)

    def _load_skip_cache(self):
        try:
            if os.path.exists(self.skip_cache_path):
                with open(self.skip_cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.skip_cache = set(data)
        except Exception:
            self.skip_cache = set()

    def _save_skip_cache(self):
        try:
            os.makedirs(os.path.dirname(self.skip_cache_path), exist_ok=True)
            with open(self.skip_cache_path, 'w', encoding='utf-8') as f:
                json.dump(list(self.skip_cache), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_plz_cache(self):
        try:
            if os.path.exists(self.plz_cache_path):
                with open(self.plz_cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.plz_cache = data
        except Exception:
            self.plz_cache = {}

    def _save_plz_cache(self):
        try:
            os.makedirs(os.path.dirname(self.plz_cache_path), exist_ok=True)
            with open(self.plz_cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.plz_cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

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

    def _extract_plz_from_text(self, text):
        if not text:
            return None
        m = PLZ_RE.search(text)
        if m:
            return m.group(1)
        return None

    def _normalize_state(self, s):
        if not s:
            return None
        s = s.strip().lower()
        # remove diacritics
        s = unicodedata.normalize('NFKD', s)
        s = ''.join(c for c in s if not unicodedata.combining(c))
        s = s.replace(' ', '-').replace('\u00df', 'ss')
        s = s.replace('ü', 'ue').replace('ö', 'oe').replace('ä', 'ae')
        return s

    def _plz_to_state_local(self, plz):
        """Quick prefix-based mapping for common ranges (covers all Bundesländer roughly).
        This is conservative and used as first-pass. Returns normalized state string or None.
        """
        try:
            prefix = int(plz[:2])
        except Exception:
            return None
        # approximate ranges (by first two digits)
        # Source: heuristic grouping of German PLZ ranges
        if 10 <= prefix <= 13:
            return 'berlin'
        if 14 <= prefix <= 16:
            return 'brandenburg'
        if 17 <= prefix <= 19:
            return 'mecklenburg-vorpommern'
        if 20 <= prefix <= 22:
            return 'hamburg'
        if 23 <= prefix <= 25:
            return 'schleswig-holstein'
        if 26 <= prefix <= 31:
            return 'niedersachsen'
        if 32 <= prefix <= 39:
            return 'nrw'
        if 40 <= prefix <= 49:
            return 'nrw'
        if 50 <= prefix <= 59:
            return 'nrw'
        if 60 <= prefix <= 65:
            return 'hessen'
        if 66 <= prefix <= 69:
            return 'rheinland-pfalz'
        if 70 <= prefix <= 79:
            return 'baden-wuerttemberg'
        if 80 <= prefix <= 97:
            return 'bayern'
        if 98 <= prefix <= 99:
            return 'thuringen'
        return None

    def _plz_to_state(self, plz):
        # check cache first
        if not plz:
            return None
        if plz in self.plz_cache:
            return self.plz_cache[plz]

        # try local heuristic
        mapped = self._plz_to_state_local(plz)
        if mapped:
            self.plz_cache[plz] = mapped
            self._save_plz_cache()
            return mapped

        # fallback: use Nominatim if available (and NOMINATIM_USER_AGENT set)
        ua = os.environ.get('NOMINATIM_USER_AGENT') or os.environ.get('NOMINATIM_USER_AGENT', None)
        if not ua:
            # no user agent for Nominatim, cannot perform lookup
            self.plz_cache[plz] = None
            self._save_plz_cache()
            return None

        try:
            params = {'postalcode': plz, 'country': 'Germany', 'format': 'jsonv2', 'limit': 1}
            headers = {'User-Agent': ua}
            resp = requests.get('https://nominatim.openstreetmap.org/search', params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                j = resp.json()
                if isinstance(j, list) and len(j) > 0:
                    addr = j[0].get('address', {})
                    state = addr.get('state') or addr.get('region') or addr.get('county')
                    ns = self._normalize_state(state)
                    self.plz_cache[plz] = ns
                    self._save_plz_cache()
                    return ns
        except Exception:
            pass
        self.plz_cache[plz] = None
        self._save_plz_cache()
        return None

    def _listing_location_text(self, a_tag):
        # Try to find a nearby location text in the search result teaser
        # Scan up to TEASER_SCAN_LEVELS parent levels and a few sibling nodes and attributes
        parent = a_tag
        for level in range(TEASER_SCAN_LEVELS):
            if not parent:
                break
            # check common selectors
            try:
                loc = parent.select_one('[class*="location"], [class*="region"], [class*="ort"], .aditem-location, .simple-ad-location, .aditem-main--location')
            except Exception:
                loc = None
            if loc and loc.get_text(strip=True):
                txt = loc.get_text(' ', strip=True)
                low = txt.lower().strip()
                if low in NON_LOCATION_TOKENS:
                    return None
                return txt
            # check attributes that sometimes contain location info
            for attr in ('data-location','data-city','title','aria-label'):
                val = parent.get(attr) if parent and hasattr(parent, 'get') else None
                if val and isinstance(val, str) and val.strip():
                    low = val.lower().strip()
                    if low in NON_LOCATION_TOKENS:
                        return None
                    return val.strip()
            # check images inside parent for alt/title
            img = parent.find('img') if parent else None
            if img:
                for a in ('alt','title'):
                    v = img.get(a)
                    if v and v.strip():
                        low = v.lower().strip()
                        if low in NON_LOCATION_TOKENS:
                            return None
                        return v.strip()
            # move up
            parent = parent.parent
        # fallback: check immediate siblings around anchor
        sib = a_tag.find_next_sibling()
        if sib:
            s = sib.get_text(' ', strip=True)
            if s:
                low = s.lower().strip()
                if low in NON_LOCATION_TOKENS:
                    return None
                return s
        # very last resort: anchor text itself
        txt = a_tag.get_text(' ', strip=True)
        if txt:
            low = txt.lower().strip()
            if low in NON_LOCATION_TOKENS:
                return None
            return txt
        return None

    def _extract_plz_near_anchor(self, a_tag, href):
        # search for PLZ in several nearby text blobs to improve recall
        # 1) href
        plz = self._extract_plz_from_text(href)
        if plz:
            return plz
        # 2) anchor text
        txt = a_tag.get_text(' ', strip=True)
        plz = self._extract_plz_from_text(txt)
        if plz:
            return plz
        # 3) parent and grandparents text (short window)
        parent = a_tag.parent
        for _ in range(4):
            if not parent:
                break
            ptxt = parent.get_text(' ', strip=True)
            # limit length to avoid huge blobs
            ptxt_short = ptxt[:300]
            plz = self._extract_plz_from_text(ptxt_short)
            if plz:
                return plz
            parent = parent.parent
        # 4) previous sibling and next sibling
        prev = a_tag.find_previous_sibling()
        if prev:
            plz = self._extract_plz_from_text(prev.get_text(' ', strip=True)[:200])
            if plz:
                return plz
        nexts = a_tag.find_next_siblings()
        for n in nexts[:3]:
            plz = self._extract_plz_from_text(n.get_text(' ', strip=True)[:200])
            if plz:
                return plz
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
                        # quick skip if we've previously marked this URL as outside allowed area
                        if full in self.skip_cache:
                            print(f"[ebay-ka] Skipping {full} (cached as outside allowed states)")
                            continue

                        # try to infer location from teaser and skip if outside allowed states
                        loc_text = self._listing_location_text(a)

                        # try to extract PLZ from href or anchor text if no loc_text
                        plz = None
                        if not loc_text:
                            plz = self._extract_plz_near_anchor(a, href)

                        mapped = None
                        if plz:
                            mapped = self._plz_to_state(plz)

                        # debug info
                        self._debug('candidate', full, 'loc_text=', loc_text, 'plz=', plz, 'mapped=', mapped)

                        # if we have a plz and mapped state, decide
                        if mapped and allowed_states_list:
                            if mapped not in allowed_states_list:
                                print(f"[ebay-ka] Skipping {full} due to PLZ {plz} -> state '{mapped}' not in allowed states")
                                self.skip_cache.add(full)
                                continue

                        if loc_text and allowed_states_list:
                            lt = loc_text.lower()
                            if not any(state in lt for state in allowed_states_list):
                                # conservative default: if loc_text exists and doesn't match, skip and cache
                                print(f"[ebay-ka] Skipping {full} due to location '{loc_text}' not in allowed states")
                                self.skip_cache.add(full)
                                continue

                        # if no loc_text and no PLZ mapping, conservative behavior = include
                        if not loc_text and not plz:
                            self._debug('Including candidate without loc/plz:', full)

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

        # persist skip cache and plz cache
        self._save_skip_cache()
        self._save_plz_cache()

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

                # debug print of parsed key signals for easier tuning
                self._debug('parsed', url, 'price=', parsed.get('price_raw'), 'area=', parsed.get('area_raw'), 'rooms=', parsed.get('rooms_raw'), 'addr=', parsed.get('addr_raw'))

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
