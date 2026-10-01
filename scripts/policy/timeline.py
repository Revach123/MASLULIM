"""ציר זמן לכל מסלול: הנתונים האחרונים + תאריך השינוי האחרון + סיווג השינוי (גדול / קטן).

הרצה: python -m scripts.policy.timeline   (נקרא גם מ-combine)
קלט: כל ההיסטוריה ב-policy/companies/<LegalId>/tracks_policy_long.json (כל גרסה = מסמך).
פלט:
  policy/tracks_latest.json/.csv   - שורה לכל (מסלול, אפיק) מהגרסה האחרונה, עם תאריך השינוי האחרון וסוגו
                                     active = המסלול מופיע בשנה האחרונה של החברה (אחרת: מסלול שנסגר/מוזג)
  policy/tracks_summary.csv        - שורה לכל מסלול: תאריך תוקף, שינוי אחרון, שינוי גדול אחרון, תקציר
  policy/track_changes.csv/.json   - יומן כל השינויים בין גרסאות עוקבות של כל מסלול

תאריך גרסה (date_source): תאריך בשם הקובץ / טקסט הקישור (doc) -> תאריך עדכון בקובץ עצמו (file_meta)
-> 1 בינואר של שנת המדיניות (year_start) -> המועד שבו המסמך נמצא לראשונה (first_seen).

סיווג שינוי בין גרסה לקודמתה:
  major - אפיק משמעותי (10%+) נוסף/הוסר, שינוי >= MAJOR_PP (10) נק' אחוז בחשיפה הצפויה או בגבולות, החלפת מדד ייחוס
          (מדדים אחרים), או שינוי משקל >= BENCH_PP (10) בהרכב המדד
  minor - שינוי קטן יותר: אחוזים בודדים בחשיפה/בגבולות או בהרכב מדד הייחוס
  שינויים מתחת ל-NOISE_PP (עיגול) לא נחשבים שינוי.
"""
import csv, json, re, zipfile
from datetime import date
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
POL = ROOT / "policy"
COMP = POL / "companies"

MAJOR_PP = 10.0    # נק' אחוז: מכאן והלאה שינוי בחשיפה/בגבולות הוא "גדול" (אחוזים בודדים = קטן)
BENCH_PP = 10.0    # שינוי משקל במדד ייחוס (אותם מדדים) מתחת לזה = קטן
NOISE_PP = 0.5     # הפרשי עיגול

FIELDS = ["legal_id", "company", "track_no", "track_no_source", "track_code", "track_name", "year", "asset", "asset_key",
          "expected_pct", "min_pct", "max_pct", "benchmark",
          "effective_date", "date_source", "last_change_date", "last_change_level", "last_major_change_date",
          "asset_change", "prev_expected_pct", "prev_min_pct", "prev_max_pct", "prev_benchmark", "prev_effective_date",
          "versions", "active", "url"]
SUMMARY_FIELDS = ["legal_id", "company", "track_no", "track_no_source", "track_code", "track_name", "year", "effective_date", "date_source",
                  "last_change_date", "last_change_level", "last_major_change_date", "last_change_summary", "prev_effective_date", "prev_url", "versions", "active", "url"]
CHANGE_FIELDS = ["legal_id", "company", "track_no", "track_no_source", "track_code", "track_name", "date", "prev_date", "level", "summary", "url", "prev_url"]


def _natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s or "")]


def _mk(y, m, d):
    y = int(y); y = y + 2000 if y < 100 else y
    try:
        return date(y, int(m), int(d))
    except ValueError:
        return None


