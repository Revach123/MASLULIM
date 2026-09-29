"""One-off probe: does Morningstar's own public site (the actual source
behind Yahoo's funds_data.asset_classes) expose more/better ISIN coverage
directly, for funds where Yahoo's search came up empty or where we only
have a truncated/ambiguous name? Tests a few different public,
no-auth-key endpoints Morningstar exposes for its fund quote pages.
"""
import json

import requests

ISINS = [
    "LI1165463954",  # ACC SICAV ACCUM (AIF)
    "KYG4941A1040",  # ION Macro Feeder Fund
    "LU1171460493",  # Fullgoal International Funds
    "LU1692455097",  # Janus Henderson Pan Euro Smaller Companies
    "IE000016ESL7",  # ENAM India Opportunities
    "US73936N1054",  # iShares U.S. Power Infrastructure
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MASLULIM-probe/1.0)"}

print("=== Morningstar global search API ===")
for isin in ISINS:
    try:
        r = requests.get(
            "https://www.morningstar.com/api/v2/search/securities",
            params={"q": isin, "limit": 3}, headers=HEADERS, timeout=15,
        )
        print(f"\n--- {isin} --- status={r.status_code}")
        print(r.text[:800])
    except Exception as e:
        print(f"{isin}: failed {e}")

print("\n=== Morningstar quicktake/security detail (by ISIN as performanceId guess) ===")
for isin in ISINS[:2]:
    try:
        r = requests.get(
            f"https://www.us-api.morningstar.com/sal/sal-service/fund/quote/v2/{isin}/data",
            headers=HEADERS, timeout=15,
        )
        print(f"\n--- {isin} --- status={r.status_code}")
        print(r.text[:500])
    except Exception as e:
        print(f"{isin}: failed {e}")

print("\n=== Trustnet public API ===")
for isin in ISINS:
    try:
        r = requests.get(
            "https://www.trustnet.com/api/factsheets/search",
            params={"q": isin}, headers=HEADERS, timeout=15,
        )
        print(f"\n--- {isin} --- status={r.status_code}")
        print(r.text[:500])
    except Exception as e:
        print(f"{isin}: failed {e}")
