"""פרסור דוחות "פירוט תרומת אפיקי ההשקעה לתשואה הכוללת" (מרכיבי תשואה) - התבנית האחידה של רשות שוק ההון.

מבנה התבנית (זהה כמעט בכל החברות, מזוהה לפי תוכן הגיליון ולא לפי חברה):
  כותרת + פרטי מסלול ("מס מסלול: 438" / "מס' אוצר 9940" / "IRA סנונית הלמן (849)" / שם הגיליון / שם הקובץ),
  שורת "אפיקי השקעה:" עם זוג עמודות לכל חודש - "התרומה לתשואה <חודש>" ו"שיעור מסך הנכסים <חודש>",
  שורה לכל אפיק (מזומנים, אג"ח ממשלתיות, ... השקעות אחרות), "תשואה חודשית", "סה"כ רווח השקעתי",
  ואחר כך פיצולים: נכסים בארץ/בחו"ל, סחירים/לא סחירים, וגוש "נתונים מצטברים" (ינואר-מרץ, ינואר-יוני...).

parse_file(path) -> {"blocks": [...], "meta": {...}}; כל בלוק = מסלול אחד בגיליון/עמוד, עם שורות:
  {period: "m"|"ytd", month, year, section, asset_key, asset_label, contribution, weight, amount}
contribution/weight באחוזים (0.5 = 0.5%), גם כשבקובץ שברים (0.005). amount = סכום בש"ח (שורת רווח השקעתי).
"""
import re
from pathlib import Path

from scripts.policy.extract import read_doc

MONTHS = [("ינואר", "jan"), ("פברואר", "feb"), ("מרץ", "מרס", "mar"), ("אפריל", "apr"), ("מאי", "may"), ("יוני", "jun"),
          ("יולי", "jul"), ("אוגוסט", "aug"), ("ספטמבר", "sep"), ("אוקטובר", "oct"), ("נובמבר", "nov"), ("דצמבר", "dec")]
_MON_RX = "|".join(sorted((w for ws in MONTHS for w in ws), key=len, reverse=True))
MON_RX = re.compile(rf"({_MON_RX})", re.I)
CONTRIB_RX = re.compile(r"תרומ|contribut", re.I)
WEIGHT_RX = re.compile(r"שיעור|משקל|מסך\s*ה?נכסים|weight", re.I)
TITLE_RX = re.compile(r"פירוט\s*תרומת|מרכיבי\s*(ה)?תשואה|תרומת\s*אפיקי", re.I)

