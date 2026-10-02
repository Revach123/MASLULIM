"""שיוך מספר מסלול (קוד האוצר) לכל מסלול מדיניות - כדי שאפשר יהיה לחבר את המדיניות למסלולים באתר.

סדר המקורות (track_no_source):
  doc        - מספר שהפרסר כבר חילץ מהשורה (fund_id / track_no / קוד ארוך של סלייס)
  name       - מספר בשם המסלול / בקוד (בלי שמות מדדים: ת"א 125, S&P 500; בלי אחוזים ושנים)
  file_name  - מספר בשם הקובץ, כשהקובץ מכיל מסלול אחד (אלטשולר 1395.xlsx, מנורה ...-14315.xlsx)
  file_cells - מספר בתוך המסמך: באותה שורה של שם המסלול, או "מספר מסלול: 1234" / "מ.ה 382" ליד הכותרת
  registry_name_fallback - מוצא אחרון בלבד: התאמת שם מול רישום המסלולים הרשמי (policy/fund_registry.csv, data.gov)
                 באותה חברה. מסומן במפורש - הנתונים נבנים מהקבצים; את השמות משמשים בעיקר לחקור היכן המספר מופיע בקבצים.
אם יש רישום, כל מספר שנמצא בקבצים נבדק מולו (קיים באותה חברה) - מספר שלא קיים נפסל ונבדק המקור הבא.
"""
import csv, re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
POL = ROOT / "policy"

NUM = re.compile(r"(?<![\d.,])(\d{3,6})(?![\d%.,]|\s*%)")
INDEX_BEFORE = re.compile(r"(ת\s*[\"״'׳]?\s*א|תל\s*-?\s*בונד|s[\s&_]*p[\s_]*|nasdaq|נאסד|msci|stoxx|ftse|dax|russell|nikkei|topix|מדד|גיל|בני|תל\s*דיב|sp)\s*[-–]?\s*$", re.I)
CODE_LABEL = re.compile(r"(?:מספר|קוד|מס['׳]?)\s*(?:ה?מסלול|ה?קופה|אוצר|אישור)|מ\.?\s*ה\.?(?=\W)|מ\"ה")


