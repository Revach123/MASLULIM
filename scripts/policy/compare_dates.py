"""השוואה: שנה/תאריך מהפרסור (תוכן, שם קובץ, קישור, מטא-דאטה) מול מועד הפרסום באתר (Last-Modified / תיקיית ההעלאה).

לכל מסמך עם מועד פרסום ועם שורות מפוענחות:
  year_fit   - האם שנת המדיניות שנקבעה מתיישבת עם מועד הפרסום (מדיניות לשנה Y מתפרסמת אוקט' Y-1 עד דצמ' Y)
  date_src   - מקור התאריך שנבחר היום (doc = תאריך בשם/קישור, file_meta, last_modified, url_folder ...)
  gap_days   - פער בין התאריך שנבחר לבין מועד הפרסום
פלט: policy/date_compare.csv + סיכום. הרצה: python -m scripts.policy.compare_dates
"""
import csv, json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from scripts.policy.pubdate import published, fits
from scripts.policy.timeline import version_date

POL = Path(__file__).resolve().parents[2] / "policy"


def main():
    out = []
    for idx in sorted((POL / "companies").glob("*/docs_index.json")):
        lid = idx.parent.name
        index = json.loads(idx.read_text("utf-8"))
        lp = idx.parent / "tracks_policy_long.json"
        years = defaultdict(Counter)
        if lp.exists():
            for r in json.loads(lp.read_text("utf-8")):
                if r.get("year"):
                    years[r["url"]][r["year"]] += 1
        for url, ent in index.items():
            if url not in years:
                continue
            pub, psrc = published(url, ent)
            if not pub:
                continue
            year = years[url].most_common(1)[0][0]
            vd, vsrc = version_date(url, ent, year)
            gap = (date.fromisoformat(vd) - pub).days if vd and len(vd) == 10 else None
            out.append({"legal_id": lid, "url": url, "year": year, "pub_date": pub.isoformat(), "pub_src": psrc,
                        "year_fit": fits(year, pub), "chosen_date": vd, "date_src": vsrc, "gap_days": gap})
    with open(POL / "date_compare.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    n = len(out)
    print(f"documents with publication date and parsed rows: {n}")
    print("year fits publication date:", Counter(r["year_fit"] for r in out))
    print("chosen date source:", Counter(r["date_src"] for r in out).most_common())
    by = defaultdict(list)
    for r in out:
        if r["gap_days"] is not None:
            by[r["date_src"]].append(abs(r["gap_days"]))
    for s, g in sorted(by.items()):
        g.sort()
        print(f"  {s:14} n={len(g):5} median|gap|={g[len(g)//2]:4}d  <=30d={sum(x <= 30 for x in g)/len(g):.0%}  >180d={sum(x > 180 for x in g)}")


if __name__ == "__main__":
    main()