def date_from_text(s: str, year=None):
    """תאריך מפורש בשם קובץ / טקסט קישור. year (שנת המדיניות) מסנן תאריכים לא סבירים."""
    s = unquote(s or "")
    cands = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})[./_-](\d{1,2})[./_-](20\d\d|\d\d)(?!\d)", s):      # 06-05-2026, 27.8.20
        cands.append(_mk(m.group(3), m.group(2), m.group(1)))
    for m in re.finditer(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)", s):                              # _20250101
        cands.append(_mk(m.group(1), m.group(2), m.group(3)))
    for m in re.finditer(r"(?<!\d)(\d\d)(\d\d)(20\d\d)(?!\d)", s):                              # 10032024
        cands.append(_mk(m.group(3), m.group(2), m.group(1)))
    for m in re.finditer(r"(?<=[_\-])(\d\d)(\d\d)(\d\d)(?=[_\-.]|$)", s):                   # _260811 (YYMMDD) / _101225 (DDMMYY)
        cands += [_mk(m.group(1), m.group(2), m.group(3)), _mk(m.group(3), m.group(2), m.group(1))]
    for m in re.finditer(r"(?<=[_\-])(\d\d)(\d)(\d\d)(?=[_\-.]|$)", s):                        # -26826 (D D M YY, הכשרה)
        cands.append(_mk(m.group(3), m.group(2), m.group(1)))
    for m in re.finditer(r"update[-_]?(\d\d)(20\d\d|\d\d)(?!\d)", s, re.I):                     # update052026 / update0526
        cands.append(_mk(m.group(2), m.group(1), 1))
    cands = [c for c in cands if c and date(2010, 1, 1) <= c <= date.today()]
    if year and str(year).isdigit():
        y = int(year)
        cands = [c for c in cands if y - 1 <= c.year <= y]   # הצהרה לשנה Y מתפרסמת ב-Y-1 (סוף שנה) או במהלך Y
    return max(cands) if cands else None


def date_from_file(path: Path, year=None):
    """תאריך עדכון מתוך מטא-דאטה של הקובץ (xlsx: docProps/core.xml; PDF: ModDate)."""
    try:
        d = None
        if path.suffix.lower() in (".xlsx", ".xlsm", ".docx"):
            with zipfile.ZipFile(path) as z:
                x = z.read("docProps/core.xml").decode("utf-8", "ignore")
            m = re.search(r"<dcterms:modified[^>]*>(\d{4})-(\d\d)-(\d\d)", x) or re.search(r"<dcterms:created[^>]*>(\d{4})-(\d\d)-(\d\d)", x)
            d = _mk(*m.groups()) if m else None
        elif path.suffix.lower() == ".pdf":
            head = path.read_bytes()[-200000:]
            m = re.search(rb"/ModDate\s*\(D:(\d{4})(\d\d)(\d\d)", head) or re.search(rb"/CreationDate\s*\(D:(\d{4})(\d\d)(\d\d)", head)
            d = _mk(*(g.decode() for g in m.groups())) if m else None
        if d and year and str(year).isdigit() and not (int(year) - 1 <= d.year <= int(year)):
            return None  # קובץ שנשמר מחדש שנים אחר כך - לא מעיד על מועד הפרסום
        return d
    except Exception:
        return None


def version_date(url, ent, year):
    d = date_from_text(url, year) or date_from_text(ent.get("link_text"), year)
    if d:
        return d.isoformat(), "doc"
    f = ROOT / ent["file"] if ent.get("file") else None
    d = date_from_file(f, year) if f and f.exists() else None
    if d:
        return d.isoformat(), "file_meta"
    if year and str(year).isdigit():
        return f"{year}-01-01", "year_start"
    return (ent.get("first_seen") or "")[:10], "first_seen"


def _num(x):
    """ערך באחוזים; מעל 400 = שגיאת פרסור (9900 במקום 99) - מתעלמים כדי לא לייצר "שינוי" מדומה."""
    try:
        v = None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None
    return None if v is not None and abs(v) > 400 else v


def track_key(r):
    """זהות מסלול לאורך שנים: מספר קופה/מסלול + שם מנורמל (בלי שנים, סימני פיסוק, "מסלול").
    track_code משתנה בין שנים (שם גיליון/קבוצה), ולכן לא משמש לבדו."""
    fid = r.get("fund_id") or r.get("track_no")
    n = r.get("track_name") or r.get("track_code") or ""
    n = re.sub(r"(19|20)\d\d", " ", n)
    n = re.sub(r"[\"'״׳()\[\]\-–_,.:/]+", " ", n)
    n = re.sub(r"\b(מסלול|לשנת|שנת|מעודכן|עדכון)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    # מספר מסלול לבדו לא מספיק: מיטב מחזרת מספרים (874 = "לבני 50 ומטה" ב-2018, "עוקב מדדי אג"ח" ב-2025)
    return f"#{fid}|{n}" if fid and str(fid).isdigit() else n


GENERIC = re.compile(r"^(page\s*\d+|גיליון\s*\d*|sheet\s*\d*|\d{1,2}|כללי)$", re.I)


