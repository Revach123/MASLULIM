"""פרסור דוחות מרכיבי התשואה של חברה ובניית סדרה לכל מסלול.

הרצה: python -m scripts.returns.extract --only <LegalId> [--all]
קלט: returns/companies/<id>/docs_index.json + raw/. פלט באותה תיקייה:
  parsed/<sha12>.json  - תוצאת הפרסור לכל קובץ (מטמון: קובץ שלא השתנה ולא השתנה הפרסר לא מפורסר שוב)
  tracks.json          - לכל מסלול: מספר (ומקורו), שם, ולכל חודש התרומה והמשקל של כל אפיק + הדוח שממנו נלקח
  nostro.json          - נוסטרו של חברות ביטוח (רבעוני, באלפי ש"ח)
כללים:
  - מה שכתוב בקובץ קובע: החודש והשנה מכותרות העמודות / "שנת דיווח"; לא תאריך הפרסום.
  - כל דוח רבעוני חוזר על כל חודשי השנה עד אליו: לכל (מסלול, חודש) נבחר הדוח העדכני ביותר (מכסה הכי הרבה חודשים
    באותה שנה, אחרת שנאסף אחרון). ערך שהשתנה בין דוחות נרשם ב-revisions.
  - מספר מסלול: מהקובץ (תווית/כותרת/שם גיליון/שם קובץ) ונבדק מול הרישום הרשמי (policy/fund_registry.csv,
    policy/fund_names.csv - data.gov). לא נמצא - התאמת שם מול הרישום של אותה חברה; ואחרון: התאמת סדרת התשואות
    מול data.gov (returns/datagov_track_map.json, נבנה ב-verify).
תקציב זמן: RETURNS_PARSE_BUDGET שניות (ברירת מחדל 1500); קובץ שנתקע > RETURNS_DOC_TIMEOUT (120) מדולג ומסומן.
"""
import argparse, csv, json, os, re, signal, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.returns.parse import parse_file, ASSET_ORDER

ROOT = Path(__file__).resolve().parents[2]
POL = ROOT / "policy"
RET = ROOT / "returns"
GENERIC_NAME = re.compile(r"(page|sheet|גיליון)\s*\d*|[\d\s.]+", re.I)
NAMED_RETURNS = re.compile(r"מרכיבי[-_ ]*(ה)?תשוא|תרומת[-_ ]*(ה)?אפיקי|yield_?\d|returnelements|תשואה[-_ ]*לפי[-_ ]*אפיק", re.I)
PDF_PARSER_VERSION = 2  # PDF בלבד - מעלים כשמשנים את פרסור ה-PDF (בלי פרסור מחדש של אלפי קבצי אקסל)
PARSER_VERSION = 5  # (v5: תאריך אקסל בתא אינו מספר מסלול) (v4: בלי שורות "תא ריק"/"נתונים לחודש" בשם) (v3: PDF בלי טבלאות - שורות טקסט) (v2: קורא xlsx גולמי כש-openpyxl נכשל, בלי "תחילת מידע טבלה" בשם)


def norm_name(s):
    s = re.sub(r"[\"'״׳`]", "", s or "")
    s = re.sub(r"בע\s*מ|חברה\s*לביטוח|חברה\s*לניהול\s*קופות\s*גמל|פנסיה\s*וגמל|קופות\s*גמל", " ", s)
    s = re.sub(r"^\d+(?=[א-ת])", "", s.strip())  # ילין: "304ילין לפידות..." - קוד פנימי צמוד לשם
    s = re.sub(r"[-–_,.()\[\]:/]", " ", s)
    s = re.sub(r"\bמסלול\b|\bקרן\b|\bקופת\b|\bגמל\b", " ", s)
    return " ".join(s.split())


