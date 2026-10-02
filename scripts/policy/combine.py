"""איחוד פלטי כל החברות (policy/companies/<LegalId>/) לטבלאות אחודות ב-policy/.

הרצה: python -m scripts.policy.combine
כל ריצת חברה כותבת רק לתיקייה שלה; הקבצים כאן נבנים מחדש כולם בכל פעם (לכן אין התנגשות בין ריצות).
"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POL = ROOT / "policy"
COMP = POL / "companies"

from .extract import LONG_FIELDS, CHANGE_FIELDS  # noqa: E402

CRAWL_FIELDS = ["legal_id", "company", "homepage", "site_source", "pages", "docs", "errors"]
SITE_CHG_FIELDS = ["detected", "legal_id", "company", "kind", "page", "text", "href"]


def _json(p, default):
    return json.loads(p.read_text("utf-8")) if p.exists() else default


def _csv_rows(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(name, fields, rows):
    with open(POL / name, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def _natural(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s or "")]


def latest_only(rows):
    """לכל (חברה, מסלול, שנה) - רק המסמך העדכני (מור מפרסמת עשרות גרסאות בשנה). ההיסטוריה המלאה נשארת
    ב-policy/companies/<LegalId>/tracks_policy_long.json. עדכני = נראה אחרון, ואז שם קובץ בסדר טבעי (_2026_17 > _2026_8)."""
    best = {}
    for r in rows:
        k = (r.get("legal_id"), r.get("track_code"), r.get("year"))
        cand = (r.get("doc_first_seen") or "", _natural(r.get("url") or ""))
        if k not in best or cand > best[k][0]:
            best[k] = (cand, r.get("url"))
    return [r for r in rows if best[(r.get("legal_id"), r.get("track_code"), r.get("year"))][1] == r.get("url")]


def main():
    long_rows, changes, unparsed, crawl, site_log, docs = [], [], [], [], [], []
    for d in sorted(p for p in COMP.iterdir() if p.is_dir()) if COMP.exists() else []:
        long_rows += _json(d / "tracks_policy_long.json", [])
        changes += _json(d / "policy_changes.json", [])
        unparsed += _json(d / "unparsed_layouts.json", [])
        crawl += _csv_rows(d / "crawl_report.csv")
        site_log += _csv_rows(d / "site_changes_log.csv")
        for url, e in _json(d / "docs_index.json", {}).items():
            docs.append({"legal_id": e["legal_id"], "url": url, "product": e.get("product"), "link_text": e.get("link_text"),
                         "first_seen": e.get("first_seen"), "last_seen": e.get("last_seen"), "file": e.get("file")})
    n_all = len(long_rows)
    long_rows = latest_only(long_rows)
    for r in long_rows:
        r.pop("doc_file", None)  # נגזר מ-url דרך documents.csv
    # רשומה לשורה, בלי רווחים: JSON תקין, diff קריא, ~פי 2.5 קטן (GitHub חוסם קבצים מעל 100MB)
    (POL / "tracks_policy_long.json").write_text(
        "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in long_rows) + "\n]\n", "utf-8")
    (POL / "unparsed_layouts.json").write_text(json.dumps(unparsed, ensure_ascii=False, indent=1), "utf-8")
    _write_csv("tracks_policy_long.csv", LONG_FIELDS, long_rows)
    _write_csv("policy_changes.csv", CHANGE_FIELDS, changes)
    _write_csv("crawl_report.csv", CRAWL_FIELDS, crawl)
    _write_csv("site_changes_log.csv", SITE_CHG_FIELDS, sorted(site_log, key=lambda r: r["detected"]))
    _write_csv("documents.csv", ["legal_id", "product", "link_text", "url", "first_seen", "last_seen", "file"], docs)
    # רשימת האתרים שהתוסף מושך (חוסמים שרתי ענן) - התוסף קורא את הקובץ הזה מהרפו
    ext = []
    for p in sorted((ROOT / "scripts" / "policy" / "sites").glob("*.json")):
        cfg = json.loads(p.read_text("utf-8"))
        if cfg.get("via") == "extension":
            ext.append({k: cfg.get(k) for k in ("legal_id", "name", "home", "pages", "products", "click", "clicks", "any_sheet", "exclude", "settle_ms", "capture_ms", "download_rx", "follow_max", "follow_rx", "timeout_min", "download_delay_ms")})
    (POL / "extension_sites.json").write_text(json.dumps(ext, ensure_ascii=False, indent=1), "utf-8")
    print(f"[combine] companies={len(crawl)} docs={len(docs)} long={len(long_rows)} (history={n_all}) unparsed={len(unparsed)}")
    from . import timeline  # הנתונים האחרונים לכל מסלול + תאריך השינוי האחרון וסוגו (גדול/קטן)
    timeline.main()


if __name__ == "__main__":
    main()