def _dist(a: dict, b: dict):
    """מרחק בין שתי גרסאות של מסלול (לשיוך מסלולים בלי שם): סכום הפרשי החשיפה הצפויה/הגבולות + קנס על אפיקים שונים."""
    keys = set(a) | set(b)
    d = 0.0
    for k in keys:
        if k not in a or k not in b:
            d += 15; continue
        for f in ("expected_pct", "min_pct", "max_pct"):
            x, y = _num(a[k].get(f)), _num(b[k].get(f))
            if x is not None and y is not None:
                d += abs(x - y) / 3
    return d


def chain_generic(versions_by_url: dict):
    """מסלולים בשם כללי (page1/גיליון1 - PDF בלי כותרת מסלול): השם לא יציב בין קבצים, לכן כל מסלול בגרסה
    משויך לשרשרת שהגרסה האחרונה שלה הכי דומה לו (חמדני). -> {chain_id: {url: version}}"""
    urls = sorted(versions_by_url, key=lambda u: (versions_by_url[u][0]["date"][0], str(versions_by_url[u][0]["year"] or ""), _natural(u)))
    chains = []  # [{"last": rows, "vers": {url: version}}]
    for u in urls:
        free = list(range(len(chains)))
        for v in versions_by_url[u]:
            best = min(((i, _dist(chains[i]["last"], v["rows"])) for i in free), key=lambda t: t[1], default=(None, 1e9))
            if best[0] is not None and best[1] <= 40:
                ch = chains[best[0]]; free.remove(best[0])
            else:
                ch = {"vers": {}}; chains.append(ch)
            ch["last"] = v["rows"]; ch["vers"][u + "#" + v["name"]] = v
    return {i: ch["vers"] for i, ch in enumerate(chains)}


def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


NON_ASSET = re.compile(r"עמל|דמי ניהול|תשואה|סה\"?כ|total", re.I)  # שורות שאינן אפיק (מגבלת עמלת ניהול חיצוני, סה"כ)


def _akey(r):
    """מפתח אפיק יציב בין שנים: asset_key סטנדרטי, אחרת השם בלי שנים/מספרי הערות שוליים/פיסוק."""
    if r.get("asset_key"):
        return r["asset_key"]
    n = re.sub(r"(19|20)\d\d", "", r.get("asset") or "")
    n = re.sub(r"\d+\*?$|\*+", "", n.strip())  # "אג"ח ממשלתי3" / "פקמ**" - הפניות להערות
    return re.sub(r"[\s\"'״׳()\-–,.]+", "", n)


def _bench_parts(b):
    b = re.sub(r"\s+", " ", (b or "").strip())
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?(?=\s*%)", b)]
    names = re.sub(r"\d+(?:\.\d+)?\s*%|[\s\-–,+/()%]+", " ", b)
    names = " ".join(sorted(set(names.lower().split())))
    return names, nums


def compare(prev: dict, cur: dict):
    """prev/cur: {asset_key: row}. -> (level|None, [תיאורים], {asset_key: 'major'|'minor'|'new'})."""
    level, notes, per = None, [], {}

    def bump(lv):
        nonlocal level
        level = "major" if "major" in (level, lv) else lv

    for k in sorted(set(prev) | set(cur)):
        a, b = prev.get(k), cur.get(k)
        name = _clean((b or a).get("asset")) or k
        if a is None or b is None:
            vals = [_num((b or a).get(f)) for f in ("expected_pct", "min_pct", "max_pct")]
            if any(v for v in vals):  # אפיק עם 0 בכל העמודות נוסף/הוסר - לא שינוי מהותי
                # אפיק קטן (צפוי ומקס' מתחת ל-MAJOR_PP, למשל "אחר" 0-2%) = שינוי קטן
                bump("major" if max(v or 0 for v in vals) >= MAJOR_PP else "minor"); per[k] = "new" if a is None else "removed"
                notes.append(f"{name}: {'נוסף' if a is None else 'הוסר'}")
            continue
        lv = None
        for f, lbl in (("expected_pct", "צפוי"), ("min_pct", "מינ'"), ("max_pct", "מקס'")):
            x, y = _num(a.get(f)), _num(b.get(f))
            if x is None and y is None:
                continue
            if x is None or y is None:  # ערך שחסר בגרסה אחת (פרסור/עמודה ריקה) - לא שינוי מדיניות
                continue
            dlt = abs(y - x)
            if dlt >= NOISE_PP:
                lv = "major" if dlt >= MAJOR_PP or lv == "major" else "minor"
                notes.append(f"{name} {lbl}: {x:g}→{y:g}")
        na, nb = _bench_parts(a.get("benchmark")), _bench_parts(b.get("benchmark"))
        if (a.get("benchmark") or "") != (b.get("benchmark") or "") and na[0] and nb[0]:  # מדד חסר בצד אחד - לא שינוי
            if na[0] != nb[0]:
                lv = "major"; notes.append(f"{name} מדד ייחוס: '{(a.get('benchmark') or '')[:60]}' → '{(b.get('benchmark') or '')[:60]}'")
            elif na[1] != nb[1]:
                d = max((abs(p - q) for p, q in zip(sorted(na[1]), sorted(nb[1]))), default=0)
                if d >= NOISE_PP or len(na[1]) != len(nb[1]):
                    lv = "major" if (d >= BENCH_PP or lv == "major") else (lv or "minor")
                    notes.append(f"{name} משקלי מדד: {'/'.join(f'{v:g}' for v in na[1])} → {'/'.join(f'{v:g}' for v in nb[1])}")
        if lv:
            per[k] = lv; bump(lv)
    return level, notes, per


