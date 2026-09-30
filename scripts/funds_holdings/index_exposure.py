"""חשיפה למניות לפי מדד, לכל מסלול.

כל רכיב של החשיפה למניות (אותם רכיבים ש-validate_equity_exposure מסכם מול
הנתון הרשמי) מפורק לפי המדד שמאחוריו:
- מניות ישירות ("מניות מבכ ויהש", "לא סחיר מניות מבכ ויהש") - "מניות בודדות"
  לפי "מדינה לפי חשיפה כלכלית".
- קרנות ישראליות (IL/נסחרת) מסווג מניות - "נכס בסיס" של הקרן (מנתוני הקרנות
  ב-revach), כולל מדדים משולבים ("All-Bond כללי 70%, ת"א 125 30%") שמפוצלים
  לפי המשקלים, רק החלק המנייתי.
- קרנות חוץ - שם הקרן בדוח × שיעור המניות של ה-ISIN (isin_fractions).
- חוזים עתידיים ועסקאות החלף - לפי החוזה/הטיקר, עם אותה חשיפה לשורה בדיוק
  כמו ב-derivatives_exposure (detail).
- אופציות - סכום אחד ("אופציות").

זיהוי המדד: טבלת מילות מפתח אחת (INDEX_PATTERNS) לכל המקורות - שם קרן,
"נכס בסיס", טיקר סוואפ ושם חוזה. הטבלה רק מאחדת שמות נרדפים של מדדים
מרכזיים (SPTR / "S&P 500 - NTR" / "SOURCE S&P 500 UCITS ETF" -> S&P 500);
שם שלא מזוהה נשאר מדד בפני עצמו בשמו המנורמל, כך שאוצר המדדים נבנה מהנתונים.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .derivatives_exposure import (
    EQUITY_UNDERLYING, FUT_UNDERLYING_COL, OPTIONS_CATEGORIES, SWAP_ASSET_TYPE_COL,
    SWAP_EQUITY_ASSET_TYPE, SWAP_TICKER_COL, _futures_exposure, _swap_exposure,
    total_assets_by_key,
)
from .excel_io import to_ratio
from .funds_classification import fund_siveg
from .sheet_source import PCT_COL

DIRECT_EQUITY_CATEGORIES = ("מניות מבכ ויהש", "לא סחיר מניות מבכ ויהש")
EQUITY_FUND_SIVEGS = ("מחקה - מניות בארץ", "מחקה - מניות בחו\"ל")
COUNTRY_COL = "מדינה לפי חשיפה כלכלית"
NAME_COL = "שם נייר ערך"
SEC_NUM_COL = "מספר נייר ערך"

# (תבנית, מזהה, שם לתצוגה) - לפי הסדר, ספציפי לפני כללי.
_P = [
    # ארה"ב - גרסאות של S&P 500 לפני S&P 500 עצמו
    (r"S\W?P\W?500.{0,12}EX\W?TECH|EX\W?TECHNOLOG|לא כולל טכנולוגיה", "sp500_ex_tech", "S&P (לא כולל טכנולוגיה)"),
    (r"S\W?P\W?500.{0,25}EQUAL|EQUAL\W?WEIGHT", "sp500_ew", "S&P 500 שווה משקל"),
    (r"S\W?P\W?500.{0,20}(ESG|SCORED|SRI|SUSTAIN|PARIS|CLIMATE)|^SLB$|SPXESUP", "sp500_esg", "S&P 500 (ESG)"),
    (r"S\s?[&@+]\s?P\W?500|S&P\W?500|\bSPX\w*|\bSPTR\b|\bSP\W?500|\bSPY\b|\bVOO\b|\bIVV\b|\bCSPX\b"
     r"|^ES$|^ME$|^HWA$", "sp500", "S&P 500"),
    (r"NASDAQ\W?COMP", "nasdaq_comp", "נסדק קומפוזיט"),
    (r"NASDAQ\W?100|NAS\W?100|\bQQQ\b|\bX?NDX\b|\bNAS1\b|נאסד\"?ק|נסד\"?ק|^NQ$|^HWB$", "nasdaq100", "נסדק"),
    (r"DOW\W?JONES\W?INDUSTRIAL|\bDJIA\b|\bINDU\b|^DM$", "dow30", "דאו ג'ונס"),
    (r"RUSSELL\W?2000|\bRTY\b|\bIWM\b|^RTS$", "russell2000", "ראסל 2000"),
    (r"MID\W?CAP\W?400|S\W?P\W?400|^FAW$", "sp400", "S&P 400"),
    # ענפים (בעיקר ארה"ב - Select Sector / MSCI US)
    (r"SEMICONDUCTOR|SEMICON|\bSOX\b|PHLX|\bSMH\b|שבבים|^SWO$|MVSMH", "semis", "שבבים"),
    (r"(WORLD|GLOBAL)\W.{0,25}(TECH|INFORMATION)|טכנולוגיה עולמי|עולמי.{0,5}טכנולוגיה|^NDWUIT$|^M1WO0IT", "world_tech", "טכנולוגיה עולמי"),
    (r"TECHNOLOGY|INFO\w*\W?TECH|TECH\W?SEL|^S5TECH|^S5INFT|\bXLK\b|טכנולוגיה|^IXT(TR)?$", "us_tech", "טכנולוגיה ארה\"ב"),
    (r"COMMUNICATION|COMM\W?SERV|\bXLC\b|תקשורת|^XAS$|^IXC(TR)?$", "us_comm", "תקשורת"),
    (r"CONSUMER\W?DISC|DISCRETION|\bXLY\b|שיקול דעת צרכני|צריכה מחזורית|^XAY$|^IXY(TR)?$", "us_consdisc",
     "שיקול דעת צרכני"),
    (r"STAPLES|\bXLP\b|מוצרי צריכה בסיסיים|^IXR(TR)?$", "us_staples", "מוצרי צריכה בסיסיים ארה\"ב"),
    (r"HEALTH\W?CARE|\bXLV\b|בריאות|^IXV(TR)?$", "us_health", "בריאות ארה\"ב"),
    (r"CLEAN\W?ENERGY|RENEWABLE|אנרגיה מתחדשת|אנרגיה נקייה", "clean_energy", "אנרגיה נקייה"),
    (r"FINANCIAL|\bXLF\b|פיננס|^IXM(TR)?$", "us_fin", "פיננסים ארה\"ב"),
    (r"INDUSTRIAL|\bXLI\b|^IXI(TR)?$", "us_ind", "תעשייה ארה\"ב"),
    (r"UTILIT|^IXU(TR)?$", "us_util", "תשתיות ארה\"ב"),
    (r"ENERGY|\bXLE\b|^IXE(TR)?$", "us_energy", "אנרגיה"),
    # עולמי
    (r"ACWI\W?EX|ALL\W?COUNTRY.{0,15}EX|WORLD\W?EX\W?U\W?S|EX\W?U\W?S\b|לא כולל ארה", "acwi_ex_us",
     "מדד עולמי (לא כולל ארה\"ב)"),
    (r"ACWI|AC\W?WORLD|ALL\W?COUNTRY|עולמי.{0,20}כולל.{0,15}מתעוררים|^ZTL$|^WMW$|M1WD|NDUEACWF", "acwi", "מדד עולמי (כולל שווקים מתעוררים)"),
    (r"EMERG|MSCI\W?EM|\bEM\b|EMG\W?MKT|EM\W?MKT|MXEF|NDUEEGF|M1EF|מתעוררים|^MES$|^RBE$", "msci_em",
     "שווקים מתעוררים"),
    (r"MSCI\W?WORLD|\bWORLD\W?INDEX|DEVELOPED|M1WO|MXWO|\bURTH\b|^ZWP$|^RVP$|^HRL$|מדד עולמי$",
     "msci_world", "מדד עולמי"),
    # אירופה
    (r"STOXX\W?(EUROPE\W?)?600|STX\W?(EUROPE\W?)?600|EURSTX\W?600|EUROPE\W?600|\bSXXP\b|^SXXGR$|^SXO$", "stoxx600",
     "אירופה 600"),
    (r"EURO\W?STOXX\W?BANK|^SX7|^CA$", "stoxx_banks", "EURO STOXX בנקים"),
    (r"EURO\W?STOXX\W?50|STOXX\W?50|EURSTX\W?50|\bSX5E\b|^VG$|יורוסטוקס", "stoxx50", "יורוסטוקס 50"),
    (r"\bDAX\b|^GX$|^DFW$", "dax", "DAX"),
    (r"FTSE\W?100|^Z$", "ftse100", "FTSE 100"),
    (r"\bSMI\b|^SM$", "smi", "SMI שווייץ"),
    (r"EUROPE|EURO\W?ZONE|אירופה", "europe", "אירופה"),
    # אסיה ושאר
    (r"NIKKEI|ניקיי|^NK$|^NO$|^NI$", "nikkei225", "ניקיי 225"),
    (r"TOPIX|\bTPX\w*|^TP$|^TMI$", "topix", "טופיקס"),
    (r"JAPAN|יפן", "japan", "יפן"),
    (r"CHINA|CSI\W?300|סין|^MUR$|NDEUCHF|M1CN", "china", "סין"),
    (r"INDIA|NIFTY|SENSEX|הודו|^JGS$", "india", "הודו"),
    (r"KOREA|KOSPI|קוריאה|^JJY$|^KS$", "korea", "קוריאה"),
    (r"TAIWAN|טייוואן|^FPO$", "taiwan", "טייוואן"),
    (r"HANG\W?SENG|^HI$|^HU$", "hangseng", "הנג סנג"),
    (r"ASX\W?200|AUSTRALIA|^XP$", "australia", "אוסטרליה"),
    (r"TSX|CANADA|^PT$", "canada", "קנדה"),
    # ישראל
    (r"(ת\"?א|TA)[\s-]*35\b|מעו\"?ף|^TA35$", "ta35", "ת\"א 35"),
    (r"(ת\"?א|TA)[\s-]*125\b|^TA125$", "ta125", "ת\"א 125"),
    (r"(ת\"?א|TA)[\s-]*90\b|^TA90$", "ta90", "ת\"א 90"),
    (r"בנקים|^TABANKS$", "il_banks", "בנקים ישראל"),
]
INDEX_PATTERNS = [(re.compile(p, re.IGNORECASE), i, lbl) for p, i, lbl in _P]

_BOND = re.compile(r"BOND|אג\"?ח|ALL-?BOND|תל\W?בונד|תל\W?גוב|מק\"?מ|TREASUR|IBOXX|CORP|\bGOV|\bAGG|"
                   r"אינדקס מדינה|מרווח|\bAA|צמוד|שקלי|\bTIPS\b|HIGH\W?YIELD|\bHY\b|FIXED|CREDIT|"
                   r"פיקדון|כספית|ריבית", re.IGNORECASE)
_SUFFIX = re.compile(r"\s*-\s*(NTR|GTR|TR|PR|NET|GROSS)\s*$|\bINDEX\b|\bINDX\b", re.IGNORECASE)
_COMPOSITE = re.compile(r"([^,;]+?)\s*(\d+(?:\.\d+)?)\s*%")

# חוזה עתידי -> שורש כפי שהוא (^ES$ וכו' בטבלה), מלבד שורשים שמתנגשים במילים
_SWAP_BASKET = re.compile(r"^(GS|JPM|CG|MS|BNP|UBS|BAR|CS|DB|BOA|HSBC|SG|NOM|WF|CITI)[A-Z0-9]{3,}", re.IGNORECASE)
_SINGLE_STOCK = re.compile(r"\b(EQUITY|UW|UN|US|UQ|LN|TT|JT|GY|FP|HK|CN|IT|SM|NA|SW)\s*$", re.IGNORECASE)


def normalize_name(text) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = _SUFFIX.sub("", s).strip(" -")
    return s


def classify_index(text) -> tuple[str, str]:
    """(מזהה, שם לתצוגה). שם לא מוכר -> המזהה והשם הם השם המנורמל עצמו."""
    s = normalize_name(text)
    for rx, idx, label in INDEX_PATTERNS:
        if rx.search(s):
            return idx, label
    return (s or "לא מזוהה"), (s or "לא מזוהה")


def is_bond_name(text) -> bool:
    return bool(_BOND.search(str(text or "")))


def split_composite(text) -> list[tuple[str, float]]:
    """'All-Bond כללי 70%, ת"א 125 30%' -> [('All-Bond כללי', .7), ('ת"א 125', .3)]."""
    parts = [(m.group(1).strip(" ,;"), float(m.group(2)) / 100) for m in _COMPOSITE.finditer(str(text or ""))]
    return parts if parts and abs(sum(w for _, w in parts) - 1) < 0.02 else [(str(text or ""), 1.0)]


def _equity_parts(underlying) -> list[tuple[str, float]]:
    """חלקי המניות של "נכס בסיס" (משקלים מנורמלים ל-1). בלי חלק מנייתי - כל השם."""
    parts = split_composite(underlying)
    eq = [(n, w) for n, w in parts if not is_bond_name(n)]
    total = sum(w for _, w in eq)
    return [(n, w / total) for n, w in eq] if total else [(str(underlying or ""), 1.0)]


class _Acc:
    def __init__(self):
        self.pct: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.label: dict[str, str] = {}
        self.src: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    def add(self, key, idx, label, value, source):
        if not value:
            return
        self.pct[key][idx] += value
        self.label.setdefault(idx, label)
        self.src[key][idx][source] += value


def _country_label(country) -> tuple[str, str]:
    c = str(country or "").strip() or "לא ידוע"
    return f"stocks:{c}", f"מניות {c} (ישירות)"


def _swap_index(row) -> tuple[str, str]:
    ticker = normalize_name(re.sub(r"\s+(INDEX|IND|EQUITY)$", "", str(row.get(SWAP_TICKER_COL) or ""),
                                   flags=re.IGNORECASE))
    idx, label = classify_index(ticker)
    if idx != ticker:
        return idx, label
    raw = str(row.get(SWAP_TICKER_COL) or "")
    country = row.get(COUNTRY_COL) or row.get("פקטור נוסף") or ""
    if _SINGLE_STOCK.search(raw) or re.search(r"\bEquity\b", raw, re.IGNORECASE):
        return _country_label(country)
    if _SWAP_BASKET.match(ticker.replace(" ", "")):
        return f"basket:{country}", f"סל מניות - {country}" if country else "סל מניות"
    return idx, label


def build_index_exposure(source: list[dict], funds: list[dict], funds_ref: list[dict],
                         isin_fractions: dict[str, dict[str, float]]) -> dict[str, dict]:
    """מפתח -> {"total": ..., "indices": {מזהה: {"label", "pct", "sources"}}}.

    source צריך להיות אחרי normalize_track_pct (כמו בכל שאר הרכיבים)."""
    acc = _Acc()
    totals = total_assets_by_key(source)

    # 1. מניות ישירות
    for rec in source:
        if rec["Category"] not in DIRECT_EQUITY_CATEGORIES or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key, pct = row.get("מפתח"), to_ratio(row.get(PCT_COL))
            if key and pct:
                idx, label = _country_label(row.get(COUNTRY_COL))
                acc.add(key, idx, label, pct, "direct")

    # 2. קרנות IL/נסחרת בסיווג מניות - לפי "נכס בסיס"
    ref_by_num = {str(r["מספר קרן"]): r for r in funds_ref if r.get("מספר קרן")}
    ref_by_isin = {str(r["ISIN"]).upper(): r for r in funds_ref if r.get("ISIN")}
    names_by_isin: dict[str, str] = {}
    for rec in source:
        if rec["Category"] in ("קרנות נאמנות", "קרנות סל"):
            for row in rec["Clean"]:
                isin = str(row.get(SEC_NUM_COL) or "").strip().upper()
                name = str(row.get(NAME_COL) or "").strip()
                # השם הארוך ביותר לאותו ISIN מכל הגופים (חלקם קוטעים: "LYX CORE EURSTX")
                if isin and len(name) > len(names_by_isin.get(isin, "")):
                    names_by_isin[isin] = name
    for f in funds:
        pct = to_ratio(f.get("שיעור מסך נכסי ההשקעה"))
        key = f.get("מפתח")
        if not pct or not key:
            continue
        num = str(f.get("מספר קרן") or "").strip()
        if f["סוג"] in ("IL", "נסחרת"):
            r = ref_by_num.get(num) or ref_by_isin.get(num.upper())
            if not r or not any(s in fund_siveg(r) for s in EQUITY_FUND_SIVEGS):
                continue
            for name, w in _equity_parts(r.get("נכס בסיס")):
                idx, label = classify_index(name)
                acc.add(key, idx, label, pct * w, "funds_il")
        elif f["סוג"] == "חוץ":
            frac = isin_fractions.get(num.upper())
            if not frac or not frac.get("equity"):
                continue
            idx, label = classify_index(names_by_isin.get(num.upper(), num))
            acc.add(key, idx, label, pct * frac["equity"], "funds_foreign")

    # 3. חוזים עתידיים - אותה חשיפה לשורה כמו ב-derivatives_exposure
    fut_detail: list[dict] = []
    fut_eq = _futures_exposure(source, totals, fut_detail)[1]
    _add_derivative(acc, fut_detail, fut_eq, "futures",
                    lambda d: classify_index(d["root"]) if d["root"] else classify_index(d["row"].get(NAME_COL)))

    # 4. עסקאות החלף - רק "סוג הנכס" = מניות (כמו validate_equity_exposure)
    swap_detail: list[dict] = []
    _swap_exposure(source, totals, swap_detail)
    swap_detail = [d for d in swap_detail if d["row"].get(SWAP_ASSET_TYPE_COL) == SWAP_EQUITY_ASSET_TYPE]
    swap_eq: dict[str, float] = defaultdict(float)
    for d in swap_detail:
        swap_eq[d["key"]] += d["ratio"]
    _add_derivative(acc, swap_detail, swap_eq, "swaps", lambda d: _swap_index(d["row"]))

    # 5. אופציות - סכום אחד (0.2% מהחשיפה בכלל המסלולים)
    for rec in source:
        if rec["Category"] not in OPTIONS_CATEGORIES or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            if row.get(FUT_UNDERLYING_COL) != EQUITY_UNDERLYING:
                continue
            key, pct = row.get("מפתח"), to_ratio(row.get(PCT_COL))
            if key and pct:
                acc.add(key, "options", "אופציות", pct, "options")

    out = {}
    for key, by_idx in acc.pct.items():
        indices = {i: {"label": acc.label[i], "pct": v, "sources": dict(acc.src[key][i])}
                   for i, v in by_idx.items() if abs(v) > 1e-9}
        out[key] = {"total": sum(v["pct"] for v in indices.values()), "indices": indices}
    return out


def _add_derivative(acc: _Acc, detail: list[dict], capped_equity: dict[str, float], source: str, index_of):
    """שורות עם אותה חשיפה כמו ברכיב המסוכם. מסלול שעבר את תקרת המסלול (ר'
    SANITY_CAP ב-derivatives_exposure) - לפי השווי המדווח של השורות, כמו שם."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for d in detail:
        if d["equity"]:
            by_key[d["key"]].append(d)
    for key, rows in by_key.items():
        use_reported = abs(sum(d["ratio"] for d in rows) - capped_equity.get(key, 0.0)) > 1e-9
        for d in rows:
            idx, label = index_of(d)
            acc.add(key, idx, label, d["row_pct"] if use_reported else d["ratio"], source)


