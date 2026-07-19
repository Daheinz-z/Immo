import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import time
import random
import os

# Kleinere UA‑Liste
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

# Pfade, die wir als Kategorie/Service-Seiten ausschließen wollen
EXCLUDE_PATH_PATTERNS = [
    '/immobilienportal/', '/leistungen/', '/kontakt', '/impressum', '/datenschutz',
    '/rss', '/suche', '/search', '/kategorie', '/category', '/tag/', '/page/'
]

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
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                print(f"[DEBUG] request exception for {url} (attempt {attempt}): {e}")
                last_exc = e
                self._sleep()
        print(f"[ERROR] Failed to fetch {url} after {self.max_retries} attempts: {last_exc}")
        return None

    def _looks_like_listing(self, text):
        # einfache Heuristiken: Preis, m², Zimmer oder 'Expose' vorkommen
        if not text:
            return False
        t = text.lower()
        if '€' in t or 'kaufpreis' in t or 'kaltmiete' in t or 'zimmer' in t or 'm²' in t or 'exposé' in t or 'expose' in t:
            return True
        return False

    def _is_excluded_path(self, href):
        low = href.lower()
        for p in EXCLUDE_PATH_PATTERNS:
            if p in low:
                return True
        return False

    def fetch_listings(self, start_url):
        print(f'Fetching search page: {start_url}')
        resp = self._get(start_url)
        if resp is None:
            print(f"[WARN] Could not fetch search page {start_url} (likely blocked). Returning empty list.")
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')
        anchors = soup.find_all('a', href=True)
        candidates = set()

        for a in anchors:
            href = a['href']
            full = urljoin(start_url, href)
            # ausschließen, wenn Pfad typische Kategorie/Service-Seite ist
            if self._is_excluded_path(full):
                continue
            # heuristische Auswahl: prefer links that contain 'objekt', 'angebot', 'immobilie', 'expose'
            if any(k in href.lower() for k in ['/objekt', '/angebot', '/immobilie', '/expose', '/inserat', '/angebot/']):
                candidates.add(full)
            # fallback: links that look like they have an id or slug (heuristisch)
            elif re.search(r'/[a-z0-9\\-]+(?:\\d{2,6})?/?$', href, re.IGNORECASE):
                candidates.add(full)

        listings = []
        for url in list(candidates)[:80]:  # etwas großzügiger limitieren, aber höflich bleiben
            try:
                print('Fetching detail:', url)
                self._sleep()
                rr = self._get(url, referer=start_url)
                if rr is None:
                    print(f"[WARN] Skipping detail {url} because it could not be fetched.")
                    continue
                detail_soup = BeautifulSoup(rr.text, 'html.parser')
                text = detail_soup.get_text(separator=' ', strip=True)
                # check if this page actually looks like a listing
                if not self._looks_like_listing(text):
                    print(f"[INFO] Skipping {url} — doesn't look like a listing (no price/area/rooms).")
                    continue
                title = detail_soup.title.string.strip() if detail_soup.title else None
                price = self._find_price(text)
                area = self._find_area(text)
                rooms = self._find_rooms(text)
                listings.append({
                    'source': 'immofux',
                    'url': url,
                    'title': title,
                    'raw_text': text,
                    'price_raw': price,
                    'area_raw': area,
                    'rooms_raw': rooms,
                })
            except Exception as e:
                print('Failed to fetch', url, e)
        return listings

    def _find_price(self, text):
        m = re.search(r'(?:Preis|Kaufpreis|€)\s*[:\-]??\s*([0-9\s\.\,]+)\s*€?', text)
        if m:
            return m.group(1)
        m2 = re.search(r'([0-9]{1,3}(?:[\.\s][0-9]{3})*)(?:\s*€)', text)
        if m2:
            return m2.group(1)
        return None

    def _find_area(self, text):
        m = re.search(r'([0-9]{2,4}[,\.]?[0-9]*)\s*m2|m²', text)
        if m:
            return m.group(1)
        return None

    def _find_rooms(self, text):
        m = re.search(r'([0-9]+(?:[,\.]5)?)\s*(?:Zimmer|rooms)', text)
        if m:
            return m.group(1)
        return None
