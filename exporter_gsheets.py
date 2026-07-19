# exporter_gsheets.py
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

def export_to_sheet(items):
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

    # Ensure worksheet exists and header is correct
    header = ['title','living_m2','land_m2','city','price_eur','rooms','condition','date_found','url','lat','lng','distance_km_berlin','distance_km_hamburg','passes_filters']
    try:
        worksheet = sh.worksheet('Listings')
        # verify header length; if different, don't overwrite but append rows using current columns
        existing = worksheet.row_values(1)
        if not existing or len(existing) < len(header):
            worksheet.delete_rows(1) if existing else None
            worksheet.insert_row(header, index=1)
    except Exception:
        worksheet = sh.add_worksheet('Listings', rows=2000, cols=len(header))
        worksheet.append_row(header)

    rows = []
    for it in items:
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
            it.get('passes_filters'),
        ])
    if rows:
        worksheet.append_rows(rows, value_input_option='RAW')
