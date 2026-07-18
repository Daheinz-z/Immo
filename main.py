
from scrapers.immofux import ImmofuxScraper
from normalizer import normalize_listing
from scoring import score_listing
from exporter_gsheets import export_to_sheet
import json
import os
from datetime import datetime

STORAGE_PATH = 'storage/db.json'
SEARCH_URL = 'https://immofux.de/'


def load_db():
    if os.path.exists(STORAGE_PATH):
        with open(STORAGE_PATH,'r',encoding='utf-8') as f:
            return json.load(f)
    return {'seen':{}, 'listings':[]}


def save_db(db):
    os.makedirs(os.path.dirname(STORAGE_PATH), exist_ok=True)
    with open(STORAGE_PATH,'w',encoding='utf-8') as f:
        json.dump(db,f,ensure_ascii=False,indent=2)


def main():
    db = load_db()
    scraper = ImmofuxScraper()
    raw_list = scraper.fetch_listings(SEARCH_URL)
    new_items = []
    for raw in raw_list:
        ident = raw.get('url') or raw.get('title')
        if not ident:
            continue
        if ident in db['seen']:
            continue
        norm = normalize_listing(raw)
        scored = score_listing(norm)
        scored['date_found'] = datetime.utcnow().isoformat() + 'Z'
        new_items.append(scored)
        db['listings'].append(scored)
        db['seen'][ident] = True
    save_db(db)

    if new_items:
        try:
            export_to_sheet(new_items)
            print(f"Exported {len(new_items)} new items to Google Sheet")
        except Exception as e:
            print('Export failed', e)
    else:
        print('No new items found')


if __name__ == '__main__':
    main()
