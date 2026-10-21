# Solar lead finder v2 (free)

Full guide: see "Solar Lead Finder: System Guide" (the document that came with this zip).
This file is the 10-line version.

1. Google Sheet > Extensions > Apps Script > paste `Code.gs`. Add Script property `SECRET_TOKEN`. Deploy as web app (Execute as Me, access Anyone). Copy the URL.
2. Private GitHub repo. Upload everything in this folder. If `.github` did not upload, create the 4 workflow files by hand (Add file > Create new file).
3. Repo Settings > Secrets and variables > Actions. Secrets: GAS_WEBHOOK_URL, SECRET_TOKEN, SERPER_API_KEY, TAVILY_API_KEY, EXA_API_KEY. Variables: STATES (CA,FL,TX,AZ).
4. Put the license downloads in `data/raw/` named by state: CA.xlsx, FL.csv, TX.csv, AZ.csv.
5. Edit `data/areas.csv` (your sample areas) and `data/big_names.txt`.
6. Actions > "Build master company list" > Run.
7. Actions > "Preflight check" > Run, then read the PASS/FAIL list in the log.
8. Actions > "Daily lead finder" > Run with limit 100 (test), read the Summary tab.
9. After that it runs by itself at 5:00 AM UTC.
10. Paste bounced emails into the Bounces tab, and outcomes into Outcomes; run `report.py` for checkpoint numbers.

Tests: `python -m unittest tests.test_pipeline` (12 tests, offline).
