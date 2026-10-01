"""רישום מסלולים רשמי (data.gov.il, משרד האוצר): מספר מסלול, מספר קופה, שם, חברה מנהלת, ח.פ.

משמש לשיוך מספר מסלול לשורות המדיניות (timeline.py) לפי שם, כשאין מספר בקובץ עצמו.
הרצה: python -m scripts.policy.fund_registry   (GitHub Action policy_registry.yml - שבועי)
פלט: policy/fund_registry.csv - כל עמודות הרישום כפי שהן + עמודות מנורמלות (track_no, kupa_no, legal_id, name, domain).
בנוסף: שם המסלול האחרון מכל אחד מ-גמל-נט/פנסיה-נט/ביטוח-נט (FUND_ID, FUND_NAME, PARENT/MANAGING) - fund_names.csv.
"""
import csv, ssl, sys
from pathlib import Path

import requests, urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

urllib3.disable_warnings()
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "policy"
API = "https://data.gov.il/api/3/action/"
REGISTRY_RID = "b5223cbc-e1b2-4503-a499-97cdcd7190d2"
DOMAINS = {"גמל": "גמל-נט", "פנסיה": "פנסיה-נט", "ביטוח": "ביטוח-נט"}


class LegacyTLS(HTTPAdapter):
    def init_poolmanager(self, *a, **k):
        c = create_urllib3_context(); c.set_ciphers("DEFAULT@SECLEVEL=1")
        c.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
        k["ssl_context"] = c
        return super().init_poolmanager(*a, **k)


S = requests.Session(); S.mount("https://", LegacyTLS()); S.headers["User-Agent"] = "Mozilla/5.0 maslulim-registry"


def api(action, **p):
    j = S.get(API + action, params=p, verify=False, timeout=180).json()
    if not j.get("success"):
        raise RuntimeError(f"{action}: {j.get('error')}")
    return j["result"]


def fetch_all(rid, fields=None):
    out, off = [], 0
    while True:
        kw = dict(resource_id=rid, limit=32000, offset=off)
        if fields:
            kw["fields"] = ",".join(fields)
        r = api("datastore_search", **kw)
        out += r["records"]; off += len(r["records"])
        if len(r["records"]) < 32000 or off >= r.get("total", 0):
            return out


def col(cols, *keys):
    return next((c for c in cols if all(k in c.replace(" ", "") for k in keys)), None)


def digits(v):
    s = str(v or "").strip()
    try:
        return str(int(float(s)))
    except ValueError:
        return s


def registry():
    rows = fetch_all(REGISTRY_RID)
    cols = list(rows[0].keys())
    c = {"track_no": col(cols, "מספר", "מסלול"), "kupa_no": col(cols, "מספר", "קופה"), "domain": col(cols, "תחום"),
         "company": col(cols, "שם", "חברה"), "legal_id": col(cols, "ח.פ") or col(cols, "חפ"),
         "name": col(cols, "שם", "מסלול") or col(cols, "שם", "קופה")}
    print("registry", len(rows), "cols", cols, "->", c, flush=True)
    for r in rows:
        for k, src in c.items():
            if src:
                r[k] = digits(r[src]) if k in ("track_no", "kupa_no", "legal_id") else str(r[src]).strip()
    return rows, cols + [k for k in c if k not in cols]


def fund_names():
    """שם עדכני לכל FUND_ID מגמל-נט/פנסיה-נט/ביטוח-נט (התקופה האחרונה)."""
    out = {}
    for dom, title in DOMAINS.items():
        res = api("package_search", q=title, rows=5)
        pkg = next((p for p in res["results"] if p.get("title") == title), res["results"][0])
        rids = [r["id"] for r in pkg["resources"] if r.get("datastore_active") and r.get("format", "").upper() == "CSV"
                and "שינויים" not in r.get("name", "")]
        for rid in rids[-2:]:  # השנה האחרונה + הקודמת
            try:
                recs = fetch_all(rid, ["FUND_ID", "FUND_NAME", "REPORT_PERIOD", "MANAGING_CORPORATION", "PARENT_COMPANY_NAME",
                                       "FUND_CLASSIFICATION", "STOCK_MARKET_EXPOSURE"])
            except Exception as e:
                print("skip", dom, rid, e, flush=True); continue
            for r in recs:
                k = (dom, digits(r.get("FUND_ID")))
                if k not in out or str(r.get("REPORT_PERIOD")) > str(out[k].get("REPORT_PERIOD")):
                    out[k] = dict(r, domain=dom, FUND_ID=k[1])
        print(dom, "funds", sum(1 for k in out if k[0] == dom), flush=True)
    return list(out.values())


def main():
    rows, cols = registry()
    with open(OUT / "fund_registry.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    try:
        fn = fund_names()
        fc = ["domain", "FUND_ID", "FUND_NAME", "REPORT_PERIOD", "MANAGING_CORPORATION", "PARENT_COMPANY_NAME",
              "FUND_CLASSIFICATION", "STOCK_MARKET_EXPOSURE"]
        with open(OUT / "fund_names.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fc, extrasaction="ignore"); w.writeheader(); w.writerows(fn)
    except Exception as e:
        print("fund_names failed:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
