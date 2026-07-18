import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import time
import random

class ImmofuxScraper:
    """Simple scraper for immofux.de

    This is a best-effort scraper using requests + BeautifulSoup. It looks for links
    that look like listing pages and tries to extract title / price / basics via regex.

    NOTE: This is a template. HTML structure may change; adapt selectors after inspecting
    the real pages.
    """

    HEADERS = {
        'User-Agent': 'immo-scraper-bot/1.0 (+https://github.com/Daheinz-z/Immo)'
    }

    def __init__(self, delay_min=1.0, delay_max=3.0):
        self.delay_min = delay_min
        self.delay_max = delay_max

    def _sleep(self):
        time.sleep(self.delay_min + random.random()*(self.delay_max-self.delay_min))

    def fetch_listings(self, start_url):
        print(f'Fetching search page: {start_url}')
        r = requests.get(start_url, headers=self.HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        anchors = soup.find_all('a', href=True)
        candidates = set()
        for a in anchors:
            href = a['href']
            # heuristic: listing links often contain keywords
            if any(k in href.lower() for k in ['/objekt', '/immobilie', '/angebot', '/expose', '/listings']):
                candidates.add(urljoin(start_url, href))
        # fallback: take links that contain 'immobil' or 'haus'
        if not candidates:
            for a in anchors:
                href = a['href']
                if any(k in href.lower() for k in ['immobil', 'haus', 'ferien']):
                    candidates.add(urljoin(start_url, href))

        listings = []
        for url in list(candidates)[:40]:  # limit to first 40 to be polite
            try:
                print('Fetching detail:', url)
                self._sleep()
                rr = requests.get(url, headers=self.HEADERS, timeout=20)
                rr.raise_for_status()
                detail_soup = BeautifulSoup(rr.text, 'html.parser')
                text = detail_soup.get_text(separator=' ', strip=True)
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
        # fallback generic euro amounts
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