# אפיקים קבועים לפי התבנית (סדר = סדר התצוגה). השמות משתנים מעט בין חברות ובין שנים
ASSETS = [
    ("cash", r"מזומנים|שווי\s*מזומנים|עו\"?ש"),
    ("gov_bonds", r"(אג[\"״']?ח|אגרות\s*חוב|איגרות\s*חוב)\s*ממשלתי|ממשלתיות"),
    ("comm_paper_tr", r"תעודות\s*חוב\s*מסחריות\s*סחירות"),
    ("comm_paper_ntr", r"תעודות\s*חוב\s*מסחריות\s*(לא|שאינן)\s*סחירות"),
    ("corp_bonds_tr", r"(אג[\"״']?ח|אגרות\s*חוב|איגרות\s*חוב)\s*קונצרני\w*\s*סחירות"),
    ("corp_bonds_ntr", r"(אג[\"״']?ח|אגרות\s*חוב|איגרות\s*חוב)\s*קונצרני\w*\s*(לא|שאינן)\s*סחירות"),
    ("stocks", r"^מניות"),
    ("etf", r"תעודות\s*סל|תעודות\s*השתתפות|^קרנות\s*סל"),
    ("mutual_funds", r"קרנות\s*נאמנות"),
    ("inv_funds", r"קרנות\s*השקעה"),
    ("warrants", r"כתבי\s*אופציה"),
    ("futures", r"חוזים\s*עתידיים"),
    ("options", r"^אופציות"),
    ("structured", r"מוצרים\s*מובנים"),
    ("loans", r"הלוואות"),
    ("deposits", r"פיקדונות|פקדונות"),
    ("held_cos", r"חברות\s*מוחזקות|השקעה\s*בחברות\s*מוחזקות|חבר(ה|ות)\s*כלול"),
    ("real_estate", r"מקרקעין|נדל\"?ן"),
    ("other", r"השקעות\s*אחרות|נכסים\s*אחרים|אחר$"),
    ("domestic", r"נכסים\s*בארץ|^בארץ$|השקעות\s*בארץ"),
    ("foreign", r"נכסים\s*בח[\"״']?ו[\"״']?ל|^בח[\"״']?ו[\"״']?ל$|השקעות\s*בח"),
    ("tradable", r"נכסים\s*סחירים|^סחיר"),
    ("non_tradable", r"נכסים\s*(לא|שאינם)\s*סחירים|^לא\s*סחיר"),
    ("profit", r"רווח\s*השקעתי|רווח\s*\(?הפסד\)?\s*השקעתי|הכנסות?\s*מהשקעות"),
    ("total", r"תשואה\s*(חודשית|כוללת|מצטברת|לתקופה|נומינלית)|^סה[\"״']?כ(\s*תשואה)?$|^סה[\"״']?כ\s*כולל|^total"),
]
ASSET_RX = [(k, re.compile(p)) for k, p in ASSETS]
SECTION = {"domestic": "geo", "foreign": "geo", "tradable": "trade", "non_tradable": "trade", "total": "total", "profit": "profit"}
ASSET_ORDER = [k for k, _ in ASSETS]


