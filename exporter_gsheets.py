import os
import json
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import SpreadsheetNotFound

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def _get_client_from_env():
    j = os.environ.get('GCP_SERVICE_ACCOUNT_JSON')
    if not j:
        raise RuntimeError('GCP_SERVICE_ACCOUNT_JSON not set in env (GitHub Secret)')
    try:
        info = json.loads(j)
    except Exception as e:
        raise RuntimeError('GCP_SERVICE_ACCOUNT_JSON does not contain valid JSON: ' + str(e))
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client

def _ensure_worksheet(sh, name, header):
    try:
        ws = sh.worksheet(name)
        existing = ws.row_values(1)
        if not existing or len(existing) < len(header):
            try:
                ws.delete_rows(1)
            except Exception:
                pass
            ws.insert_row(header, index=1)
    except Exception:
        ws = sh.add_worksheet(name, rows=2000, cols=len(header))
        ws.append_row(header)
    return ws

def export_to_sheet(parsed_items, matching_items, review_items=None):
    sheet_id = os.environ.get('GSHEET_ID')
    if not sheet_id:
        raise RuntimeError('GSHEET_ID not set in env (GitHub Secret)')
    client = _get_client_from_env()
    try:
        sh = client.open_by_key(sheet_id)
    except SpreadsheetNotFound:
        raise RuntimeError(f'Spreadsheet with ID \"{sheet_id}\" not found or not shared with the service account.')
    except Exception as e:
        raise RuntimeError('Failed to open spreadsheet: ' + str(e))

    # Listings worksheet (only matches)
    listings_header = ['title','living_m2','land_m2','city','price_eur','rooms','condition','date_found','url','lat','lng','distance_km_berlin','distance_km_hamburg']
    listings_ws = _ensure_worksheet(sh, 'Listings', listings_header)

    rows = []
    for it in matching_items:
        rows.append([
            it.get('title'),
            it.get('living_m2'),
            it.get('land_m2'),
            it.get('city'),
            it.get('price_eur'),
            it.get('rooms'),
            it.get('condition'),
            it.get('date_found'),
            it.get('url'),
            it.get('lat'),
            it.get('lng'),
            it.get('distance_km_berlin'),
            it.get('distance_km_hamburg'),
        ])
    if rows:
        listings_ws.append_rows(rows, value_input_option='RAW')

    # Parsed worksheet (all parsed items + reasons)
    parsed_header = [
        'title','living_m2','land_m2','city','price_eur','rooms','condition','date_found','url','lat','lng',
        'distance_km_berlin','distance_km_hamburg','passes_filters','filter_reasons','addr_raw','raw_text'
    ]
    parsed_ws = _ensure_worksheet(sh, 'Parsed', parsed_header)

    parsed_rows = []
    for it in parsed_items:
        parsed_rows.append([
            it.get('title'),
            it.get('living_m2'),
            it.get('land_m2'),
            it.get('city'),
            it.get('price_eur'),
            it.get('rooms'),
            it.get('condition'),
            it.get('date_found'),
            it.get('url'),
            it.get('lat'),
            it.get('lng'),
            it.get('distance_km_berlin'),
            it.get('distance_km_hamburg'),
            it.get('passes_filters'),
            ', '.join(it.get('filter_reasons') or []),
            it.get('addr_raw'),
            (it.get('raw_text') or '')[:1000],
        ])
    if parsed_rows:
        parsed_ws.append_rows(parsed_rows, value_input_option='RAW')

    # Review worksheet (near matches) - optional
    if review_items:
        review_header = [
            'title','living_m2','land_m2','city','price_eur','rooms','condition','date_found','url','lat','lng',
            'distance_km_berlin','distance_km_hamburg','passes_filters','filter_reasons','addr_raw','raw_text'
        ]
        review_ws = _ensure_worksheet(sh, 'Review', review_header)
        review_rows = []
        for it in review_items:
            review_rows.append([
                it.get('title'),
                it.get('living_m2'),
                it.get('land_m2'),
                it.get('city'),
                it.get('price_eur'),
                it.get('rooms'),
                it.get('condition'),
                it.get('date_found'),
                it.get('url'),
                it.get('lat'),
                it.get('lng'),
                it.get('distance_km_berlin'),
                it.get('distance_km_hamburg'),
                it.get('passes_filters'),
                ', '.join(it.get('filter_reasons') or []),
                it.get('addr_raw'),
                (it.get('raw_text') or '')[:1000],
            ])
        if review_rows:
            review_ws.append_rows(review_rows, value_input_option='RAW')
