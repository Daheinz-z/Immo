#!/usr/bin/env python3
import json
import os
from geocode import geocode_item

DB_PATH = 'storage/db.json'

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'seen': {}, 'listings': []}

def save_db(db):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def main():
    db = load_db()
    listings = db.get('listings', [])
    updated = 0
    total = 0
    for it in listings:
        total += 1
        if it.get('lat') is None or it.get('lng') is None:
            before = (it.get('lat'), it.get('lng'))
            new = geocode_item(it)
            after = (new.get('lat'), new.get('lng'))
            if after != before and after[0] is not None:
                updated += 1
    save_db(db)
    print(f"Backfill done. Updated {updated} of {total} listings.")

if __name__ == '__main__':
    main()
