"""אימות מרכיבי התשואה מול data.gov.il (גמל-נט / פנסיה-נט / ביטוח-נט): סך התרומות לחודש = תשואת החודש של המסלול.

לכל מסלול עם מספר: משווים לכל חודש את סך התרומות בדוח (שורת "תשואה חודשית" / סכום האפיקים) ל-MONTHLY_YIELD של
אותו FUND_ID באותו חודש. התאמה לאורך חודשים רבים = גם המספרים נכונים וגם השיוך למסלול נכון.
מסלול בלי מספר (או עם מספר שלא ברישום): מחפשים את סדרת data.gov שמתאימה לו (כל המסלולים, כל הדומיינים) - התאמה
יחידה וחד-משמעית נשמרת ב-returns/datagov_track_map.json ומשמשת את extract בריצה הבאה (מקור "datagov_yield").

הרצה (בענן - data.gov.il חסום בחלק מהסביבות): python -m scripts.returns.verify
פלט: returns/verify_tracks.csv (שורה למסלול: סטטוס, חודשים שהושוו, פער חציוני/מקסימלי, דומיין),
     returns/verify_gaps.csv (חודשים עם פער > 0.15 נק'), returns/datagov_track_map.json
סטטוס: ok (פער חציוני <= OK_GAP), check (<= CHECK_GAP), mismatch, no_data (המסלול לא ב-data.gov / אין חודשים משותפים).
"""
import csv, json, statistics
from collections import defaultdict
from pathlib import Path

from scripts.policy.fund_registry import api, DOMAINS
from scripts.returns.extract import norm_name

ROOT = Path(__file__).resolve().parents[2]
RET = ROOT / "returns"
OK_GAP, CHECK_GAP, MONTH_GAP = 0.06, 0.3, 0.15


def fetch_yields():
    """{(domain, FUND_ID): {YYYYMM: MONTHLY_YIELD}} - כל ההיסטוריה בשלושת הדומיינים."""
    out = defaultdict(dict)
    for dom, title in DOMAINS.items():
        res = api("package_search", q=title, rows=5)
        pkg = next((p for p in res["results"] if p.get("title") == title), res["results"][0])
        rids = [r["id"] for r in pkg["resources"] if r.get("datastore_active") and r.get("format", "").upper() == "CSV"
                and "שינויים" not in r.get("name", "")]
        n = 0
        for rid in rids:
            off = 0
            while True:
                try:
                    r = api("datastore_search", resource_id=rid, fields="FUND_ID,REPORT_PERIOD,MONTHLY_YIELD", limit=32000, offset=off)
                except Exception as e:
                    print(dom, rid, "error", e, flush=True)
                    break
                for x in r["records"]:
                    try:
                        y = float(x["MONTHLY_YIELD"])
                    except (TypeError, ValueError):
                        continue
                    p = str(x["REPORT_PERIOD"])[:6]
                    out[(dom, str(x["FUND_ID"]).split(".")[0])][f"{p[:4]}-{p[4:6]}"] = y
                    n += 1
                off += len(r["records"])
                if len(r["records"]) < 32000:
                    break
        print(dom, "records", n, flush=True)
    return out


def compare(ours: dict, gov: dict):
    gaps = [(ym, v, gov[ym], abs(v - gov[ym])) for ym, v in ours.items() if ym in gov and v is not None]
    if not gaps:
        return None
    g = [x[3] for x in gaps]
    return {"n": len(g), "median_gap": round(statistics.median(g), 4), "max_gap": round(max(g), 4), "gaps": gaps}


def status(c):
    if not c:
        return "no_data"
    return "ok" if c["median_gap"] <= OK_GAP else "check" if c["median_gap"] <= CHECK_GAP else "mismatch"


