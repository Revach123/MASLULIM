"""דוח חסרים: לכל מסלול ברישום שלא נמצא - סיבה סבירה והצעה לריצה הבאה. נבנה מחדש בכל combine.

פלט:
  returns/gaps.csv        - שורה למסלול חסר: חברה, מסלול, תחום, סיבת החברה, מועמד לפי שם (מסלול בלי מספר), הצעה
  returns/gaps_companies.csv - שורה לחברה: סיבה אחת עיקרית + מונים + הצעה
"""
import csv, json
from collections import Counter
from pathlib import Path

from scripts.returns.extract import Registry, _toks

ROOT = Path(__file__).resolve().parents[2]
RET = ROOT / "returns"
COMP = RET / "companies"
SITES = ROOT / "scripts" / "policy" / "sites"


def _cfg(lid):
    p = SITES / f"{lid}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def company_reason(row, cfg, rep, index):
    """(קוד, הסבר, הצעה) - הסיבה העיקרית לכך שחברה חסרה מסלולים."""
    errs = rep.get("errors") or []
    html_pages = sum(1 for e in errs if "not_a_document" in e)
    via_ext = bool(cfg.get("via") == "extension")
    docs = int(row["docs_returns"] or 0)
    cands = int(row["candidates"] or 0)
    unid = int(row["unidentified_blocks"] or 0)
    if cfg.get("returns_unpublished"):  # נבדק ידנית/בתוסף: החברה לא מפרסמת (עדיין) - התוסף/הסריקה ימשכו אוטומטית כשיופיעו
        return ("not_published", cfg["returns_unpublished"], "אין פעולה - הסריקה האוטומטית תיקלוט כשיפורסמו")
    if cfg.get("returns_skip_home"):
        return ("blocked", "האתר חוסם גם את הדפדפן הביתי", "תוסף Chrome שמריץ סריקת מרכיבי תשואה, או קבצים ידניים ל-policy/inbox/<id>/returns/")
    if via_ext and docs == 0:
        return ("home_no_files", "הסריקה הביתית לא הורידה קבצי מרכיבי תשואה",
                "לבדוק returns/_home/<id>/crawl.log; לוודא returns_pages ו-returns_ctx; להריץ only=<id> (75 דקות)")
    if docs == 0 and cands == 0:
        return ("no_candidates", "לא נמצאו קישורים שנראים כמרכיבי תשואה", "להוסיף returns_pages / returns_text מהאתר (או החברה לא מפרסמת)")
    if docs == 0:
        return ("candidates_not_returns", f"{cands} קבצים נמצאו אך אף אחד לא מרכיבי תשואה", "להרחיב את RETURNS_RX או returns_text לשמות הקבצים")
    if html_pages:
        return ("html_pages", f"{html_pages} עמודי HTML (לא קבצים) סומנו not_a_document", "לפרסר טבלאות HTML מעמודי ה-iframe")
    if unid > 5:
        return ("unidentified", f"{unid} בלוקים בלי זהות מסלול", "להוסיף track_no_map / כללי זיהוי לפי שם")
    return ("partial", "נמצאו חלק מהמסלולים; השאר כנראה לא מפורסמים בקבצים שנסרקו", "לבדוק עמודים נוספים באתר (returns_pages) או שנים קודמות (returns_click_texts)")


def main():
    reg = Registry()
    cov = {r["legal_id"]: r for r in csv.DictReader(open(RET / "coverage.csv", encoding="utf-8-sig"))}
    trk = {}
    for r in csv.DictReader(open(RET / "tracks.csv", encoding="utf-8-sig")):
        trk.setdefault(r["legal_id"], []).append(r)
    rows, crow = [], []
    for lid, row in sorted(cov.items()):
        regs = reg.by_co.get(lid, {})
        if not regs:
            continue
        found = {t["track_no"] for t in trk.get(lid, []) if t.get("track_no")}
        miss = {no: nm for no, nm in regs.items() if no not in found}
        if not miss:
            continue
        d = COMP / lid
        rep = json.loads((d / "crawl_report.json").read_text("utf-8")) if (d / "crawl_report.json").exists() else {}
        index = json.loads((d / "docs_index.json").read_text("utf-8")) if (d / "docs_index.json").exists() else {}
        cfg = _cfg(lid)
        code, why, hint = company_reason(row, cfg, rep, index)
        unnamed = []  # מסלולים שנמצאו בלי מספר (שם בלבד) - מועמדים להתאמה
        tj = d / "tracks.json"
        if tj.exists():
            for t in json.loads(tj.read_text("utf-8")).get("tracks", []):
                if not t.get("track_no") and not str(t.get("key", "")).startswith("u:") and t.get("name"):
                    unnamed.append(t)
        crow.append({"legal_id": lid, "company": row["company"], "registry_tracks": len(regs), "found": len(regs) - len(miss), "missing": len(miss),
                     "reason": code, "why": why, "hint": hint, "unnumbered_tracks": len(unnamed), "docs_returns": row["docs_returns"],
                     "candidates": row["candidates"]})
        for no, nm in sorted(miss.items()):
            t = _toks(nm)
            best, sc = None, 0.0
            for u in unnamed:
                v = _toks(u["name"])
                if t and v:
                    j = len(t & v) / len(t | v)
                    if j > sc:
                        best, sc = u, j
            rows.append({"legal_id": lid, "company": row["company"], "track_no": no, "track_name": nm, "domain": reg.domain.get(no),
                         "reason": code, "candidate_unnumbered": best["name"] if best and sc >= 0.5 else "", "candidate_score": round(sc, 2) if best and sc >= 0.5 else "",
                         "hint": hint})
    for name, data in (("gaps.csv", rows), ("gaps_companies.csv", crow)):
        with open(RET / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, list(data[0]) if data else ["legal_id"])
            w.writeheader()
            w.writerows(data)
    c = Counter(r["reason"] for r in crow)
    print(f"[returns.gaps] companies={len(crow)} missing_tracks={len(rows)} reasons={dict(c)}")


if __name__ == "__main__":
    main()
