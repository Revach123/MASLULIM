"""מיזוג פלטי ג'ובים מקבילים (אחד לכל חברה) לתיקיית policy/ אחת.

הרצה: python -m scripts.policy.merge <תיקיית ארטיפקטים>   (בכל תת-תיקייה: policy/ של ג'וב אחד)
docs_index.json: איחוד לפי url (הרשומה עם last_seen מאוחר יותר גוברת); raw/ ו-site_snapshot/ מועתקים;
דוחות CSV: שורה לכל legal_id (האחרון גובר); site_changes.json: שרשור. אחרי המיזוג מריצים extract --all.
"""
import csv, json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "policy"


def merge_csv(name, parts):
    rows, header = {}, None
    for p in [OUT / name] + parts:
        if not p.exists():
            continue
        with open(p, encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            h = next(r, None)
            header = header or h
            for row in r:
                if row:
                    rows[row[0]] = row
    if header:
        with open(OUT / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(header); w.writerows(rows[k] for k in sorted(rows))


def main(art: Path):
    jobs = [d / "policy" if (d / "policy").is_dir() else d for d in sorted(art.iterdir()) if d.is_dir()]
    index = json.loads((OUT / "docs_index.json").read_text("utf-8")) if (OUT / "docs_index.json").exists() else {}
    changes, new_docs = [], []
    for j in jobs:
        ip = j / "docs_index.json"
        if ip.exists():
            for url, ent in json.loads(ip.read_text("utf-8")).items():
                if url not in index or (ent.get("last_seen") or "") >= (index[url].get("last_seen") or ""):
                    index[url] = ent
        for sub in ("raw", "site_snapshot"):
            if (j / sub).is_dir():
                shutil.copytree(j / sub, OUT / sub, dirs_exist_ok=True)
        for fn, acc in (("site_changes.json", changes), ("new_docs.json", new_docs)):
            if (j / fn).exists():
                acc += json.loads((j / fn).read_text("utf-8"))
    OUT.mkdir(exist_ok=True)
    (OUT / "docs_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "site_changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "new_docs.json").write_text(json.dumps(new_docs, ensure_ascii=False, indent=1), "utf-8")
    for name in ("crawl_report.csv", "site_report.csv"):
        merge_csv(name, [j / name for j in jobs])
    if changes:  # יומן מצטבר
        log = OUT / "site_changes_log.csv"
        new = not log.exists()
        with open(log, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, ["detected", "legal_id", "company", "kind", "page", "text", "href"], extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(changes)
    print(f"[merge] jobs={len(jobs)} docs={len(index)} site_changes={len(changes)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