def main():
    import os
    cache = os.environ.get("RETURNS_GOV_CACHE")  # ריצה שנייה באותו ג'וב (אחרי בנייה מחדש) - בלי למשוך שוב
    if cache and Path(cache).exists():
        gov = {tuple(k.split("|", 1)): v for k, v in json.loads(Path(cache).read_text("utf-8")).items()}
    else:
        gov = fetch_yields()
        if cache:
            Path(cache).write_text(json.dumps({f"{d}|{f}": v for (d, f), v in gov.items()}), "utf-8")
    by_id = defaultdict(list)
    for (dom, fid) in gov:
        by_id[fid].append(dom)
    # המיפוי מצטבר: מסלול שזוהה בעבר לפי data.gov נשאר מזוהה (אחרת בריצה הבאה הוא חוזר למספר השגוי וחוזר חלילה)
    mp = RET / "datagov_track_map.json"
    ymap = json.loads(mp.read_text("utf-8")) if mp.exists() else {}
    rows, gap_rows = [], []
    for p in sorted((RET / "companies").glob("*/tracks.json")):
        data = json.loads(p.read_text("utf-8"))
        lid = data["legal_id"]
        it = data["assets"].index("total") if "total" in data["assets"] else None
        for t in data["tracks"]:
            ours = {ym: (v["c"][it] if it is not None and len(v["c"]) > it else None) for ym, v in t["m"].items()}
            ours = {k: v for k, v in ours.items() if v is not None}
            no = t.get("track_no")
            best, dom = None, None
            if no:
                for d in by_id.get(no, []):
                    c = compare(ours, gov[(d, no)])
                    if c and (best is None or c["median_gap"] < best["median_gap"]):
                        best, dom = c, d
            st = status(best)
            found = None
            # בלי מספר / מספר שלא מתאים: חיפוש הסדרה המתאימה בכל data.gov (לפחות 3 חודשים משותפים, התאמה חד-משמעית)
            if len(ours) >= 3 and (not no or st in ("mismatch", "no_data") or (t.get("track_no_src") or "").endswith("_unverified")):
                cands = []
                for (d, fid), series in gov.items():
                    c = compare(ours, series)
                    if c and c["n"] >= 3:
                        cands.append((c["median_gap"], fid, d, c))
                cands.sort(key=lambda x: x[0])
                if cands and cands[0][0] <= 0.03 and (len(cands) == 1 or cands[1][0] > max(0.08, 3 * cands[0][0]) or cands[1][1] == cands[0][1]):
                    found = cands[0]
                    if found[1] != no:
                        for nm in t.get("names") or [t.get("name") or ""]:  # השמות כפי שבקבצים - המפתח של extract
                            ymap[f"{lid}|{norm_name(nm)}"] = found[1]
            if st == "mismatch" and t.get("track_no_src") == "datagov_yield" and not found:
                for nm in t.get("names") or []:
                    ymap.pop(f"{lid}|{norm_name(nm)}", None)
            row = {"legal_id": t.get("owner") or lid, "key": t["key"], "track_no": no, "track_no_src": t.get("track_no_src"), "track_name": t.get("name"),
                   "domain": dom, "status": st, "n": best and best["n"], "median_gap": best and best["median_gap"],
                   "max_gap": best and best["max_gap"], "months": len(ours),
                   "datagov_match": found and found[1], "datagov_match_gap": found and found[0]}
            rows.append(row)
            for ym, a, b, g in (best or {}).get("gaps", []):
                if g > MONTH_GAP:
                    gap_rows.append({"legal_id": t.get("owner") or lid, "key": t["key"], "track_no": no, "ym": ym, "ours": a, "datagov": b, "gap": round(g, 4)})
    with open(RET / "verify_tracks.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]) if rows else ["legal_id"]); w.writeheader(); w.writerows(rows)
    with open(RET / "verify_gaps.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, ["legal_id", "key", "track_no", "ym", "ours", "datagov", "gap"]); w.writeheader(); w.writerows(gap_rows)
    (RET / "datagov_track_map.json").write_text(json.dumps(ymap, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    c = defaultdict(int)
    for r in rows:
        c[r["status"]] += 1
    print("verify:", dict(c), "map:", len(ymap), "gap months:", len(gap_rows))


if __name__ == "__main__":
    main()