def _clean(v):
    s = "" if v is None else str(v)
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def num(v):
    """'0.0012' / '1.5%' / '(0.3)' / '-' -> float / None"""
    s = _clean(v).replace(",", "")
    if not s or s in ("-", "--", "—"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    pct = "%" in s  # "100%" בקובץ של שברים (הכשרה) = 1.0
    s = s.strip("()").replace("%", "").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    x = x / 100 if pct else x
    return -x if neg else x


def asset_of(label: str):
    t = _clean(label).rstrip(":").strip()
    t = re.sub(r"^\d+[.)]\s*", "", t)
    for k, rx in ASSET_RX:
        if rx.search(t):
            return k
    return None


def month_of(text: str):
    m = MON_RX.search(text or "")
    if not m:
        return None
    w = m.group(1).lower()
    return next(i for i, ws in enumerate(MONTHS, 1) if w in ws)


DATE_RX = re.compile(r"(20\d\d)-(\d\d)-\d\d|(?<!\d)(\d{1,2})[./](\d{1,2})[./](20\d\d|\d\d)(?!\d)|(?<![\d/])(\d{1,2})[./](20\d\d)(?!\d)")


def months_in(text: str):
    """חודשים בטקסט: שם חודש, או תאריך (2021-01-01 / 31/01/2023 / 01/2023) - כותרות שבהן החודש כתאריך."""
    out = [next(i for i, ws in enumerate(MONTHS, 1) if w.group(1).lower() in ws) for w in MON_RX.finditer(text or "")]
    if out:
        return out
    t = (text or "").strip()
    if re.fullmatch(r"\d{5}(\.0+)?", t) and 36000 < float(t) < 60000:  # תאריך אקסל סידורי (44562 = 1/1/2022)
        from datetime import date, timedelta
        return [(date(1899, 12, 30) + timedelta(days=int(float(t)))).month]
    for m in DATE_RX.finditer(text or ""):
        mo = int(m.group(2) or m.group(4) or m.group(6))
        if 1 <= mo <= 12:
            out.append(mo)
    return out


def year_in(text: str):
    m = re.search(r"(?<!\d)(20[0-4]\d|19[89]\d)(?!\d)", text or "")
    return int(m.group(1)) if m else None


def col_kind(text: str):
    if CONTRIB_RX.search(text):
        return "c"
    if WEIGHT_RX.search(text):
        return "w"
    return None


def is_header(row):
    """שורת כותרת עמודות: לפחות 2 תאים של 'תרומה'/'שיעור מסך הנכסים'."""
    kinds = [col_kind(_clean(c)) for c in row]
    return sum(1 for k in kinds if k) >= 2 and any(k == "c" for k in kinds)


def header_columns(rows, hi):
    """-> {col: (kind, period, month, year)} ; period: m=חודש, ytd=מצטבר מתחילת השנה עד month."""
    row = rows[hi]
    cols = {}
    for j, c in enumerate(row):
        t = _clean(c)
        k = col_kind(t)
        if not k:
            continue
        ms = months_in(t)
        src = t
        if not ms:  # חודש בתא ממוזג בשורה שמעל (הערך בתא הראשון של המיזוג)
            for up in (1, 2):
                if hi - up < 0:
                    break
                above = rows[hi - up]
                for jj in range(j, max(-1, j - 4), -1):
                    a = _clean(above[jj]) if jj < len(above) else ""
                    if a and months_in(a):
                        ms = months_in(a)
                        if re.fullmatch(r"\d{5}(\.0+)?", a):  # תאריך סידורי -> "1/2022" (לשנה)
                            from datetime import date, timedelta
                            d = date(1899, 12, 30) + timedelta(days=int(float(a)))
                            a = f"{d.month}/{d.year}"
                        src = a + " " + t
                        break
                if ms:
                    break
        if not ms and re.search(r"מתחילת\s*השנה|מצטבר|ytd", t, re.I):
            cols[j] = (k, "ytd", None, year_in(src))
            continue
        if not ms:
            continue
        cum = len(set(ms)) >= 2 or bool(re.search(r"מצטבר|מתחילת\s*השנה|ytd", src, re.I))
        cols[j] = (k, "ytd" if cum else "m", ms[-1], year_in(src))
    return cols


TRACK_LABEL = re.compile(r"(?:מס['׳\"]?|מספר|קוד)\s*(?:ה?מסלול|אוצר|ה?קופה|קרן|אישור)\s*(?:במס\s*הכנסה)?\s*[:.]?\s*(\d{1,6})(?!\d)"
                         r"|(?:מס['׳\"]?|מספר|קוד)\s*[:.]?\s*(\d{3,6})(?!\d)")
PAREN_NO = re.compile(r"[(\[]\s*(\d{3,6})\s*[)\]]")
NAME_LABEL = re.compile(r"^(?:שם\s*(?:ה?מסלול|ה?קופה|ה?קרן)|מסלול)\s*:?\s*$")
REPORT_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")


def _meta_from_rows(rows, lo, hi):
    """פרטי מסלול מהשורות שמעל שורת הכותרת (lo..hi-1)."""
    meta = {"track_no": None, "track_no_src": None, "track_name": None, "company": None, "year": None,
            "report_date": None, "titles": []}
    for r in rows[lo:hi]:
        cells = [_clean(c) for c in r if _clean(c)]
        cells = [c for c in cells if not re.match(r"^(לא קיים מידע נוסף|סוף הגיליון|הגעת לשדה|תא ללא תוכן)", c)]
        if not cells:
            continue
        line = " ".join(cells)
        for i, c in enumerate(cells):
            nxt = cells[i + 1] if i + 1 < len(cells) else ""
            if re.match(r"^(מס['׳\"]?|מספר|קוד)\s*(ה?מסלול|אוצר|ה?קופה|קרן)", c) and not meta["track_no"]:
                inline = c.split(":", 1)[1] if ":" in c else re.sub(r"^\D+", "", c)
                m = re.match(r"^\s*(\d{1,6})(?:\.0)?\s*$", inline) or re.match(r"^\s*(\d{1,6})(?:\.0)?\s*$", nxt)
                if m:
                    meta["track_no"], meta["track_no_src"] = m.group(1), "label"
            elif re.match(r"^שם\s*(ה?מסלול|ה?קופה|ה?קרן)", c) and not meta["track_name"]:
                inline = c.split(":", 1)[1].strip() if ":" in c else ""
                meta["track_name"] = inline or nxt or None
            elif re.match(r"^שם\s*(ה?חברה|ה?גוף)", c) and nxt:
                meta["company"] = nxt
            elif re.match(r"^שנת\s*(ה?דיווח|דוח)", c):
                meta["year"] = year_in(nxt) or year_in(c) or meta["year"]
            elif re.match(r"^(דיווח\s*ל|נכון\s*ל|ליום|לתאריך)", c):
                d = REPORT_DATE.search(c + " " + nxt)
                if d:
                    y = int(d.group(3)); y = y + 2000 if y < 100 else y
                    meta["report_date"] = f"{y:04d}-{int(d.group(2)):02d}-{int(d.group(1)):02d}"
        if not meta["track_no"]:
            m = TRACK_LABEL.search(line)
            if m:
                meta["track_no"], meta["track_no_src"] = m.group(1) or m.group(2), "label"
        if re.match(r"^(מס['׳\"]?|מספר|קוד|שם|שנת|דיווח|נכון|ליום|תאריך)\s", cells[0]) or TRACK_LABEL.match(line):
            continue
        isno = lambda c: bool(re.fullmatch(r"\d{3,6}(\.0)?", c)) and not re.fullmatch(r"(19[89]\d|20[0-4]\d)(\.0)?", c)
        if len(cells) == 2 and isno(cells[1]) and num(cells[0]) is None:
            # "שם המסלול | 9940" - המספר בתא נפרד ליד השם (ילין: מס' אוצר; לפעמים בשורת שם החברה)
            meta.setdefault("cell_no", cells[1].split(".")[0])
            meta["titles"].append(cells[0])
        elif len(cells) == 1 and isno(cells[0]):
            meta.setdefault("cell_no", cells[0].split(".")[0])  # ילין: שורה שכל תוכנה מספר המסלול
        elif len(cells) == 1:
            meta["titles"].append(line)
        elif len(cells) <= 3:  # שם + קוד פנימי בתא נפרד (ילין: "ילין לפידות גמל לבני 50 עד 60 | AE")
            meta["titles"].append(max(cells, key=len))
    for t in meta["titles"]:
        if not meta["year"] and re.fullmatch(r"\s*(20[0-4]\d)(\.0)?\s*", t):
            meta["year"] = int(float(t))
    if not meta["track_no"]:
        for t in reversed(meta["titles"]):
            m = PAREN_NO.search(t) or re.search(r"(?:מסלול|קופה|מ\.?ה\.?)\s*(\d{3,6})(?!\d)", t)
            if m and not re.search(r"%|S&P|ת\"א", t[max(0, m.start() - 6):m.start()]):
                meta["track_no"], meta["track_no_src"] = m.group(1), "title"
                break
    if not meta["track_no"] and meta.get("cell_no"):
        meta["track_no"], meta["track_no_src"] = meta["cell_no"], "title_cell"
    meta.pop("cell_no", None)
    if not meta["track_name"]:
        names = [t for t in meta["titles"] if not TITLE_RX.search(t) and num(t) is None
                 and not re.search(r"בע[\"״]מ\s*$", t) and len(t) > 2]
        if names:
            meta["track_name"] = names[-1]
    if not meta["year"]:
        for t in meta["titles"]:
            y = year_in(t)
            if y and not TITLE_RX.search(t):
                meta["year"] = y
                break
    return meta


def parse_table(rows, sheet=""):
    """-> בלוקים: לכל שורת כותרת עמודות - האפיקים מתחתיה עד שורת הכותרת הבאה."""
    rows = [list(r) for r in rows]
    heads = [i for i, r in enumerate(rows) if is_header(r)]
    blocks = []
    prev_end = 0
    cur_meta = None
    for n, hi in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(rows)
        meta = _meta_from_rows(rows, prev_end, hi)
        # כותרת "נתונים מצטברים" באותו מסלול (בלי פרטי מסלול חדשים מעליה) - ממשיכה את הבלוק הקודם
        new_track = cur_meta is None or meta["track_no"] or meta["track_name"] and meta["track_name"] != cur_meta.get("track_name") \
            and not re.search(r"מצטבר|נתונים", meta["track_name"] or "")
        if new_track:
            cur_meta = {**meta, "rows": [], "sheet": sheet}
            blocks.append(cur_meta)
        else:
            for k in ("year", "report_date"):
                cur_meta[k] = cur_meta.get(k) or meta.get(k)
        cols = header_columns(rows, hi)
        if not cols:
            prev_end = end
            continue
        first = min(cols)
        # עמודת התווית: התא "אפיקי השקעה" בשורת הכותרת, אחרת התא הטקסטואלי הראשון בשורות הנתונים
        for i in range(hi + 1, end):
            r = rows[i]
            # התווית: תא הטקסט הקרוב ביותר משמאל לעמודת הנתונים הראשונה (הפניקס: עמודות סיווג פנימיות לפני השם
            # המוצג - "אגרות חוב קונצרני | סה"כ נכסים | סחיר | אג"ח קונצרניות סחירות"), אחרת תא הטקסט הראשון
            label = ""
            for j in list(range(min(first, len(r)) - 1, -1, -1)) + list(range(first, len(r))):
                if j in cols:
                    continue
                t = _clean(r[j])
                if t and num(t) is None and not re.fullmatch(r"all|סה\"?כ נכסים", t, re.I):
                    label = t
                    break
            if not label:
                continue
            key = asset_of(label)
            if key is None:
                if re.search(r"מצטבר|נתונים|אפיקי\s*השקעה|^עמודה\s*\d+$", label) or DATE_RX.fullmatch(label):
                    continue
                vals = [num(r[j]) for j in cols if j < len(r)]
                if not any(v is not None for v in vals):
                    continue
                key = "x:" + label[:40]
            for j, (kind, period, month, year) in cols.items():
                if j >= len(r):
                    continue
                v = num(r[j])
                if v is None:
                    continue
                cur_meta["rows"].append({"period": period, "month": month, "year": year, "asset_key": key,
                                         "asset_label": label[:60], "kind": kind, "value": v})
        prev_end = end
    return [b for b in blocks if b["rows"]]


def _scale(block):
    """שברים (0.005) או אחוזים (0.5)? לפי שורת הסה"כ / סכום המשקלים לחודש."""
    w_tot = [r["value"] for r in block["rows"] if r["kind"] == "w" and r["asset_key"] == "total"]
    if w_tot:
        return 100.0 if max(abs(x) for x in w_tot) <= 1.5 else 1.0
    sums = {}
    for r in block["rows"]:
        if r["kind"] == "w" and SECTION.get(r["asset_key"]) is None:
            sums[(r["period"], r["month"])] = sums.get((r["period"], r["month"]), 0) + r["value"]
    if sums:
        return 100.0 if max(abs(x) for x in sums.values()) <= 1.5 else 1.0
    c = [abs(r["value"]) for r in block["rows"] if r["kind"] == "c" and r["asset_key"] == "total"]
    return 100.0 if c and max(c) < 0.3 else 1.0


def finalize(block):
    """שורות גולמיות (תא לכל ערך) -> שורה לכל (תקופה, חודש, אפיק) עם תרומה/משקל באחוזים."""
    sc = _scale(block)
    out = {}
    for r in block["rows"]:
        k = (r["period"], r["month"], r["asset_key"])
        o = out.setdefault(k, {"period": r["period"], "month": r["month"], "year": r["year"], "asset_key": r["asset_key"],
                               "asset_label": r["asset_label"], "section": SECTION.get(r["asset_key"], "asset"),
                               "contribution": None, "weight": None, "amount": None})
        o["year"] = o["year"] or r["year"]
        if r["asset_key"] == "profit":
            if r["kind"] == "c" and o["amount"] is None:
                o["amount"] = r["value"]
            continue
        f = "contribution" if r["kind"] == "c" else "weight"
        if o[f] is None:
            o[f] = round(r["value"] * sc, 6)
    rows = list(out.values())
    # בלי שורת "תשואה חודשית" - הסה"כ = סכום האפיקים
    have_total = {(r["period"], r["month"]) for r in rows if r["asset_key"] == "total" and r["contribution"] is not None}
    sums = {}
    for r in rows:
        if r["section"] == "asset" and r["contribution"] is not None:
            sums[(r["period"], r["month"])] = sums.get((r["period"], r["month"]), 0) + r["contribution"]
    for (p, m), s in sums.items():
        if (p, m) not in have_total:
            rows.append({"period": p, "month": m, "year": None, "asset_key": "total", "asset_label": "(סכום האפיקים)",
                         "section": "total", "contribution": round(s, 6), "weight": None, "amount": None, "derived": True})
    return rows, sc


# ---------- נוסטרו (חברות ביטוח): רבעוני, באלפי ש"ח + חלק מסך ההכנסה, לא תשואה למסלול ----------
NOSTRO_MEASURES = [("inv_income", r"הכנסות\s*מהשקעות"), ("total_income", r"הכנסה\s*הכוללת"), ("assets", r"סך\s*נכסים")]


def parse_nostro_table(rows, sheet=""):
    """גיליון 'פירוט תרומת אפיקי השקעה בנוסטרו': שורת 'נתונים לרבעון בשנת' עם 'רבעון 1..4' (או 'רבעון 1+2' במצטבר),
    מתחתיה שורת מדדים (תרומה להכנסות מהשקעות / תרומה להכנסה הכוללת / סך נכסים), כל אחד: אלפי ש"ח + אחוזים.
    -> [{portfolio, period: q|ytd, quarter, year, asset_key, asset_label, <measure>_ils, <measure>_share}]"""
    rows = [[_clean(c) for c in r] for r in rows]
    out = []
    portfolio = None
    for i, r in enumerate(rows[:6]):
        for c in r:
            if c and re.search(r"נוסטרו|ביטוח\s*חיים|כללי\s*והון|^חיים$", c) and not TITLE_RX.search(c) and "דוח" not in c:
                portfolio = portfolio or c
    heads = [i for i, r in enumerate(rows) if any(re.match(r"^נתונים\s*(לרבעון|מצטברים)", c) for c in r)]
    for n, hi in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(rows)
        qcols = {j: c for j, c in enumerate(rows[hi]) if re.match(r"^רבעון\s*\d", c)}
        if not qcols or hi + 1 >= len(rows):
            continue
        ytd = any(re.match(r"^נתונים\s*מצטברים", c) for c in rows[hi])
        mrow = rows[hi + 1]
        year = next((year_in(c) for c in mrow + rows[hi] if re.fullmatch(r"(20\d\d)(\.0)?", c)), None)
        cols = {}
        for j, c in enumerate(mrow):
            key = next((k for k, rx in NOSTRO_MEASURES if re.search(rx, c)), None)
            if not key:
                continue
            qs = [q for q in qcols if q <= j]
            if not qs:
                continue
            qtxt = qcols[max(qs)]
            quarter = max(int(x) for x in re.findall(r"\d", qtxt))
            cols[j] = (key, "ils", quarter)
            cols[j + 1] = (key, "share", quarter)
        first = min(cols) if cols else 0
        for r in rows[hi + 2:end]:
            label = next((r[j] for j in range(min(first, len(r)) - 1, -1, -1) if r[j] and num(r[j]) is None), "")
            if not label or re.search(r"באלפי|באחוזים", label):
                continue
            key = asset_of(label) or ("designated_bonds" if re.search(r"מיועדות", label) else "x:" + label[:40])
            if key == "total" or re.fullmatch(r"סה[\"״']?כ", label):
                key = "total"
            for j, (measure, unit, q) in cols.items():
                v = num(r[j]) if j < len(r) else None
                if v is None:
                    continue
                rec = next((o for o in out if o["period"] == ("ytd" if ytd else "q") and o["quarter"] == q
                            and o["asset_label"] == label[:60] and o["_hi"] == hi), None)
                if rec is None:
                    rec = {"portfolio": portfolio or sheet, "sheet": sheet, "period": "ytd" if ytd else "q", "quarter": q,
                           "year": year, "asset_key": key, "asset_label": label[:60], "section": SECTION.get(key, "asset"), "_hi": hi}
                    out.append(rec)
                rec[f"{measure}_{unit}"] = round(v * 100, 6) if unit == "share" else v
    # רבעון שלא דווח (הכל אפס) - נזרק
    live = {(o["_hi"], o["quarter"]) for o in out if o.get("assets_ils") or o.get("inv_income_ils")}
    res = []
    for o in out:
        if (o["_hi"], o["quarter"]) in live:
            o.pop("_hi")
            res.append(o)
    return res


FILE_NO = re.compile(r"(?<!\d)\d{9}_([gpib])(\d{3,6})_", re.I)
FILE_PERIOD = re.compile(r"yield\s*([1-4])\s*-?\s*(\d{2})(?!\d)", re.I)


def file_hints(name: str, link_text: str = ""):
    """מספר/תקופה משם הקובץ (מוסכמת רשות שוק ההון: <ח.פ.>_<g|p|i><מספר>_Yield<רבעון><שנה>) וטקסט הקישור."""
    h = {}
    m = FILE_NO.search(name)
    if m:
        h["file_no"], h["file_kind"] = m.group(2), {"g": "גמל", "p": "פנסיה", "i": "ביטוח", "b": "ביטוח"}[m.group(1).lower()]
    m = FILE_PERIOD.search(name)
    if m:
        h["quarter"], h["year"] = int(m.group(1)), 2000 + int(m.group(2))
    blob = f"{name} {link_text}"
    m = re.search(r"מסלול\s*(\d{3,6})(?!\d)", blob)
    if m:
        h["text_no"] = m.group(1)
    if "year" not in h:
        y = year_in(link_text) or year_in(name)
        if y:
            h["year"] = y
    m = re.search(r"\bQ\s*([1-4])\s*[./]?\s*(20)?(\d{2})\b", blob, re.I) or re.search(r"רבעון\s*([1-4])\D{0,8}(20)?(\d{2})(?!\d)", blob)
    if m and "quarter" not in h:
        h["quarter"], h["year"] = int(m.group(1)), 2000 + int(m.group(3))
    return h


def parse_file(path, link_text=""):
    path = Path(path)
    text, tables, names = read_doc(path)
    hints = file_hints(path.name, link_text)
    blocks = []
    for t, (rows) in enumerate(tables):
        sheet = names[t] if t < len(names) else f"t{t}"
        for b in parse_table(rows, sheet):
            if not b["track_no"] and re.fullmatch(r"\d{3,6}", sheet.strip()):
                b["track_no"], b["track_no_src"] = sheet.strip(), "sheet"
            b["rows"], b["scale"] = finalize(b)
            blocks.append(b)
    # PDF: טבלה לכל עמוד - פרטי המסלול בטקסט העמוד (לא בטבלה)
    if path.suffix.lower() == ".pdf" and blocks:
        _pdf_meta(path, blocks)
    # בלוק בלי פרטי מסלול (גיליון "מצטבר", המשך בעמוד הבא ב-PDF) - שייך למסלול היחיד שזוהה בקובץ / לבלוק שלפניו
    ids = {(b["track_no"], b["track_name"]) for b in blocks if b["track_no"] or b["track_name"]}
    for i, b in enumerate(blocks):
        if not b["track_no"] and not b["track_name"]:
            src = next(iter(ids)) if len(ids) == 1 else ((blocks[i - 1]["track_no"], blocks[i - 1]["track_name"]) if i else (None, None))
            b["track_no"], b["track_name"] = src
            b["track_no_src"] = b["track_no_src"] or (blocks[i - 1].get("track_no_src") if i else None)
    single = len({(b["track_no"], b["track_name"]) for b in blocks}) == 1
    warnings = []
    for b in blocks:
        if not b["track_no"] and single and hints.get("file_no"):
            b["track_no"], b["track_no_src"] = hints["file_no"], "file_name"
        if not b["track_no"] and single and hints.get("text_no"):
            b["track_no"], b["track_no_src"] = hints["text_no"], "link_text"
        b.pop("titles", None)
    # שנת הקובץ = השנה הנפוצה בעמודות החודשיות (מה שכתוב בקובץ); אחרת שנת הדיווח / שם הקובץ
    from collections import Counter
    ys = Counter(r["year"] for b in blocks for r in b["rows"] if r["period"] == "m" and r.get("year"))
    file_year = (ys.most_common(1)[0][0] if ys else None) or next((b["year"] for b in blocks if b.get("year")), None) or hints.get("year")
    for b in blocks:
        y = b.get("year") or file_year
        keep = []
        for r in b["rows"]:
            r["year"] = r.get("year") or y
            if file_year and r["year"] != file_year and r["year"] != y:
                warnings.append(f"year_conflict:{b['sheet']}:{r['period']}{r['month']}:{r['year']}")
                continue
            keep.append(r)
        # עמודות של חודשים שעוד לא דווחו (התבנית מכילה את כל 12 החודשים) - ריקות או אפס בכל האפיקים
        live = {(r["period"], r["month"]) for r in keep if r["section"] == "asset"
                and ((r["contribution"] or 0) != 0 or (r["weight"] or 0) != 0)}
        b["rows"] = [r for r in keep if (r["period"], r["month"]) in live]
        b["year"] = y
    blocks = [b for b in blocks if b["rows"]]
    nostro = []
    if not blocks:
        for t, rows in enumerate(tables):
            nostro += parse_nostro_table(rows, names[t] if t < len(names) else f"t{t}")
    return {"blocks": blocks, "nostro": nostro, "hints": hints, "file_year": file_year, "warnings": sorted(set(warnings))[:20],
            "is_returns": bool(blocks) or bool(nostro) or bool(TITLE_RX.search(text[:3000]))}


def _pdf_meta(path, blocks):
    import pdfplumber
    from scripts.policy.extract import _fix_rtl, _is_visual_rtl
    with pdfplumber.open(path) as pdf:
        pages = []
        for pg in pdf.pages:
            t = pg.extract_text() or ""
            pages.append(_fix_rtl(t) if _is_visual_rtl(t) else t)
    for b in blocks:
        m = re.match(r"page(\d+)", b.get("sheet") or "")
        t = pages[int(m.group(1)) - 1] if m and int(m.group(1)) <= len(pages) else ""
        lines = [l.strip() for l in t.splitlines() if l.strip()]
        head = []
        for l in lines:
            if CONTRIB_RX.search(l) or asset_of(l.split(" ")[0] if l else ""):
                break
            head.append([l])
        meta = _meta_from_rows(head, 0, len(head))
        for k in ("track_no", "track_no_src", "track_name", "year", "report_date", "company"):
            if not b.get(k) and meta.get(k):
                b[k] = meta[k]


if __name__ == "__main__":
    import json, sys
    for p in sys.argv[1:]:
        res = parse_file(p)
        for b in res["blocks"]:
            months = sorted({(r["period"], r["month"]) for r in b["rows"]}, key=lambda x: (x[0], x[1] or 0))
            tot = {(r["period"], r["month"]): r["contribution"] for r in b["rows"] if r["asset_key"] == "total"}
            unk = sorted({r["asset_label"] for r in b["rows"] if r["asset_key"].startswith("x:")})
            print(json.dumps({"file": Path(p).name[-50:], "sheet": b["sheet"], "no": b["track_no"], "src": b["track_no_src"],
                              "name": b["track_name"], "year": b["year"], "scale": b["scale"], "n": len(b["rows"]),
                              "months": [f"{p_}{m}" for p_, m in months], "total": {f"{k[0]}{k[1]}": v for k, v in list(tot.items())[:4]},
                              "unknown": unk[:5]}, ensure_ascii=False))
        if not res["blocks"]:
            print(json.dumps({"file": Path(p).name[-50:], "blocks": 0, "hints": res["hints"]}, ensure_ascii=False))
