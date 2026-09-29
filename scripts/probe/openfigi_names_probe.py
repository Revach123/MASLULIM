"""One-off probe: fetch OpenFIGI's full (untruncated) name for each of the
34 ISINs still unclassified after the current pipeline, so we can inspect
the real fund name (not the truncated report name) and add any further
safe, low-ambiguity keywords to foreign_etf_reference.py.
"""
import json
import time

import requests

ISINS = [
    "LI1165463954", "IE00BKWQOJ47", "IE00BKSBD728", "LU0769026740",
    "LU2618836352", "IE00B804LV55", "LU0906530919", "LU1688575437",
    "US78463V1070", "LU1366333257", "LU1048315086", "IE00B3RGB191",
    "LU2869556576", "KYG4941A1040", "LU1171460493", "US73936N1054",
    "LU1987754873", "US46438F1012", "LU2428302371", "US46438R1059",
    "IE00BYWJ7569", "LU1692455097", "IE000016ESL7", "IE0000J80JT1",
    "555888222", "UC4642886380", "US92864M4006", "US25459W4540",
    "LU0683769987", "US0032601066", "US46428Q1094", "US4642852044",
    "IM00B3B2JG43", "KYG1367R1083",
]

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
BATCH = 10

s = requests.Session()
for i in range(0, len(ISINS), BATCH):
    batch = ISINS[i : i + BATCH]
    jobs = [{"idType": "ID_ISIN", "idValue": isin} for isin in batch]
    r = s.post(OPENFIGI_URL, json=jobs, headers={"Content-Type": "application/json"}, timeout=30)
    results = r.json()
    for isin, res in zip(batch, results):
        data = res.get("data") if isinstance(res, dict) else None
        if data:
            print(f"{isin:16} {data[0].get('name', '')}")
        else:
            err = res.get("error") if isinstance(res, dict) else "?"
            print(f"{isin:16} <no data: {err}>")
    time.sleep(2.6)
