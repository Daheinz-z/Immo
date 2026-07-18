import os
import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def _get_client_from_env():
    j = os.environ.get('GCP_SERVICE_ACCOUNT_JSON')
    if not j:
        raise RuntimeError('GCP_SERVICE_ACCOUNT_JSON not set in env (GitHub Secret)')
    info = json.loads(j)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def export_to_sheet(items):
    sheet_id = os.environ.get('GSHEET_ID')
    if not sheet_id:
        raise RuntimeError('GSHEET_ID not set in env (GitHub Secret)')
    client = _get_client_from_env()
    sh = client.open_by_key(sheet_id)
    try:
        worksheet = sh.worksheet('Listings')
    except Exception:
        worksheet = sh.add_worksheet('Listings', rows=1000, cols=20)
        # header
        worksheet.append_row(['id','source','title','url','price_eur','living_m2','rooms','score','date_found'])

    rows = []
    for it in items:
        rid = it.get('url')
        rows.append([rid, it.get('source'), it.get('title'), it.get('url'), it.get('price_eur'), it.get('living_m2'), it.get('rooms'), it.get('score'), it.get('date_found')])
    # append rows in batch
    worksheet.append_rows(rows, value_input_option='RAW')
