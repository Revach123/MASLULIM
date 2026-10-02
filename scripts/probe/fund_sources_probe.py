"""בדיקת מקורות לסיווג קרנות נאמנות זרות (UCITS) לפי ISIN - מה כל מקור מחזיר. הרצה ב-CI בלבד
(fund_sources_probe.yml); תוצאה ללוג."""
import re
import sys
import time

import requests

ISINS = sys.argv[1:] or ["LI1165463954", "IE00B804LV55", "LU1171460493", "LU1987754873", "LU2428302371",
                         "IE000016ESL7", "LU2486835627", "LU1687402807", "LU2656573974", "IE00B66MWN84"]
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
     "Accept-Language": "en-GB,en;q=0.9"}
s = requests.Session()
s.headers.update(H)


def show(label, r, n=600):
    body = r.text if r is not None else ""
    print(f"  [{label}] {getattr(r, 'status_code', '-')} len={len(body)}")
    return body


def text_of(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


for isin in ISINS:
    print(f"== {isin}")
    # FT: חיפוש -> סימול -> עמוד ההחזקות (Asset allocation)
    try:
        r = s.get("https://markets.ft.com/data/searchapi/searchsecurities", params={"query": isin}, timeout=30)
        b = show("ft search", r)
        print("   ", b[:400].replace("\n", " "))
        syms = re.findall(r'"symbol"\s*:\s*"([^"]+)"', b)
        for sym in syms[:1]:
            for page in ("summary", "holdings"):
                r2 = s.get(f"https://markets.ft.com/data/funds/tearsheet/{page}", params={"s": sym}, timeout=30)
                t = text_of(show(f"ft {page} {sym}", r2))
                for kw in ("Asset type", "Morningstar category", "Fund type", "Investment style", "Sector"):
                    i = t.find(kw)
                    if i >= 0:
                        print(f"     {kw}: {t[i:i + 300]}")
    except Exception as e:
        print("  ft error", e)
    # Morningstar UK: חיפוש לפי ISIN
    try:
        r = s.get("https://www.morningstar.co.uk/uk/util/SecuritySearch.ashx",
                  params={"q": isin, "limit": 3, "preferedList": ""}, timeout=30)
        b = show("morningstar search", r)
        print("   ", b[:400].replace("\n", " | "))
    except Exception as e:
        print("  morningstar error", e)
    # Yahoo search (לשם השוואה - המקור הקיים)
    try:
        r = s.get("https://query2.finance.yahoo.com/v1/finance/search", params={"q": isin, "quotesCount": 3}, timeout=30)
        b = show("yahoo search", r)
        print("   ", b[:300].replace("\n", " "))
    except Exception as e:
        print("  yahoo error", e)
    time.sleep(1)
