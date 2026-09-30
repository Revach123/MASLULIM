"""פער מדיניות מול דוחות: משווה טווחי מדיניות (tracks_policy.json) לחשיפה בפועל
לפי master.json (פלט funds_holdings.main). התאמת מסלול: אותו ח.פ. + דמיון שם.

הרצה: python -m scripts.policy.gap --master out/master.json
כיסוי נוכחי: מניות ואג"ח בלבד (לפי עמודות הקטגוריה ב-master). חו"ל/מט"ח/לא-סחיר דורשים
עמודות סיווג שטרם אומתו מול נתונים חיים - ר' README.
"""
import argparse, csv, json
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / (__import__("os").environ.get("POLICY_OUT") or "policy")  # ריצה לחברה: policy/companies/<LegalId>
ACTUAL = {
    "equity": ["מניות מבכ ויהש", "לא סחיר מניות מבכ ויהש"],
    "bonds": ["איגרות חוב", "איגרות חוב ממשלתיות", "לא סחיר איגרות חוב",
              "לא סחיר איגרות חוב ממשלתיות", "לא סחיר איגרות חוב מיועדות"],
}
NAME_KEYS = ["שם מסלול", "שם מסלול ארוך", "שם מסלול השקעה"]
TOL = 1.0  # נקודות אחוז סובלנות


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", type=Path, required=True)
    a = ap.parse_args()
    master = json.loads(a.master.read_text("utf-8"))
    policy = json.loads((OUT / "tracks_policy.json").read_text("utf-8")) if (OUT / "tracks_policy.json").exists() else []
    # פורמט מובנה (long): רשומה לכל מסלול עם טווחי מניות/מט"ח; מפתח מדויק לפי מספר מסלול
    wide: dict[str, dict] = {}
    lp = OUT / "tracks_policy_long.json"
    long_rows = json.loads(lp.read_text("utf-8")) if lp.exists() else []
    # כמה גרסאות/מסמכים יכולים לתאר אותו מסלול: נשארים עם המסמך העדכני (שנה, ואז מועד ראיית המסמך)
    tk = lambda r: r.get("track_code") or f"{r['legal_id']}-{r['fund_id']}"  # מיטב: כמה מסלולים חולקים fund_id
    best: dict[tuple, tuple] = {}
    for r in long_rows:
        k = (tk(r), r.get("year") or "")
        best[k] = max(best.get(k, ("", "", "")), (r.get("year") or "", r.get("doc_first_seen") or "", r["url"]))
    for r in long_rows:
        if not r.get("asset_key") or r.get("min_pct") is None:
            continue
        if (r.get("year") or "", r.get("doc_first_seen") or "", r["url"]) != best[(tk(r), r.get("year") or "")]:
            continue
        w = wide.setdefault(f"{tk(r)}|{r.get('year')}", {"legal_id": r["legal_id"], "track_name": r["track_name"],
                                                       "ids": [x for x in (r.get("track_no"), r["fund_id"]) if x], "url": r["url"]})
        w[f"{r['asset_key']}_min"], w[f"{r['asset_key']}_max"] = r["min_pct"], r["max_pct"]
    policy = list(wide.values()) + policy
    by_co: dict[str, list] = {}
    by_fund: dict[str, dict] = {}  # קוד קופה ייחודי ברישום - מתאים גם כשה-legal_id במסמך שונה (אתר משותף לכמה חברות)
    for m in master:
        co, _, fid = str(m["מפתח"]).partition("_")
        by_co.setdefault(co, []).append(m)
        by_fund[fid] = m

    def tname(m):
        return next((str(m[k]) for k in NAME_KEYS if m.get(k)), "")

    rows = []
    for p in policy:
        exact = [by_fund[i] for i in p.get("ids", []) if i in by_fund][:1]  # מספר מסלול קודם, אחר כך קוד קופה
        cands = [(1.0, exact[0])] if exact else [(SequenceMatcher(None, p["track_name"], tname(m)).ratio(), m) for m in by_co.get(p["legal_id"], [])]
        if not cands:
            rows.append({"legal_id": p["legal_id"], "track_name": p["track_name"], "status": "חברה ללא מסלולים בדוחות"}); continue
        ratio, m = max(cands, key=lambda x: x[0])
        if ratio < 0.85:
            rows.append({"legal_id": p["legal_id"], "track_name": p["track_name"], "status": "אין התאמת מסלול",
                         "best_match": tname(m), "match_ratio": round(ratio, 2)}); continue
        for k, cols in ACTUAL.items():
            lo, hi = p.get(f"{k}_min"), p.get(f"{k}_max")
            if lo is None and hi is None:
                continue
            vals = [float(m.get(c) or 0) for c in cols]
            act = sum(vals)
            act = act * 100 if act <= 1.5 else act  # master: יחס או אחוזים
            gap = (act - hi) if hi is not None and act > hi + TOL else (act - lo) if lo is not None and act < lo - TOL else 0
            rows.append({"legal_id": p["legal_id"], "track_key": m["מפתח"], "track_name": p["track_name"],
                         "matched_name": tname(m), "match_ratio": round(ratio, 2), "asset": k,
                         "policy_min": lo, "policy_max": hi, "actual_pct": round(act, 2),
                         "gap_pp": round(gap, 2), "status": "חריגה" if gap else "בטווח", "source_url": p["url"]})
    fields = ["legal_id", "track_key", "track_name", "matched_name", "match_ratio", "asset", "policy_min",
              "policy_max", "actual_pct", "gap_pp", "status", "best_match", "source_url"]
    with open(OUT / "policy_gap.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print(f"[gap] {len(rows)} שורות, חריגות: {sum(r['status'] == 'חריגה' for r in rows)}")


if __name__ == "__main__":
    main()
