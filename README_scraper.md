# Immo - Scraper & exporter scaffold

Dieses Repo enthält ein kleines Python‑Scaffold, das regelmäßig Immobilien‑Listings sammelt, normalisiert, bewertet und nach Google Sheets exportiert.

Zweck:
- Modularer Scraper pro Portal (scrapers/)
- Normalisierung (normalizer.py)
- Scoring (scoring.py)
- Export zu Google Sheets (exporter_gsheets.py)
- Scheduler via GitHub Actions (cron)

Wichtig: Bitte trage die benötigten GitHub‑Secrets ein (siehe README). Außerdem: prüfen wir vor dem Scraping die Nutzungsbedingungen der Portale.
