"""הדפסת השורות החודשיות של מסלולים מ-data.gov.il (גמל-נט/פנסיה-נט/ביטוח-נט) - לבדיקות ידניות מהענן
(data.gov.il חסום מסביבות מסוימות). מדפיס JSON שורה לכל (מסלול, חודש), החודשים האחרונים.

הרצה: python -m scripts.policy.datagov_peek --domain ביטוח --ids 13721 9536 [--months 12]
"""
import argparse, json
from scripts.policy.fund_registry import api, DOMAINS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="ביטוח", choices=list(DOMAINS))
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--months", type=int, default=12)
    a = ap.parse_args()
    res = api("package_search", q=DOMAINS[a.domain], rows=5)
    pkg = next((p for p in res["results"] if p.get("title") == DOMAINS[a.domain]), res["results"][0])
    rids = [r["id"] for r in pkg["resources"] if r.get("datastore_active") and r.get("format", "").upper() == "CSV"
            and "שינויים" not in r.get("name", "")]
    rows = []
    for rid in rids[-2:]:  # השנה האחרונה + הקודמת
        for fid in a.ids:
            for v in (int(fid), str(fid)):  # FUND_ID מספרי או טקסט, לפי המשאב
                try:
                    recs = api("datastore_search", resource_id=rid, filters=json.dumps({"FUND_ID": v}), limit=200)["records"]
                except Exception:
                    recs = []
                if recs:
                    rows += recs; break
    rows.sort(key=lambda r: (str(r.get("FUND_ID")), str(r.get("REPORT_PERIOD"))))
    keep = {}
    for r in rows:
        keep.setdefault(str(r.get("FUND_ID")), []).append(r)
    for fid, rs in keep.items():
        for r in rs[-a.months:]:
            r.pop("_id", None)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    print("fields:", sorted({k for r in rows for k in r}))


if __name__ == "__main__":
    main()