def display_name(s):
    """שם לתצוגה: בלי קידומת החברה ("הכשרה חברה לביטוח - "), בלי "מספר קופה 62" ובלי קוד פנימי צמוד ("304ילין")."""
    s = re.sub(r"\s*\(?\s*(מספר|מס['׳\"]?)\s*(ה?קופה|ה?מסלול|אוצר)\s*:?\s*\d+\s*\)?", " ", s or "")
    if " - " in s and re.search(r"חברה|בע[\"״]?מ|ביטוח\s*$", s.split(" - ", 1)[0]):
        s = s.split(" - ", 1)[1]
    s = re.sub(r"^\d+(?=[א-ת])", "", s.strip())
    return " ".join(s.split()) or None


def _toks(s):
    return set(norm_name(s).split())


class Registry:
    """רישום המסלולים הרשמי (data.gov): {legal_id: {track_no: name}}, כל ה-FUND_ID, מספרי קופה -> מסלולים."""

    def __init__(self):
        self.by_co = defaultdict(dict)
        self.kupa = defaultdict(lambda: defaultdict(set))
        self.domain = {}
        self.names = {}
        p = POL / "fund_registry.csv"
        if p.exists():
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                if r.get("track_no") and r.get("legal_id"):
                    self.by_co[r["legal_id"]][r["track_no"]] = r.get("name") or ""
                    self.domain[r["track_no"]] = r.get("domain")
                    if r.get("kupa_no"):
                        self.kupa[r["legal_id"]][r["kupa_no"]].add(r["track_no"])
        p = POL / "fund_names.csv"
        if p.exists():
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                self.names[str(r["FUND_ID"])] = r.get("FUND_NAME") or ""
                self.domain.setdefault(str(r["FUND_ID"]), r.get("domain"))
        self.companies = set(self.by_co)
        for sp in (ROOT / "scripts" / "policy" / "sites").glob("*.json"):
            self.companies.add(sp.stem)
        p = RET / "datagov_track_map.json"
        self.yield_map = json.loads(p.read_text("utf-8")) if p.exists() else {}

    def known(self, no):
        return bool(no) and (no in self.names or any(no in d for d in self.by_co.values()))

    def by_name(self, lid, name):
        """התאמת שם מול מסלולי החברה: חפיפת מילים מלאה (בלי מילים כלליות) - רק התאמה יחידה."""
        t = _toks(name)
        if not t:
            return None
        best, score, tie = None, 0.0, False
        for no, nm in self.by_co.get(lid, {}).items():
            u = _toks(nm)
            if not u:
                continue
            j = len(t & u) / len(t | u)
            if j > score + 1e-9:
                best, score, tie = no, j, False
            elif abs(j - score) < 1e-9:
                tie = True
        return best if best and score >= 0.6 and not tie else None

    def resolve(self, lid, no, src, name, key=None):
        """מספר מהקובץ שרשום בחברה -> הוא; התאמת סדרת התשואות ב-data.gov (verify) גוברת על כל השאר (מספר בסוגריים
        שהוא קוד פנימי - אינפיניטי "(715)" = מסלול 1078); מספר קופה עם מסלול יחיד; התאמת שם; מספר שרשום רק בחברה אחרת."""
        ym = (self.yield_map.get(f"{lid}|{key}") if key else None) or (self.yield_map.get(f"{lid}|{norm_name(name)}") if norm_name(name) else None)
        if ym:
            return ym, "datagov_yield"
        if no and no in self.by_co.get(lid, {}):
            return no, src
        if no and len(self.kupa.get(lid, {}).get(no, ())) == 1:  # מספר קופה עם מסלול יחיד
            return next(iter(self.kupa[lid][no])), f"{src}_kupa"
        nm = self.by_name(lid, name)
        if nm:
            return nm, "registry_name"
        if no:
            return no, src if no in self.names else f"{src}_unverified"
        return None, None


