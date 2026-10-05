"""אימות מספרי של שיוך מסמך מדיניות -> מספר מסלול, מול הנתונים הרשמיים (data.gov.il).

כל קובץ מדיניות מציין את שיעור החשיפה בפועל ביום הדיווח (בדרך כלל 31/12 של השנה הקודמת). גמל-נט/פנסיה-נט/ביטוח-נט
מדווחים לכל מסלול את החשיפה למניות ולמט"ח באותו חודש. אם המספרים קרובים - השיוך נכון; אם רחוקים - כנראה שיוך שגוי
(שינוי שם מסלול, התאמת שם לרישום, מיפוי ידני שהתיישן). כך כל השיוכים נבדקים, בלי קשר לדרך שבה נמצא המספר.

פלט: policy/mapping_check.csv (שורה למסלול: מקור המספר, חשיפה במסמך מול data.gov, סטטוס) + סיכום להדפסה.
סטטוס: ok (פער <= 5 נק'), check (5-12), mismatch (> 12), no_data.
הרצה (בענן - data.gov.il חסום בחלק מהסביבות): python -m scripts.policy.verify_mapping [--year 2026]
"""
import argparse, csv, json
from collections import defaultdict
from pathlib import Path
from scripts.policy.fund_registry import api, DOMAINS

POL = Path(__file__).resolve().parents[2] / "policy"
FIELDS = ["FUND_ID", "REPORT_PERIOD", "TOTAL_ASSETS", "STOCK_MARKET_EXPOSURE", "FOREIGN_CURRENCY_EXPOSURE"]


def datagov_period(period):
    """{fund_id: {"equity": %, "fx": %, "assets": ₪M}} לחודש נתון, משלושת הדומיינים.
    החשיפות בגמל/פנסיה/ביטוח-נט מדווחות במיליוני ₪ - מחושב אחוז מסך הנכסים."""
    out = {}
    for dom, title in DOMAINS.items():
        res = api("package_search", q=title, rows=5)
        pkg = next((p for p in res["results"] if p.get("title") == title), res["results"][0])
        rids = [r["id"] for r in pkg["resources"] if r.get("datastore_active") and r.get("format", "").upper() == "CSV"
                and "שינויים" not in r.get("name", "")]
        n = 0
        for rid in rids[-3:]:
            for pv in (int(period), str(period)):
                off = 0
                while True:
                    try:
                        r = api("datastore_search", resource_id=rid, filters=json.dumps({"REPORT_PERIOD": pv}),
                                fields=",".join(FIELDS), limit=32000, offset=off)
                    except Exception:
                        break
                    for x in r["records"]:
                        try:
                            tot = float(x["TOTAL_ASSETS"])
                        except (TypeError, ValueError):
                            continue
                        if tot <= 0:
                            continue
                        pct = lambda k: round(100 * float(x[k]) / tot, 2) if x.get(k) not in (None, "") else None
                        out[(dom, str(x["FUND_ID"]))] = {"equity": pct("STOCK_MARKET_EXPOSURE"),
                                                         "fx": pct("FOREIGN_CURRENCY_EXPOSURE"), "assets": tot}
                        n += 1
                    off += len(r["records"])
                    if len(r["records"]) < 32000:
                        break
                if n:
                    break
        print(dom, period, "funds", n, flush=True)
    return out


def doc_exposures(year):
    """{(legal_id, track_no): {"equity": %, "fx": %, "source": ..., "name": ...}} מהמסמכים של השנה."""
    # המספר נקבע בשלב הסיכום (track_numbers) - הצירוף לפי track_code, לא לפי track_no שבשורות המסמך
    summ = {(r["legal_id"], r["track_code"]): r for r in csv.DictReader(open(POL / "tracks_summary.csv", encoding="utf-8-sig"))
            if r["track_no"] and r["year"] == str(year)}
    out = defaultdict(dict)
    for r in json.loads((POL / "tracks_policy_long.json").read_text("utf-8")):
        s = summ.get((r.get("legal_id"), r.get("track_code")))
        if r.get("year") != str(year) or not s or r.get("current_pct") is None or r.get("asset_key") not in ("equity", "fx"):
            continue
        k = (s["legal_id"], s["track_no"])
        out[k].setdefault(r["asset_key"], r["current_pct"])
        out[k]["source"] = s["track_no_source"]
        out[k]["name"] = s["track_name"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args()
    gov = datagov_period(f"{a.year - 1}12")
    # מספרי מסלול חוזרים בין הדומיינים (128 = "כלל תמר" בגמל וגם "מנורה ביטוח כללי" בביטוח): הדומיין לפי הרישום הרשמי
    dom_of = defaultdict(set)
    for r in csv.DictReader(open(POL / "fund_registry.csv", encoding="utf-8-sig")):
        if r.get("track_no") and r.get("legal_id"):
            dom_of[(r["legal_id"], r["track_no"])].add(r.get("domain") or r.get("תחום"))
    rows = []
    for (lid, tn), d in sorted(doc_exposures(a.year).items()):
        doms = dom_of.get((lid, tn)) or set(DOMAINS)
        g = [gov[(dm, tn)] for dm in doms if (dm, tn) in gov]
        g = g[0] if len(g) == 1 else (max(g, key=lambda v: v["assets"]) if g else None)
        diffs = [abs(d[k] - g[k]) for k in ("equity", "fx") if g and d.get(k) is not None and g.get(k) is not None]
        worst = max(diffs) if diffs else None
        status = "no_data" if worst is None else "ok" if worst <= 5 else "check" if worst <= 12 else "mismatch"
        rows.append({"legal_id": lid, "track_no": tn, "track_no_source": d.get("source"), "track_name": d.get("name"),
                     "doc_equity": d.get("equity"), "gov_equity": g and g["equity"], "doc_fx": d.get("fx"),
                     "gov_fx": g and g["fx"], "max_gap": worst, "status": status})
    with open(POL / "mapping_check.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(rows)
    tot = defaultdict(lambda: defaultdict(int))
    for r in rows:
        tot[r["track_no_source"]][r["status"]] += 1
    for src, c in sorted(tot.items()):
        print(f"{src:24} " + " ".join(f"{k}={v}" for k, v in sorted(c.items())))
    for r in rows:
        if r["status"] in ("mismatch", "check"):
            print(r["status"], r["legal_id"], r["track_no"], r["track_no_source"], (r["track_name"] or "")[:40],
                  "equity", r["doc_equity"], "/", r["gov_equity"], "fx", r["doc_fx"], "/", r["gov_fx"])


if __name__ == "__main__":
    main()
