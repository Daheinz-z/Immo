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

            if not any(parsed.get(k) for k in ('price_raw','area_raw','rooms_raw','title')):
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