def parse_all(out: Path, index: dict, force=False):
    """פרסור קבצים חדשים/שהשתנו -> parsed/<sha12>.json. מחזיר מספר קבצים שפורסרו."""
    pdir = out / "parsed"
    pdir.mkdir(parents=True, exist_ok=True)

    class _T(BaseException):
        pass

    def _alarm(*_):
        raise _T()

    timeout = int(os.environ.get("RETURNS_DOC_TIMEOUT", "120"))
    stop_at = time.monotonic() + float(os.environ.get("RETURNS_PARSE_BUDGET", "1500"))
    can = hasattr(signal, "SIGALRM")
    if can:
        signal.signal(signal.SIGALRM, _alarm)
    n = 0
    for url, e in index.items():
        cache = pdir / f"{e['sha256'][:12]}.json"
        is_pdf = e["file"].lower().endswith(".pdf")
        if not force and e.get("parsed_sha") == e["sha256"] and e.get("parser_version") == PARSER_VERSION \
                and (not is_pdf or e.get("pdf_parser_version") == PDF_PARSER_VERSION) \
                and (cache.exists() or e.get("not_returns") or e.get("parse_error")):
            continue
        if time.monotonic() > stop_at:
            print("[returns.extract] parse budget reached - the next run continues", flush=True)
            break
        f = ROOT / e["file"]
        if not f.exists():
            e.update(parse_error="file missing", parsed_sha=e["sha256"], parser_version=PARSER_VERSION)
            continue
        try:
            if can:
                signal.alarm(timeout)
            res = parse_file(f, e.get("link_text") or "")
            if can:
                signal.alarm(0)
        except _T:
            e.update(parse_error=f"timeout {timeout}s", parsed_sha=e["sha256"], parser_version=PARSER_VERSION)
            print(f"[returns.extract] {f.name}: timeout", flush=True)
            continue
        except Exception as ex:
            if can:
                signal.alarm(0)
            e.update(parse_error=f"{type(ex).__name__}: {str(ex)[:150]}", parsed_sha=e["sha256"], parser_version=PARSER_VERSION)
            print(f"[returns.extract] {f.name}: {type(ex).__name__} {ex}", flush=True)
            continue
        e.pop("parse_error", None)
        if not res["blocks"] and not res["nostro"]:
            # לא דוח מרכיבי תשואה (קובץ אחר באותו עמוד) - נשאר באינדקס (לא יורד שוב), הקובץ עצמו נמחק
            e.update(not_returns=True, parsed_sha=e["sha256"], parser_version=PARSER_VERSION, pdf_parser_version=PDF_PARSER_VERSION)
            if not NAMED_RETURNS.search(url + " " + (e.get("link_text") or "")):
                f.unlink(missing_ok=True)  # קובץ שהשם שלו אומר מרכיבי תשואה נשמר (פרסור מחדש כשהפרסר ישתפר)
            cache.unlink(missing_ok=True)
            continue
        e.pop("not_returns", None)
        slim = {"file_year": res["file_year"], "warnings": res["warnings"], "hints": res["hints"],
                "blocks": [{k: b.get(k) for k in ("track_no", "track_no_src", "track_name", "company", "year", "report_date", "sheet", "scale")}
                           | {"rows": [{k: r.get(k) for k in ("period", "month", "year", "asset_key", "asset_label", "contribution", "weight", "amount")}
                                       for r in b["rows"]]} for b in res["blocks"]],
                "nostro": res["nostro"]}
        cache.write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), "utf-8")
        e.update(parsed_sha=e["sha256"], parser_version=PARSER_VERSION, pdf_parser_version=PDF_PARSER_VERSION, tracks=len(res["blocks"]), file_year=res["file_year"])
        n += 1
        print(f"[returns.extract] {f.name}: blocks={len(res['blocks'])} nostro={len(res['nostro'])} year={res['file_year']}", flush=True)
    if can:
        signal.alarm(0)
    return n


def _r(x, nd=5):
    return None if x is None else round(x, nd)