TRACK_FIELDS = {
    "company": "שם החברה", "product": "סוג קרן", "track_number": "מס' מסלול",
    "track_name": "שם מסלול קצר", "track_name_long": "שם מסלול ההשקעה", "track_type": "סוג מסלול",
    "official_equity": "חשיפה למניות", "official_month": "נכון לחודש",
}


def report_month_by_key(source: list[dict]) -> dict[str, str]:
    """מפתח -> YYYYMM של הדוח האחרון שבו המסלול מופיע."""
    out: dict[str, str] = {}
    for rec in source:
        d = rec.get("ReportMonth")
        if d is None:
            continue
        ym = f"{d.year}{d.month:02d}"
        for r in rec["Clean"]:
            k = r.get("מפתח")
            if k is not None and ym > out.get(k, ""):
                out[k] = ym
    return out


def build_index_table(index_exp: dict[str, dict], tracks_by_key: dict[str, dict],
                      report_month: dict[str, str]) -> list[dict]:
    """רשומה למסלול: פרטי המסלול (מ-tracks) + סה"כ חשיפה למניות + פירוק לפי מדד,
    מהגדול לקטן. רק מסלולים שיש להם נתוני דוח."""
    out = []
    empty = {"total": 0.0, "indices": {}}
    for key in set(index_exp) | set(report_month):
        exp = index_exp.get(key, empty)
        t = tracks_by_key.get(key, {})
        rec = {"key": key, **{f: t.get(src) for f, src in TRACK_FIELDS.items()},
               "report_month": report_month.get(key), "equity_total": round(exp["total"], 6)}
        rec["indices"] = [
            {"id": i, "label": e["label"], "pct": round(e["pct"], 6),
             "sources": {s: round(v, 6) for s, v in e["sources"].items()}}
            for i, e in sorted(exp["indices"].items(), key=lambda x: -x[1]["pct"])
        ]
        out.append(rec)
    return sorted(out, key=lambda r: (str(r.get("company") or ""), str(r["key"])))


