"""חילוץ טווחי מדיניות לכל מסלול ממסמכים שנמשכו (policy/docs_index.json).

הרצה: python -m scripts.policy.extract [--all]   (ברירת מחדל: רק מסמכים שלא נותחו)
פלט: policy/tracks_policy.csv + .json - שורה לכל (חברה, מסמך, מסלול).

היוריסטיקה על עברית חופשית: מזהה כותרת מסלול ("מסלול ..."), ובחלון הטקסט עד
הכותרת הבאה מחלץ טווחי חשיפה (מינ'-מקס') לפי אפיק. כל שורה נושאת snippet מקור
וציון ביטחון - חובה לעבור ידנית על מסמכים ראשונים כי פורמט משתנה בין חברות.
"""
import argparse, csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "policy"

NUM = r"(\d{1,3}(?:\.\d+)?)"
PCT = NUM + r"\s*%?"
# אפיק -> ביטוי זיהוי בטקסט
ASSETS = {
    "equity": r"(?:חשיפה\s+ל)?מניות",
    "bonds": r"(?:איגרות|אגרות)\s+חוב|אג[\"״']?ח",
    "foreign": r"חו[\"״]ל|חוץ\s+לארץ|נכסים\s+זרים",
    "fx": r"מט[\"״]ח|מטבע\s+חוץ",
    "illiquid": r"לא\s+סחיר|בלתי\s+סחיר",
}
TRACK_HDR = re.compile(r"^\s*(?:\d+[.)]\s*)?((?:מסלול|קרן\s+השתלמות|קופת\s+גמל|קרן\s+פנסיה)[^\n:]{3,80})$")