def build():
    names = {}
    for r in csv.DictReader(open(POL / "crawl_report.csv", encoding="utf-8-sig")) if (POL / "crawl_report.csv").exists() else []:
        names[r["legal_id"]] = r["company"]
    tracks = {}  # (lid, track_code) -> {url: {"rows": {akey: row}, ...}}
    for d in sorted(p for p in COMP.iterdir() if p.is_dir()) if COMP.exists() else []:
        idx = json.loads((d / "docs_index.json").read_text("utf-8")) if (d / "docs_index.json").exists() else {}
        rows = json.loads((d / "tracks_policy_long.json").read_text("utf-8")) if (d / "tracks_policy_long.json").exists() else []
        dcache = {}
        generic = {}  # url -> {name: version} - מסלולים בשם כללי, משויכים בהמשך לפי תוכן
        for r in rows:
            if GENERIC.match((r.get("track_name") or "").strip()):
                url = r.get("url")
                if (url, r.get("year")) not in dcache:
                    dcache[(url, r.get("year"))] = version_date(url, idx.get(url, {}), r.get("year"))
                v = generic.setdefault(url, {}).setdefault(r.get("track_name"), {"rows": {}, "year": r.get("year"), "url": url,
                                                                                 "name": r.get("track_name"), "date": dcache[(url, r.get("year"))]})
                if not NON_ASSET.search(r.get("asset") or ""):
                    v["rows"].setdefault(_akey(r), r)
                continue
            key = (r.get("legal_id"), track_key(r))
            url = r.get("url")
            if (url, r.get("year")) not in dcache:
                dcache[(url, r.get("year"))] = version_date(url, idx.get(url, {}), r.get("year"))
            v = tracks.setdefault(key, {}).setdefault(url, {"rows": {}, "year": r.get("year"), "url": url,
                                                             "date": dcache[(url, r.get("year"))]})
            if not NON_ASSET.search(r.get("asset") or ""):
                v["rows"].setdefault(_akey(r), r)
        if generic:
            for cid, vers in chain_generic({u: list(g.values()) for u, g in generic.items()}).items():
                tracks[(d.name, f"~generic{cid}")] = vers
    latest, summary, log = [], [], []
    max_year = {}
    for (lid, _), versions in tracks.items():
        for v in versions.values():
            if str(v["year"] or "").isdigit():
                max_year[lid] = max(max_year.get(lid, 0), int(v["year"]))
    for (lid, tkey), versions in tracks.items():
        vs = sorted(versions.values(), key=lambda v: (v["date"][0], str(v["year"] or ""), _natural(v["url"])))
        last_change = (vs[0]["date"], "initial", [], {}, None)  # (date, level, notes, per-asset, הגרסה שלפני השינוי)
        last_major = vs[0]["date"][0]
        prev = vs[0]
        for v in vs[1:]:
            lv, notes, per = compare(prev["rows"], v["rows"])
            if lv:
                last_change = (v["date"], lv, notes, per, prev)
                if lv == "major":
                    last_major = v["date"][0]
                any_row = next(iter(v["rows"].values()))
                log.append({"legal_id": lid, "company": names.get(lid, ""), "track_code": any_row.get("track_code"),
                            "track_name": any_row.get("track_name"), "date": v["date"][0], "prev_date": prev["date"][0],
                            "level": lv, "summary": "; ".join(notes)[:1000], "url": v["url"], "prev_url": prev["url"]})
            prev = v
        cur = vs[-1]
        tcode = next(iter(cur["rows"].values())).get("track_code")
        active = str(cur["year"] or "").isdigit() and int(cur["year"]) >= max_year.get(lid, 0)
        (cdate, csrc), clevel, cnotes, cper, before = last_change
        any_row = next(iter(cur["rows"].values()))
        summary.append({"legal_id": lid, "company": names.get(lid, ""), "track_code": tcode, "track_name": any_row.get("track_name"),
                        "year": cur["year"], "effective_date": cur["date"][0], "date_source": cur["date"][1],
                        "last_change_date": cdate, "last_change_level": clevel, "last_major_change_date": last_major,
                        "last_change_summary": "; ".join(cnotes)[:500],
                        "prev_effective_date": before["date"][0] if before else "", "prev_url": before["url"] if before else "", "versions": len(vs), "active": active, "url": cur["url"]})
        for k, r in cur["rows"].items():
            latest.append({"legal_id": lid, "company": names.get(lid, ""), "track_code": tcode, "track_name": _clean(r.get("track_name")),
                           "year": cur["year"], "asset": _clean(r.get("asset")), "asset_key": r.get("asset_key"),
                           "expected_pct": r.get("expected_pct"), "min_pct": r.get("min_pct"), "max_pct": r.get("max_pct"),
                           "benchmark": _clean(r.get("benchmark")), "effective_date": cur["date"][0], "date_source": cur["date"][1],
                           "last_change_date": cdate, "last_change_level": clevel, "last_major_change_date": last_major,
                           "asset_change": cper.get(k, ""),
                           # המדיניות שהייתה בתוקף לפני השינוי האחרון (ריק אם אין שינוי / האפיק חדש)
                           "prev_expected_pct": (before["rows"].get(k) or {}).get("expected_pct") if before else None,
                           "prev_min_pct": (before["rows"].get(k) or {}).get("min_pct") if before else None,
                           "prev_max_pct": (before["rows"].get(k) or {}).get("max_pct") if before else None,
                           "prev_benchmark": _clean((before["rows"].get(k) or {}).get("benchmark")) if before else None,
                           "prev_effective_date": before["date"][0] if before else "", "versions": len(vs), "active": active, "url": cur["url"]})
    # מספר מסלול לכל מסלול - מהקבצים עצמם (track_numbers.py); התאמת שם רק כמוצא אחרון ומסומנת
    from .track_numbers import assign
    url_tracks = {}
    for (lid, tkey), versions in tracks.items():
        for v in versions.values():
            url_tracks.setdefault(v["url"], set()).add(tkey)
    meta = []
    for s_, (key, versions) in zip(summary, tracks.items()):
        cur = max(versions.values(), key=lambda v: (v["date"][0], str(v["year"] or ""), _natural(v["url"])))
        r0 = next(iter(cur["rows"].values()))
        fids = [x for r in cur["rows"].values() for x in (r.get("fund_id"), r.get("track_no")) if x]
        meta.append({"legal_id": key[0], "track_name": r0.get("track_name"), "track_code": r0.get("track_code"),
                     "sheet": r0.get("sheet"), "url": cur["url"], "doc_file": r0.get("doc_file"), "fund_ids": fids,
                     "single_track_file": len(url_tracks.get(cur["url"], ())) == 1, "active": s_["active"], "_s": s_})
    assign(meta)
    by_key = {}
    for m in meta:
        m["_s"]["track_no"], m["_s"]["track_no_source"] = m["track_no"], m["track_no_source"]
        by_key[(m["_s"]["legal_id"], m["_s"]["url"], m["_s"]["track_code"])] = m
    for r in latest:
        m = by_key.get((r["legal_id"], r["url"], r["track_code"]))
        r["track_no"], r["track_no_source"] = (m["track_no"], m["track_no_source"]) if m else ("", "")
    # אותם קבצים באתר של שתי חברות (מגדל ביטוח מציג את קבצי מגדל מקפת): מסלול שהמספר שלו שייך ברישום לחברה אחרת,
    # שגם אצלה המסלול קיים - נשאר רק אצל הבעלים
    from .track_numbers import Registry
    reg = Registry()
    owner = {tn: lid for lid, d in reg.by_company.items() for tn in d}
    have = {(s_["legal_id"], s_["track_no"]) for s_ in summary if s_.get("track_no")}
    dup = {(s_["legal_id"], s_["track_code"], s_["url"]) for s_ in summary if s_.get("track_no")
           and s_["track_no"] not in reg.by_company.get(s_["legal_id"], {}) and owner.get(s_["track_no"]) not in (None, s_["legal_id"])
           and (owner[s_["track_no"]], s_["track_no"]) in have}
    if dup:
        drop_names = {(s_["legal_id"], s_["track_name"]) for s_ in summary if (s_["legal_id"], s_["track_code"], s_["url"]) in dup}
        summary = [s_ for s_ in summary if (s_["legal_id"], s_["track_code"], s_["url"]) not in dup]
        latest = [r for r in latest if (r["legal_id"], r["track_code"], r["url"]) not in dup]
        log = [r for r in log if (r.get("legal_id"), r.get("track_name")) not in drop_names]
    return latest, summary, log


