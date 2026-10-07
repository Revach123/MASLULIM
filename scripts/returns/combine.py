"""איחוד מרכיבי התשואה של כל החברות לטבלאות ב-returns/ (נבנות מחדש בכל ריצה - אין התנגשות בין ריצות חברה).

הרצה: python -m scripts.returns.combine
פלט:
  returns/tracks.csv          - שורה למסלול: מספר + מקור, שם, מוצר, חודש ראשון/אחרון, תשואה אחרונה, תיקונים, אימות data.gov
  returns/monthly_totals.csv  - שורה למסלול×חודש: סך התרומה (=תשואת החודש), תרומת המניות, הדוח שממנו נלקח
  returns/coverage.csv        - שורה לחברה: סריקה (עמודים/קבצים/שגיאות), מסלולים שנמצאו מול הרישום הרשמי, טווח חודשים
  returns/nostro.csv          - נוסטרו של חברות הביטוח (רבעוני)
  returns/index.json          - סיכום לאתר (Revach: returns.html)
"""
import csv, json
from collections import defaultdict
from pathlib import Path

from scripts.returns.extract import Registry

ROOT = Path(__file__).resolve().parents[2]
RET = ROOT / "returns"
COMP = RET / "companies"


def _w(name, fields, rows):
    with open(RET / name, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def company_names():
    out = {}
    m = ROOT / "manifest.csv"
    if m.exists():
        for r in csv.DictReader(open(m, encoding="utf-8-sig")):
            out[r["LegalId"]] = r["ParentCorpName"].strip()
    for p in (ROOT / "scripts" / "policy" / "sites").glob("*.json"):
        c = json.loads(p.read_text("utf-8"))
        out.setdefault(c["legal_id"], c.get("name") or c["legal_id"])
    return out


def main():
    reg = Registry()
    names = company_names()
    vpath = RET / "verify_tracks.csv"
    ver = {(r["legal_id"], r["key"]): r for r in csv.DictReader(open(vpath, encoding="utf-8-sig"))} if vpath.exists() else {}
    tracks_rows, monthly, cov, nostro_rows, idx = [], [], [], [], []
    ids = sorted(set(names) | {p.name for p in COMP.glob("*") if p.is_dir()})
    for lid in ids:
        d = COMP / lid
        rep = json.loads((d / "crawl_report.json").read_text("utf-8")) if (d / "crawl_report.json").exists() else {}
        index = json.loads((d / "docs_index.json").read_text("utf-8")) if (d / "docs_index.json").exists() else {}
        data = json.loads((d / "tracks.json").read_text("utf-8")) if (d / "tracks.json").exists() else {"tracks": [], "docs": {}, "assets": []}
        assets = data.get("assets") or []
        ix = {k: i for i, k in enumerate(assets)}
        found = set()
        months_all = []
        for t in data["tracks"]:
            months = list(t["m"])
            months_all += months
            if t.get("track_no"):
                found.add(t["track_no"])
            last = t["m"][months[-1]] if months else None
            tot = lambda v: (v["c"][ix["total"]] if v and "total" in ix and len(v["c"]) > ix["total"] else None)
            v = ver.get((lid, t["key"]), {})
            tracks_rows.append({"legal_id": lid, "company": names.get(lid, lid), "key": t["key"], "track_no": t.get("track_no"),
                                "track_no_src": t.get("track_no_src"), "track_name": t.get("name"), "registry_name": t.get("registry_name"),
                                "product": t.get("product"), "first_month": t.get("first"), "last_month": t.get("last"),
                                "n_months": t.get("n_months"), "last_return": tot(last), "revisions": len(t.get("revisions") or []),
                                "verify_status": v.get("status"), "verify_months": v.get("n"), "verify_median_gap": v.get("median_gap"),
                                "docs": len({x["d"] for x in t["m"].values()})})
            for ym, val in t["m"].items():
                st = ix.get("stocks")
                monthly.append({"legal_id": lid, "key": t["key"], "track_no": t.get("track_no"), "ym": ym, "total": tot(val),
                                "stocks": val["c"][st] if st is not None and len(val["c"]) > st else None, "doc": val["d"]})
        regs = set(reg.by_co.get(lid, {}))
        docs_ok = sum(1 for e in index.values() if not e.get("not_returns") and not e.get("parse_error"))
        last_m = max(months_all) if months_all else None
        row = {"legal_id": lid, "company": names.get(lid, lid), "pages": rep.get("pages"), "candidates": rep.get("candidates"),
               "docs_index": len(index), "docs_returns": docs_ok, "not_returns": sum(1 for e in index.values() if e.get("not_returns")),
               "parse_errors": sum(1 for e in index.values() if e.get("parse_error")), "tracks": len(data["tracks"]),
               "tracks_numbered": sum(1 for t in data["tracks"] if t.get("track_no")), "registry_tracks": len(regs),
               "registry_found": len(regs & found), "registry_coverage": round(100 * len(regs & found) / len(regs), 1) if regs else None,
               "first_month": min(months_all) if months_all else None, "last_month": last_m,
               "crawl_errors": " | ".join(rep.get("errors") or [])[:600], "last_crawl": rep.get("run")}
        cov.append(row)
        if (d / "nostro.json").exists():
            for o in json.loads((d / "nostro.json").read_text("utf-8")):
                nostro_rows.append({"legal_id": lid, **o})
        if data["tracks"] or (d / "nostro.json").exists():
            idx.append({**{k: row[k] for k in ("legal_id", "company", "tracks", "tracks_numbered", "registry_tracks", "registry_found",
                                                 "registry_coverage", "first_month", "last_month", "docs_returns")},
                        "nostro": (d / "nostro.json").exists()})
    _w("tracks.csv", list(tracks_rows[0]) if tracks_rows else ["legal_id"], tracks_rows)
    _w("monthly_totals.csv", ["legal_id", "key", "track_no", "ym", "total", "stocks", "doc"], monthly)
    _w("coverage.csv", list(cov[0]) if cov else ["legal_id"], cov)
    nf = ["legal_id", "portfolio", "year", "quarter", "period", "asset_key", "asset_label", "inv_income_ils", "inv_income_share",
          "total_income_ils", "total_income_share", "assets_ils", "assets_share", "d"]
    _w("nostro.csv", nf, nostro_rows)
    tot = defaultdict(int)
    for r in cov:
        tot["companies"] += 1
        tot["with_data"] += bool(r["tracks"])
        tot["tracks"] += r["tracks"]
        tot["registry_tracks"] += r["registry_tracks"]
        tot["registry_found"] += r["registry_found"]
        tot["docs"] += r["docs_returns"]
    (RET / "index.json").write_text(json.dumps({"totals": tot, "companies": idx}, ensure_ascii=False, indent=1), "utf-8")
    print(f"[returns.combine] companies={tot['companies']} with_data={tot['with_data']} tracks={tot['tracks']} "
          f"registry {tot['registry_found']}/{tot['registry_tracks']} docs={tot['docs']}")


if __name__ == "__main__":
    main()