def parse_range(s: str):
    """'10%-25%' / '10 עד 25' / 'עד 30%' / 'לפחות 50%' -> (min, max) (None = לא צוין)."""
    m = re.search(PCT + r"\s*(?:-|–|—|עד|ל-?)\s*" + PCT, s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = re.search(r"(?:עד|מקסימום|לכל\s+היותר|לא\s+יעלה\s+על)\s*" + PCT, s)
    if m:
        return (None, float(m.group(1)))
    m = re.search(r"(?:לפחות|מינימום|לא\s+פחות\s+מ)\s*" + PCT, s)
    if m:
        return (float(m.group(1)), None)
    m = re.search(PCT, s)
    return (float(m.group(1)),) * 2 if m and "%" in s else (None, None)


def norm_name(s: str) -> str:
    s = re.sub(r"[\"'״׳\-–—()\[\]:.,]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_tracks_from_text(text: str) -> list[dict]:
    lines = [l.rstrip() for l in text.splitlines()]
    hdrs = [(i, norm_name(m.group(1))) for i, l in enumerate(lines) if (m := TRACK_HDR.match(l))]
    out = []
    for n, (i, name) in enumerate(hdrs):
        end = hdrs[n + 1][0] if n + 1 < len(hdrs) else len(lines)
        block = lines[i + 1:end][:60]
        rec = {"track_name": name, "snippet": " ".join(block)[:400], "confidence": "text"}
        for k, pat in ASSETS.items():
            for l in block:
                if re.search(pat, l) and re.search(r"\d\s*%|%\s*\d|\d+\s*(?:-|–|עד)\s*\d+", l):
                    lo, hi = parse_range(re.split(pat, l, maxsplit=1)[-1])
                    if lo is not None or hi is not None:
                        rec[f"{k}_min"], rec[f"{k}_max"] = lo, hi
                        break
        for l in block:
            if re.search(r"מדד\s+ה?ייחוס|בנצ[׳']?מרק|benchmark", l, re.I):
                rec["benchmark"] = l.strip()[:200]; break
        if any(f"{k}_{b}" in rec for k in ASSETS for b in ("min", "max")):
            out.append(rec)
    return out


def extract_tracks_from_table(rows: list[list[str]]) -> list[dict]:
    """טבלה: שורת כותרת עם שמות אפיקים, שורה לכל מסלול (או להפך - לא נתמך עדיין)."""
    out, hdr = [], None
    for r in rows:
        cells = [(c or "").replace("\n", " ").strip() for c in r]
        if hdr is None:
            cols = {}
            for j, c in enumerate(cells):
                for k, pat in ASSETS.items():
                    if re.search(pat, c):
                        cols.setdefault(k, j)
            if len(cols) >= 2:
                hdr = cols
            continue
        if not cells or not cells[0] and len(cells) < 2:
            continue
        name = next((c for c in cells if c and not re.search(r"\d\s*%", c)), "")
        if not name:
            continue
        rec = {"track_name": norm_name(name), "snippet": " | ".join(cells)[:400], "confidence": "table"}
        for k, j in hdr.items():
            if j < len(cells) and cells[j]:
                lo, hi = parse_range(cells[j] if "%" in cells[j] else cells[j] + "%")
                if lo is not None or hi is not None:
                    rec[f"{k}_min"], rec[f"{k}_max"] = lo, hi
        if any(f"{k}_{b}" in rec for k in ASSETS for b in ("min", "max")):
            out.append(rec)
    return out


def read_doc(path: Path):
    """-> (text, tables[list[rows]], names[list[str]]) - names = שמות גיליונות (ריק ל-PDF/DOCX)"""
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pdfplumber
        texts, tables = [], []
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages:
                texts.append(pg.extract_text() or "")
                tables += pg.extract_tables()
        return "\n".join(texts), tables, []
    if ext == ".xls":
        import xlrd
        wb = xlrd.open_workbook(path)
        tables = [[[str(c) if c != "" else "" for c in sh.row_values(i)] for i in range(sh.nrows)]
                  for sh in wb.sheets()]
        return "\n".join(" ".join(c for c in r if c) for t in tables for r in t), tables, [sh.name for sh in wb.sheets()]
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        tables = [[[str(c) if c is not None else "" for c in row] for row in ws.iter_rows(values_only=True)]
                  for ws in wb.worksheets]
        return "\n".join(" ".join(c for c in r if c) for t in tables for r in t), tables, [ws.title for ws in wb.worksheets]
    if ext == ".docx":
        import docx
        d = docx.Document(path)
        tables = [[[c.text for c in row.cells] for row in t.rows] for t in d.tables]
        return "\n".join(p.text for p in d.paragraphs), tables, []
    return "", [], []  # .doc/.xls ישנים: לא נתמך - מדווח כ-unsupported


# ---------- פרסרים לפי מבנה (מזוהים לפי תוכן הגיליון, לא לפי חברה) ----------
BOUNDS = re.compile(r"(-?\d+(?:\.\d+)?)\s*%?\s*-\s*(-?\d+(?:\.\d+)?)\s*%")
ASSET_MAP = {"מניות": "equity", "מטח": "fx", "מט\"ח": "fx"}  # יתר האפיקים נשמרים בשמם המקורי


def _num(v):
    try:
        return float(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_statement_blocks(rows, sheet=""):
    """מבנה "הצהרת השקעות": בלוקים של [קידוד מסלול | שם המסלול | כותרת | שורה לאפיק | סוף טבלה].
    -> רשימת רשומות long (שורה לכל מסלול x אפיק). [] אם המבנה לא מתאים."""
    if not any(str(r[0]).strip() == "קידוד מסלול" for r in rows if r and r[0] is not None):
        return []
    year = next((m.group(1) for r in rows[:3] for c in r if c and (m := re.search(r"(20\d\d)", str(c)))), None)
    out, cur, hdr = [], None, None
    for r in rows:
        r = list(r) + [None] * 7
        k = str(r[0]).strip() if r[0] is not None else ""
        if k == "קידוד מסלול":
            code = str(r[1]).strip()
            parts = code.split("-")
            cur = {"track_code": code, "legal_id": parts[0],
                   "fund_id": str(int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else None,
                   "track_no": parts[2] if len(parts) > 2 else None, "track_name": None, "year": year}
            hdr = None
        elif cur and k == "שם המסלול":
            cur["track_name"] = norm_name(str(r[1] or ""))
        elif cur and k == "אפיק":
            hdr = True
        elif cur and hdr and k and k not in ("סוף טבלה", "סה\"כ") and not k.startswith("*"):
            m = BOUNDS.search(str(r[4] or ""))
            cur_pct, exp = _num(r[1]), _num(r[2])
            if m is None and exp is None and cur_pct is None:
                continue
            out.append({**cur, "asset": k.rstrip("*").strip(), "asset_key": ASSET_MAP.get(k.rstrip("*").strip()),
                        "current_pct": None if cur_pct is None else round(cur_pct * 100, 2),
                        "expected_pct": None if exp is None else round(exp * 100, 2),
                        "tolerance": r[3], "min_pct": float(m.group(1)) if m else None,
                        "max_pct": float(m.group(2)) if m else None,
                        "benchmark": (str(r[5]).replace("\n", " ") if r[5] else None), "sheet": sheet})
    return out


def parse_change_log(rows, sheet=""):
    """גיליון "מהות שינויים": מספר מסלול | שם מסלול | מהות השינוי | תאריך עדכון."""
    if not rows or [str(c).strip() for c in rows[0][:4]] != ["מספר מסלול", "שם מסלול", "מהות השינוי", "תאריך עדכון"]:
        return []
    return [{"track_code": str(r[0]), "track_name": r[1], "change": str(r[2] or "").replace("\n", " "),
             "updated": str(r[3])[:10]} for r in rows[1:] if r and r[0]]


LONG_FIELDS = ["legal_id", "fund_id", "track_no", "track_code", "track_name", "year", "asset", "asset_key",
               "current_pct", "expected_pct", "tolerance", "min_pct", "max_pct", "benchmark", "url", "doc_file", "sheet"]
CHANGE_FIELDS = ["legal_id", "track_code", "track_name", "change", "updated", "url"]


def dump_layout(names, tables, ent, url):
    """מבנה שאף פרסר לא זיהה: שומרים תחילת כל גיליון כדי שנוסיף פרסר אחרי שנראה אותו."""
    return {"url": url, "legal_id": ent["legal_id"], "file": ent["file"],
            "sheets": [{"name": n, "head": [[str(c)[:60] for c in r if c not in (None, "")] for r in t[:15]]}
                       for n, t in zip(names or [""] * len(tables), tables)]}


FIELDS = ["legal_id", "url", "doc_file", "track_name", "confidence",
          *[f"{k}_{b}" for k in ASSETS for b in ("min", "max")], "benchmark", "snippet"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    idx_path = OUT / "docs_index.json"
    index = json.loads(idx_path.read_text("utf-8"))
    rows_path = OUT / "tracks_policy.json"
    keep = not a.all and rows_path.exists()
    rows = {r["url"] + "|" + r["track_name"]: r for r in json.loads(rows_path.read_text("utf-8"))} if keep else {}
    long_path, chg_path, unp_path = (OUT / "tracks_policy_long.json", OUT / "policy_changes.json",
                                     OUT / "unparsed_layouts.json")
    _load = lambda p: json.loads(p.read_text("utf-8")) if keep and p.exists() else []
    long_rows, changes, unparsed = _load(long_path), _load(chg_path), _load(unp_path)
    for url, ent in index.items():
        if not a.all and ent.get("parsed_sha") == ent["sha256"]:
            continue
        # החלפת תוצאות קודמות של אותו url (מסמך שהתעדכן)
        long_rows = [r for r in long_rows if r["url"] != url]
        changes = [r for r in changes if r["url"] != url]
        unparsed = [r for r in unparsed if r["url"] != url]
        p = ROOT / ent["file"]
        try:
            text, tables, names = read_doc(p)
        except Exception as ex:
            print(f"[extract] {p.name}: {ex!r}", file=sys.stderr); continue
        names = names or [""] * len(tables)
        n_long, leftovers = 0, []
        for nm, t in zip(names, tables):
            found = parse_statement_blocks(t, nm)
            if found:
                for r in found:
                    r.update(url=url, doc_file=ent["file"])
                long_rows += found; n_long += len(found); continue
            chg = parse_change_log(t, nm)
            if chg:
                for r in chg:
                    r.update(legal_id=ent["legal_id"], url=url)
                changes += chg; continue
            leftovers.append((nm, t))
        recs = [] if n_long else extract_tracks_from_text(text)
        for nm, t in leftovers:
            recs += extract_tracks_from_table(t)
        for r in recs:
            r.update(legal_id=ent["legal_id"], url=url, doc_file=ent["file"])
            rows[url + "|" + r["track_name"]] = r
        if not n_long and not recs:
            unparsed.append(dump_layout(names, tables, ent, url))
        ent["parsed_sha"] = ent["sha256"]
        print(f"[extract] {p.name}: long={n_long} heuristic={len(recs)}", flush=True)
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    out = sorted(rows.values(), key=lambda r: (r["legal_id"], r["track_name"]))
    rows_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for path, data in ((long_path, long_rows), (chg_path, changes), (unp_path, unparsed)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    for name, data, fields in (("tracks_policy", out, FIELDS), ("tracks_policy_long", long_rows, LONG_FIELDS),
                               ("policy_changes", changes, CHANGE_FIELDS)):
        with open(OUT / f"{name}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fields, extrasaction="ignore")
            w.writeheader(); w.writerows(data)
    print(f"[extract] long={len(long_rows)} changes={len(changes)} unparsed_docs={len(unparsed)}")


if __name__ == "__main__":
    main()