def summarize(index_table: list[dict], top: int = 25) -> str:
    """סיכום לוג: כמה מהחשיפה שויכה למדד מוכר (מהטבלה), ומדדים מובילים."""
    known = {i for _, i, _ in INDEX_PATTERNS}
    tot: dict[str, float] = defaultdict(float)
    labels: dict[str, str] = {}
    for r in index_table:
        for e in r["indices"]:
            tot[e["id"]] += e["pct"]
            labels[e["id"]] = e["label"]
    S = sum(tot.values()) or 1.0
    recognized = sum(v for i, v in tot.items()
                     if i in known or i.startswith(("stocks:", "basket:")) or i == "options")
    lines = [f"[index] {len(tot)} מדדים; {recognized / S * 100:.1f}% מהחשיפה שויך למדד מוכר / מניות בודדות / סל"]
    for i, v in sorted(tot.items(), key=lambda x: -x[1])[:top]:
        lines.append(f"[index] {v / S * 100:6.2f}%  {labels[i]}")
    unknown = sorted(((v, i) for i, v in tot.items() if i not in known
                      and not i.startswith(("stocks:", "basket:")) and i != "options"), reverse=True)
    lines += [f"[index] לא מזוהה {v / S * 100:5.2f}%  {i}" for v, i in unknown[:top]]
    return "\n".join(lines)