def build(lid: str, out: Path, index: dict, reg: Registry):
    """כל הקבצים שפורסרו -> tracks.json (מסלול -> חודש -> אפיקים) + nostro.json."""
    pdir = out / "parsed"
    tracks = {}
    docs = {}
    nostro = {}
    for url, e in index.items():
        cache = pdir / f"{e['sha256'][:12]}.json"
        if e.get("not_returns") or not cache.exists():
            continue
        res = json.loads(cache.read_text("utf-8"))
        did = e["sha256"][:12]
        cover = 0
        for b in res["blocks"]:
            cover = max([cover] + [r["month"] or 0 for r in b["rows"] if r["period"] == "m"])
        docs[did] = {"url": url, "file": e["file"], "link_text": (e.get("link_text") or "")[:160], "first_seen": e.get("first_seen"),
                     "year": res.get("file_year"), "cover": cover, "product": e.get("product")}
        rank = (res.get("file_year") or 0, cover, e.get("first_seen") or "")
        for b in res["blocks"]:
            raw_name = (b.get("track_name") or "").strip()
            # בלוק בלי זהות (PDF של ילין: "page1" / "2024 1 2 3 ..." בלי שם מסלול): אסור שיתמזג עם בלוקים אחרים תחת אותו מפתח
            # (n:page1 ערבב עשרות מסלולים) - מפתח לפי הקובץ והגיליון; אימות data.gov יכול לשייך לו מספר (verify)
            generic = not norm_name(raw_name) or bool(GENERIC_NAME.fullmatch(raw_name))
            uid = f"u:{did}:{b.get('sheet') or ''}"
            no, src = reg.resolve(lid, b.get("track_no"), b.get("track_no_src") or "file", "" if generic else raw_name, uid if generic else None)
            key = no or (uid if generic else "n:" + norm_name(raw_name))
            t = tracks.setdefault(key, {"key": key, "track_no": no, "track_no_src": src, "name": None, "names": [],
                                        "m": {}, "ytd": {}, "revisions": [], "_rank": {}})
            nm = "" if generic else raw_name
            if nm and nm not in t["names"]:
                t["names"].append(nm)
            if src and (t["track_no_src"] or "").endswith("_unverified") and not src.endswith("_unverified"):
                t["track_no_src"] = src
            per = defaultdict(lambda: {"c": {}, "w": {}})
            for r in b["rows"]:
                if not r.get("year") or not r.get("month"):
                    continue
                ym = f"{r['year']}-{r['month']:02d}"
                slot = per[(r["period"], ym)]
                if r["contribution"] is not None:
                    slot["c"][r["asset_key"]] = _r(r["contribution"])
                if r["weight"] is not None:
                    slot["w"][r["asset_key"]] = _r(r["weight"], 4)
                if r.get("amount") is not None:
                    slot["amount"] = r["amount"]
            for (period, ym), v in per.items():
                bucket = t["m" if period == "m" else "ytd"]
                rk = t["_rank"].get((period, ym))
                old = bucket.get(ym)
                if old is not None:
                    a, c = old["c"].get("total"), v["c"].get("total")
                    if a is not None and c is not None and abs(a - c) > 0.005:
                        t["revisions"].append({"period": period, "ym": ym, "old": a if rank > rk else c,
                                               "new": c if rank > rk else a, "docs": [old["d"], did]})
                if rk is None or rank > rk:
                    t["_rank"][(period, ym)] = rank
                    bucket[ym] = {**v, "d": did}
        for o in res.get("nostro", []):
            port = o.get("portfolio") or ""
            port = "נוסטרו חיים" if "חיים" in port else "נוסטרו כללי והון" if "כללי" in port else "נוסטרו סה\"כ" if re.search(r"סה|סיכום", port) else port
            k = (port, o["period"], o["year"], o["quarter"], o["asset_key"], o["asset_label"])
            prev = nostro.get(k)
            if prev is None or rank > prev["_rank"]:
                nostro[k] = {**o, "portfolio": port, "d": did, "_rank": rank}
    tracks = {k: t for k, t in tracks.items() if t["m"] or t["ytd"]}
    # אתר משותף לכמה חברות (מגדל פנסיה/ביטוח, הקרנות הוותיקות באתר עמיתים): המסלול שייך לחברה שהמספר שלו רשום אצלה
    # ברישום הרשמי; בלי רישום - לח.פ. שבתחילת שם הקובץ (<ח.פ.>_g526_Yield226). combine והאתר מקבצים לפי owner
    known = reg.companies
    for t in tracks.values():
        owners = {c for c, nos in reg.by_co.items() if t["track_no"] and t["track_no"] in nos}
        if owners and lid not in owners:
            # רק כשהשם תואם את המסלול ברישום של החברה האחרת (152 "פסגות כללי" בהכשרה 2018 != 152 של כלל היום)
            own = sorted(owners)[0] if len(owners) == 1 else None
            a, b = _toks(t["names"][-1] if t["names"] else ""), _toks(reg.by_co.get(own, {}).get(t["track_no"], "")) if own else set()
            if own and a and b and len(a & b) / len(a | b) >= 0.3:
                t["owner"] = own
            elif not t["track_no_src"].endswith("_unverified"):
                t["track_no_src"] += "_other_company"
        elif not owners:
            pref = {m.group(1) for ym in t["m"].values() for m in [re.match(r"(\d{9})_", Path(docs.get(ym["d"], {}).get("file") or "").name.split("_", 1)[-1])] if m}
            pref &= known
            if len(pref) == 1 and lid not in pref:
                t["owner"] = pref.pop()
        if not t.get("owner"):
            t.pop("owner", None)
    for t in tracks.values():
        t.pop("_rank")
        t["name"] = display_name(t["names"][-1]) if t["names"] else None
        if t["track_no"]:
            t["registry_name"] = reg.by_co.get(lid, {}).get(t["track_no"]) or reg.names.get(t["track_no"])
            t["product"] = reg.domain.get(t["track_no"])
        t["m"] = dict(sorted(t["m"].items()))
        t["ytd"] = dict(sorted(t["ytd"].items()))
        months = list(t["m"])
        t["first"], t["last"], t["n_months"] = (months[0] if months else None), (months[-1] if months else None), len(months)
        t["revisions"] = t["revisions"][-50:]
    # עמודות: מערך לכל חודש לפי סדר האפיקים (assets) - חצי מהגודל של מילון לכל חודש
    extra = sorted({k for t in tracks.values() for b in (t["m"], t["ytd"]) for v in b.values() for k in (*v["c"], *v["w"])} - set(ASSET_ORDER))
    assets = ASSET_ORDER + extra
    for t in tracks.values():
        for b in (t["m"], t["ytd"]):
            for ym, v in b.items():
                c = [v["c"].get(k) for k in assets]
                w = [v["w"].get(k) for k in assets]
                while c and c[-1] is None:
                    c.pop()
                while w and w[-1] is None:
                    w.pop()
                b[ym] = {"c": c, "w": w, "d": v["d"], **({"a": v["amount"]} if v.get("amount") is not None else {})}
    data = {"legal_id": lid, "assets": assets, "docs": docs,
            "tracks": sorted(tracks.values(), key=lambda x: (x["track_no"] is None, x["track_no"] or "", x["key"]))}
    (out / "tracks.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    nos = [{k: v for k, v in o.items() if k != "_rank"} for o in nostro.values()]
    if nos:
        (out / "nostro.json").write_text(json.dumps(sorted(nos, key=lambda o: (o["portfolio"], o["year"] or 0, o["period"], o["quarter"])),
                                                    ensure_ascii=False, separators=(",", ":")), "utf-8")
    else:
        (out / "nostro.json").unlink(missing_ok=True)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--all", action="store_true", help="פרסור מחדש של כל הקבצים")
    a = ap.parse_args()
    reg = Registry()
    ids = a.only or sorted(p.name for p in (RET / "companies").glob("*") if (p / "docs_index.json").exists())
    for lid in ids:
        out = RET / "companies" / lid
        idx_path = out / "docs_index.json"
        if not idx_path.exists():
            continue
        index = json.loads(idx_path.read_text("utf-8"))
        n = parse_all(out, index, a.all)
        for u, e in index.items():  # קבצים שנפסלו (לא מרכיבי תשואה) - גם אם חזרו ממיזוג עם הענף
            if e.get("not_returns") and e.get("file") and not NAMED_RETURNS.search(u + " " + (e.get("link_text") or "")):
                (ROOT / e["file"]).unlink(missing_ok=True)
        idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
        data = build(lid, out, index, reg)
        print(f"[returns.extract] {lid}: parsed={n} docs={len(data['docs'])} tracks={len(data['tracks'])}", flush=True)


if __name__ == "__main__":
    main()