def _norm(s):
    s = re.sub(r"(?i)s\s*&\s*p\s*(\d)", r"sp\1", str(s or ""))  # "S&P 500" = "S&P500"
    s = re.sub(r"[\"'״׳()\[\]\-–_,.:/%]+", " ", s)
    s = re.sub(r"\b(מסלול|קופת|קרן|גמל|לשנת|בע\s*מ|מסל)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _ages(s):
    """גילאים לצורה אחת: "עד 50"/"50 ומטה"/"עד גיל 50" -> גיל50מטה; "50-60"/"50 עד 60" -> גיל5060; "60+"/"60 ומעלה"/"מעל 60" -> גיל60מעלה"""
    s = str(s or "")
    s = re.sub(r"50\s*(?:-|–|עד|ל|\s)\s*60(?!\d)", " גיל5060 ", s)
    s = re.sub(r"(?:עד|מתחת ל)\s*(?:גיל\s*)?50(?!\d)|50\s*ומטה", " גיל50מטה ", s)
    s = re.sub(r"60\s*(?:\+|ומעלה|פלוס)|מעל\s*(?:גיל\s*)?60(?!\d)", " גיל60מעלה ", s)
    return s


def _toks(s):
    s = _ages(s)
    s = re.sub(r"(?i)s\s*&\s*p\s*(\d)", r"sp\1", s)
    s = re.sub(r"(?i)(\d+)\s*s\s*&\s*p\b", r"sp\1", s)  # "500 S&P" (הכשרה)
    s = re.sub(r"(?<!\d)(19|20)\d\d(?!\d)", " ", s)  # שנה בשם ("מסלול כללי מור 2026")
    s = re.sub(r"[\"'״׳()\[\]\-–_,.:;/%]+", " ", s.lower())
    stop = {"מסלול", "קופת", "קופה", "קרן", "לשנת", "בע", "מ", "בעמ", "מסל", "לבני", "בני", "גילאי", "לגילאי", "עד", "ו",
            "המותאם", "לגילאים", "גילאים", "למסלול", "מדיניות", "צפויה", "השקעה"}
    syn = {"מחקה": "עוקב", "עוקבי": "עוקב", "מנייתי": "מניות", "המנייתי": "מניות", "הלכתי": "הלכה", "כהלכה": "הלכה"}
    return frozenset(syn.get(w, w) for w in s.split() if w not in stop)


def numbers_in(text):
    """מספרי מסלול אפשריים בטקסט: 3-6 ספרות, לא שנה, לא אחוז, לא שם מדד (ת"א 125).
    אחרי תווית מפורשת ("מספר מסלול באוצר 47", "מ.ה. 50") גם 1-2 ספרות (הפניקס: מסלולים 47, 50)."""
    out = []
    t = unquote(str(text or ""))
    for m in re.finditer(r"(?:מספר|מס['׳]?)\s*מסלול(?:\s*באוצר)?\s*[:\-]?\s*(\d{1,2})(?!\d)|מ\.\s?ה\.?\s*(\d{1,2})(?!\d)", t):
        out.append(str(int(m.group(1) or m.group(2))))
    for m in NUM.finditer(t):
        n = m.group(1)
        if re.fullmatch(r"(19|20)\d\d", n):
            continue
        if INDEX_BEFORE.search(t[max(0, m.start() - 14):m.start()]):
            continue
        out.append(str(int(n)))
    return out


def from_long_code(code):
    """סלייס: <ח.פ. 9><אפסים><קופה><מסלול 5 ספרות> -> מספר המסלול."""
    c = str(code or "")
    if c.isdigit() and len(c) >= 20:
        return str(int(c[-5:]))
    return None


def from_file_name(url):
    name = unquote(url or "").split("/")[-1].split("?")[0]
    name = re.sub(r"\.(xlsx?|pdf|docx?)$", "", name, flags=re.I)
    if re.fullmatch(r"\d{3,5}", name) and not 2016 <= int(name) <= 2035:  # רק המספר (אלטשולר "1912.xlsx") - מסלול גם אם נראה כשנה; לא שנת מדיניות
        return [str(int(name))]
    name = re.sub(r"(?<!\d)\d{1,2}[._-]\d{1,2}[._-]\d{2,4}(?!\d)", " ", name)  # תאריכים
    name = re.sub(r"(?<!\d)(19|20)\d{6}(?!\d)", " ", name)
    c = [n for n in numbers_in(name) if not re.fullmatch(r"\d{6}", n)]  # 6 ספרות בשם קובץ = לרוב תאריך (260811)
    return c


class Registry:
    def __init__(self):
        self.by_company = {}
        self.ok = False
        p = POL / "fund_registry.csv"
        if not p.exists():
            return
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            lid, tn = (r.get("legal_id") or "").strip(), (r.get("track_no") or "").strip()
            if lid and tn:
                self.by_company.setdefault(lid, {})[tn] = r.get("name") or ""
        names = POL / "fund_names.csv"
        if names.exists():  # שמות עדכניים מגמל-נט/פנסיה-נט/ביטוח-נט
            byid = {}
            for r in csv.DictReader(open(names, encoding="utf-8-sig")):
                byid[r["FUND_ID"]] = r.get("FUND_NAME") or ""
            for lid, d in self.by_company.items():
                for tn in d:
                    if byid.get(tn) and len(byid[tn]) > len(d[tn]):
                        d[tn] = byid[tn]
        self.ok = bool(self.by_company)

    def valid(self, lid, n):
        """המספר קיים ברישום - באותה חברה, או בכל חברה (קרנות ותיקות רשומות תחת עמיתים וכד'), או בגמל-נט/פנסיה-נט/
        ביטוח-נט (fund_names: קרנות משתתפות ברווחים - הראל קרן י 259012, כלל קרן ט 14011 - אינן ברישום)."""
        if not self.ok or lid not in self.by_company or n in self.by_company[lid]:
            return True
        if not hasattr(self, "_all"):
            self._all = {x for d in self.by_company.values() for x in d}
            fp = POL / "fund_names.csv"
            self._fn = {r["FUND_ID"] for r in csv.DictReader(open(fp, encoding="utf-8-sig"))} if fp.exists() else set()
        if n in self._all:
            return True
        # רק בגמל-נט/פנסיה-נט/ביטוח-נט: לפחות 3 ספרות ולא שנה (2016 = מספר קופה/שנה, 75 = "2.075 מש"ח")
        return n in self._fn and len(n) >= 3 and not (1990 <= int(n) <= 2035)

    def match_name(self, lid, name, taken=()):
        cand = self.by_company.get(lid) or {}
        a = _norm(name)
        if not a or not cand:
            return None, 0
        best, score, second = None, 0, 0
        if len(cand) == 1 and re.search(r"(^|\s)כללי$", a) and not re.search(r"\d", a):
            return next(iter(cand)), 0.85  # חברה עם מסלול אחד ברישום, ובקובץ "מסלול כללי" (שופטים, ביוכימאים)
        # השוואת קבוצות מילים, בלי המילים שמשותפות לכל שמות החברה ברישום ("ילין לפידות", "אלטשולר שחם").
        # גמל/להשקעה/השתלמות/פנסיה נשמרות (מבדילות בין קופות). קודם התאמה מלאה יחידה, אחר כך שם המסמך מוכל
        # בשם הרישום והמועמד עם הכי מעט מילים עודפות יחיד
        digs = lambda x: sorted(re.findall(r"(?<!\d)\d{1,3}(?!\d)", re.sub(r"(?i)s\s*&\s*p\s*(\d)|(\d+)\s*s\s*&\s*p\b", r"sp\1\2", _ages(x))))
        sets = {tn: _toks(nm) for tn, nm in cand.items() if digs(nm) == digs(name)}  # גילאים/אחוזים/מדד זהים
        alls = [_toks(nm) for nm in cand.values()]
        common_reg = frozenset.intersection(*alls) if len(alls) > 1 else frozenset()
        common = common_reg | {"חברה", "לביטוח", "בע", "מ", "בעמ"}  # "הכשרה חברה לביטוח בע"מ - כללי" = "הכשרה כללי"
        mine = _toks(name) - common
        mine = frozenset(w for w in mine if not any(pre + w in common_reg for pre in "להוב"))  # "משפטנים" = "למשפטנים"
        # שם ברישום בלי תיאור מסלול ("קרן השתלמות למשפטנים בע"מ") = המסלול הכללי
        sets = {tn: (t if t - common else t | {"כללי"}) for tn, t in sets.items()}
        # ראשי תיבות של שם החברה ברישום ("ק.ל.ע", "עו\"ס") כמילה אחת במסמך ("מסלול קלע כללי") - לא מכריעים
        acr = {re.sub(r"[\"״'׳.]", "", m) for nm in cand.values() for m in re.findall(r"[א-ת]{1,3}(?:[\"״'׳.][א-ת]{1,3})+", str(nm))}
        if mine - acr:
            mine = mine - acr
        if mine:
            same = [tn for tn, t in sets.items() if t - common == mine]
            if len(same) == 1:
                return same[0], 0.95
            if not same:
                sub = [(len(t - common - mine), tn) for tn, t in sets.items() if mine <= t - common]
                if len(sub) == 1:  # שם כללי שמתאים לכמה קופות (גל/כלנית "לבני 50 עד 60") - בלי ניחוש
                    return sub[0][1], 0.9 - 0.01 * sub[0][0]
        for tn, nm in cand.items():
            b = _norm(nm)
            if not b or digs(nm) != digs(name):  # גילאים/אחוזים/מדד חייבים להיות זהים ("לבני 50 ומטה" != "לבני 60 ומעלה")
                continue
            s = 1.0 if a == b else SequenceMatcher(None, a, b).ratio()
            if b.endswith(a) or a.endswith(b):
                s = max(s, 0.9)
            if s > score:
                best, score, second = tn, s, score
            elif s > second:
                second = s
        # שתי התאמות כמעט שוות (עמ"י: "גמל להשקעה ... S&P 500" / "גמל ... S&P 500") - אין הכרעה, עדיף בלי מספר
        return (best, score) if score >= 0.82 and score - second >= 0.03 else (None, score)


_DOC_CACHE = {}


CACHE_PATH = POL / "track_no_cells_cache.json"
_CELLS = None


def cells_cached(doc_file, sheet, track_name):
    """from_file_cells עם מטמון קבוע (קבצי המקור לא משתנים - ה-sha בשם הקובץ), כדי ש-combine יישאר מהיר."""
    global _CELLS
    import json
    if _CELLS is None:
        try:
            _CELLS = json.loads(CACHE_PATH.read_text("utf-8"))
        except Exception:
            _CELLS = {}
    k = f"{doc_file}|{sheet}|{track_name}"
    if k not in _CELLS:
        _CELLS[k] = from_file_cells(doc_file, sheet, track_name)
        _CELLS["__dirty__"] = True
    return _CELLS[k]


def save_cache():
    import json
    if _CELLS and _CELLS.pop("__dirty__", None):
        CACHE_PATH.write_text(json.dumps(_CELLS, ensure_ascii=False, separators=(",", ":"), sort_keys=True), "utf-8")


def from_file_cells(doc_file, sheet, track_name):
    """מספר מסלול בתוך המסמך, צמוד לכותרת המסלול: באותה שורה או ב-2 השורות שאחריה
    ("מספר מסלול באוצר 961" מתחת ל"הפניקס גמל מסלול מניות"). לא סורקים את כל הגיליון - תווית של מסלול אחר
    אינה ראיה. מסלול חדש בלי מספר בקובץ (הפניקס "אג"ח ללא מניות") נשאר בלי מספר."""
    if not doc_file or not track_name:
        return []
    p = ROOT / doc_file
    if not p.exists():
        return []
    if doc_file not in _DOC_CACHE:
        try:
            from .extract import read_doc
            _, tables, names = read_doc(p)
            _DOC_CACHE[doc_file] = list(zip(names or [""] * len(tables), tables))
        except Exception:
            _DOC_CACHE[doc_file] = []
    target = _norm(track_name)
    if len(target) < 4:
        return []
    out = []
    docs = _DOC_CACHE[doc_file]
    for nm, t in docs:
        if sheet and nm and nm != sheet and len(docs) > 1:
            continue
        for ri, row in enumerate(t[:600]):
            cells = [str(c or "").strip() for c in row]
            if not any(_norm(c) == target or (len(target) > 8 and target in _norm(c)) for c in cells):
                continue
            for k in range(ri, min(ri + 3, len(t))):
                cs = [str(c or "").strip() for c in t[k]]
                txt = " ".join(cs)
                if k > ri and any(len(_norm(c)) > 8 and _norm(c) != target and not CODE_LABEL.search(c)
                                  and not re.fullmatch(r"[\d.%\s-]+", c) for c in cs) and not CODE_LABEL.search(txt):
                    break  # התחיל בלוק אחר
                for m in CODE_LABEL.finditer(txt):
                    out += numbers_in(txt[m.end():m.end() + 25])[:1]
                if k == ri:
                    out += [str(int(c)) for c in cs if re.fullmatch(r"\d{3,6}", c) and not re.fullmatch(r"(19|20)\d\d", c)]
            if out:
                return list(dict.fromkeys(out))
    return list(dict.fromkeys(out))


def from_struct_code(code):
    """קוד מובנה <ח.פ.>-<קופה מרופדת>-<מסלול>-000 (מיטב: 512065202-00000000000874-1386-000) -> מספר המסלול (לא הקופה)."""
    m = re.search(r"\d{7,9}-0*(\d+)-(\d+)-\d+$", str(code or ""))
    return str(int(m.group(2))) if m else None


def name_numbers(name):
    """מספרים בשם המסלול. מספר בסוף השם נחשב גם אם נראה כשנה ("מיטבית עתודות ספיר 2002")."""
    out = numbers_in(name)
    m = re.search(r"(?<![\d%])((?:19|20)\d\d)\s*$", str(name or ""))
    # לא שנת יעד ("יעד לפרישה 2040" - מנורה: המסלול הוא 2015; 2040 הוא מסלול של חברה אחרת והמסלול נמחק בכפילויות)
    if m and not re.search(r"לשנת|שנת|מעודכן|פרישה|יעד", str(name)):
        out.append(m.group(1))
    return out


def candidates(t):
    """[(מספר, מקור)] לפי סדר עדיפות - הכל מהקבצים עצמם."""
    c = []
    for n in filter(None, (from_struct_code(t.get("track_code")), from_long_code(t.get("track_code")))):
        c.append((n, "doc_code"))
    for n in name_numbers(t.get("track_name")) + name_numbers((t.get("track_code") or "").split("|")[-1]):
        c.append((n, "name"))
    # מספר קצר (1-2 ספרות) בסוף השם ("כלל כללי 99", "אשראי ואג ח 4") - רק אם הוא מסלול של אותה חברה ברישום (נבדק ב-assign)
    m = re.search(r"(?<![\d%.])(\d{1,2})\s*$", str(t.get("track_name") or ""))
    if m and m.group(1) not in ("50", "60") and not re.search(r"(עד|לבני|גיל|גילאי|ומעלה|ומטה|מעל|\d)\s*$", t["track_name"][:m.start()]):
        c.append((str(int(m.group(1))), "name_short"))
    for f in t.get("fund_ids") or []:
        if not from_struct_code(t.get("track_code")):  # במיטב fund_id = מספר הקופה, לא המסלול
            c.append((str(int(f)) if str(f).isdigit() else str(f), "doc"))
    if t.get("single_track_file"):
        c += [(n, "file_name") for n in from_file_name(t.get("url"))]
    return list(dict.fromkeys(c))


def assign(tracks):
    """tracks: list of dict {legal_id, track_name, track_code, sheet, url, doc_file, fund_ids, single_track_file, active}
    -> מוסיף track_no, track_no_source. מספר שהוקצה לכמה מסלולים שונים באותה חברה נשאר רק אצל המסלול שהמספר
    מופיע בשמו (דליפה מהמסלול הקודם בגיליון - הפניקס/כלל); האחרים עוברים למקור הבא."""
    reg = Registry()
    for t in tracks:
        t["_c"] = [x for x in candidates(t) if reg.valid(t["legal_id"], x[0])
                   and (x[1] != "name_short" or x[0] in reg.by_company.get(t["legal_id"], {}))]
        t["_banned"] = set()
    for _ in range(4):
        owners = {}
        for t in tracks:
            pick = next((x for x in t["_c"] if x[0] not in t["_banned"]), None)
            t["track_no"], t["track_no_source"] = pick if pick else ("", "")
            if pick and t.get("active"):
                owners.setdefault((t["legal_id"], pick[0]), []).append(t)
        changed = False
        for (lid, n), ts in owners.items():
            if len({_norm(x.get("track_name")) for x in ts}) < 2:
                continue
            keep = [x for x in ts if n in name_numbers(x.get("track_name")) or x["track_no_source"] == "doc_code"]
            if len(keep) > 1 and all(x["track_no_source"] != "doc_code" for x in keep):
                keep = keep[:1]  # אותו מסלול מופיע פעמיים בקובץ (הפניקס: גיליון פרט וגיליון ביטוח, אותו מספר באוצר)
            for x in ts:
                if x not in keep or len(keep) > 1 and x["track_no_source"] != "doc_code":
                    x["_banned"].add(n); changed = True
        if not changed:
            break
    owned = {(t["legal_id"], t["track_no"]) for t in tracks if t["track_no"] and t.get("active")}
    for t in tracks:  # בלי מספר מהשורה/השם/הקובץ: תאי המסמך, ורק אחר כך (מוצא אחרון) התאמת שם לרישום
        if t["track_no"]:
            continue
        for n in cells_cached(t.get("doc_file"), t.get("sheet"), t.get("track_name")):
            if reg.valid(t["legal_id"], n) and n not in t["_banned"] and (t["legal_id"], n) not in owned:
                owned.add((t["legal_id"], n))
                t["track_no"], t["track_no_source"] = n, "file_cells"; break
    # track_no_map בהגדרות האתר: [[regex על שם המסלול, מספר]] - מיפוי ידני מבוקר כשהשמות בקובץ מקוצרים
    # (קרנות מורים: "מות מקור הלכתי - מסלול מקוצר" = 2041)
    import json as _json
    sites = Path(__file__).with_name("sites")
    maps = {}
    act_owned = {(t["legal_id"], t["track_no"]) for t in tracks if t["track_no"] and t.get("active")}
    for t in sorted(tracks, key=lambda t: not t.get("active")):  # מסלול פעיל קודם (לאומי: page9 של 2026 לפני 2023)
        lid = t["legal_id"]
        if lid not in maps:
            f = sites / f"{lid}.json"
            maps[lid] = _json.loads(f.read_text("utf-8")).get("track_no_map") if f.exists() else None
        if not t["track_no"] and maps[lid]:
            n = next((str(n) for rx, n in maps[lid] if re.search(rx, t.get("track_name") or "")), None)
            if n and (lid, n) not in act_owned:  # מסלול ישן (לא פעיל) עם אותו מספר לא חוסם
                act_owned.add((lid, n)); owned.add((lid, n)); t["track_no"], t["track_no_source"] = n, "site_map"
    if reg.ok:  # מוצא אחרון: התאמת שם לרישום. ההתאמה הטובה ביותר קודמת ("פאסיבי לבני 50" לפני "לבני 50")
        fb = []
        for i, t in enumerate(tracks):
            if not t["track_no"]:
                for pen, nm in ((0, t.get("track_name")), (0.1, t.get("sheet"))):  # שם גיליון - עדיפות נמוכה
                    n, sc = reg.match_name(t["legal_id"], nm)
                    if n:  # מסלול פעיל קודם למסלול ישן עם אותו שם
                        fb.append((0 if t.get("active") else 1, pen - sc, i, n)); break
        for _, _, i, n in sorted(fb):
            t = tracks[i]
            if (t["legal_id"], n) not in owned:
                owned.add((t["legal_id"], n))
                t["track_no"], t["track_no_source"] = n, "registry_name_fallback"
    for t in tracks:
        t.pop("_c", None); t.pop("_banned", None)
    save_cache()
    return tracks
