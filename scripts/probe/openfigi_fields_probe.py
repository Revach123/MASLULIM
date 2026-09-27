"""Probe: what does OpenFIGI actually return per ISIN beyond 'name'? Testing
whether marketSector/securityType/securityType2 are a reliable *structured*
equity-vs-bond signal, as an alternative to keyword-matching the (often
truncated) report name. Also tries ESMA FIRDS (CFI code) for a couple of
EU ISINs, if reachable from this runner, as a second candidate structured
source.

Sample: real ISINs from the current MASLULIM missing_foreign_funds.py
output, chosen for known ground truth (publicly known fund category).
"""
import json
import time

import requests

SAMPLE = [
    ("LU0569863243", "bond", "UBAM Global High Yield Solution"),
    ("IE00BMD7Z621", "bond", "Neuberger Berman Global Flexible Credit"),
    ("IE0034085260", "bond", "PIMCO GIS Global (bond range)"),
    ("AU00000A2000", "equity", "BetaShares Australia 200 ETF"),
    ("US71531T1051", "equity", "Pershing Square USA Ltd"),
    ("LU2126068639", "equity", "Kotak Funds India Midcap"),
    ("IE00BD0NCR01", "?", "BlackRock Idx Sel"),
    ("X9X9USD58946", "cash", "BlackRock ICS US Dollar (money market - placeholder ISIN?)"),
]

print("=== OpenFIGI raw mapping ===")
jobs = [{"idType": "ID_ISIN", "idValue": isin} for isin, _, _ in SAMPLE]
r = requests.post("https://api.openfigi.com/v3/mapping", json=jobs,
                   headers={"Content-Type": "application/json"}, timeout=30)
print("status:", r.status_code)
results = r.json()
for (isin, truth, label), res in zip(SAMPLE, results):
    print(f"\n--- {isin} ({label}) [expected: {truth}] ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
time.sleep(3)

print("\n=== ESMA FIRDS (CFI code) probe ===")
# ESMA FIRDS FITRS/FIRDS full reference data search API (public, no key)
for isin, truth, label in SAMPLE[:4]:
    try:
        resp = requests.get(
            "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select",
            params={"q": f"ISIN:{isin}", "wt": "json", "rows": 1},
            timeout=20,
        )
        print(f"\n--- FIRDS search {isin} ({label}) ---")
        print("status:", resp.status_code)
        print(resp.text[:1500])
    except Exception as e:
        print(f"FIRDS lookup failed for {isin}: {e}")
    time.sleep(1)