def _write(name, fields, rows):
    with open(POL / name, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def write_complete(latest):
    """policy/extension_complete.json - חברות שיש להן מדיניות של השנה הנוכחית לכל המסלולים, כדי שהתוסף ידלג
    עליהן (skip_complete_hours בכללים, ברירת מחדל 24 שעות). מלא = כל מסלולי הרישום הרשמי (data.gov) של החברה
    מכוסים במדיניות השנה; חברה שאינה ברישום (קרן ותיקה) - כל המסלולים הפעילים שלה עם מדיניות השנה."""
    year = str(date.today().year)
    reg = {}
    rp = POL / "fund_registry.csv"
    if rp.exists():
        for r in csv.DictReader(open(rp, encoding="utf-8-sig")):
            if r.get("legal_id") and r.get("track_no"):
                reg.setdefault(r["legal_id"], set()).add(r["track_no"])
    have, act, act_y = {}, {}, {}
    for r in latest:
        if not r.get("active"):
            continue
        lid = r["legal_id"]
        k = (r.get("track_code"), r.get("track_name"))
        act.setdefault(lid, set()).add(k)
        if str(r.get("year") or "") >= year:
            act_y.setdefault(lid, set()).add(k)
            if r.get("track_no"):
                have.setdefault(lid, set()).add(r["track_no"])
    out = {}
    for lid in set(act) | set(reg):
        R, H = reg.get(lid, set()), have.get(lid, set())
        if R:
            ok, why = R <= H, f"registry {len(R & H)}/{len(R)}"
        else:
            ok = bool(act_y.get(lid)) and len(act_y[lid]) == len(act.get(lid, ()))
            why = f"tracks {len(act_y.get(lid, ()))}/{len(act.get(lid, ()))} (not in registry)"
        out[lid] = {"complete": ok, "why": why, "missing": sorted(R - H)[:50] if R else []}
    (POL / "extension_complete.json").write_text(json.dumps(
        {"year": year, "generated": date.today().isoformat(), "companies": out}, ensure_ascii=False, indent=1), "utf-8")


def main():
    latest, summary, log = build()
    latest.sort(key=lambda r: (r["legal_id"], r["track_name"] or "", r["asset"] or ""))
    summary.sort(key=lambda r: (r["legal_id"], r["track_name"] or ""))
    log.sort(key=lambda r: (r["date"], r["legal_id"], r["track_name"] or ""), reverse=True)
    (POL / "tracks_latest.json").write_text(
        "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in latest) + "\n]\n", "utf-8")
    (POL / "track_changes.json").write_text(
        "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in log) + "\n]\n", "utf-8")
    _write("tracks_latest.csv", FIELDS, latest)
    _write("tracks_summary.csv", SUMMARY_FIELDS, summary)
    _write("track_changes.csv", CHANGE_FIELDS, log)
    write_complete(latest)
    lv = {}
    for s in summary:
        lv[s["last_change_level"]] = lv.get(s["last_change_level"], 0) + 1
    print(f"[timeline] tracks={len(summary)} rows={len(latest)} changes={len(log)} last-change levels={lv}")


if __name__ == "__main__":
    main()
