"""פירוט החזקות מלא לכל מסלול: כל שורה מכל גיליון בדוח, עם החשיפה למניות של השורה
(מניה ישירה / חלק המניות של קרן / נוציונל נגזר) - אותו חישוב בדיוק כמו
validate_equity_exposure ו-index_exposure. לדף המסלול ב-revach (/track_holdings).

מבנה לכל מפתח:
  {"period": "YYYYMM", "cats": [שמות גיליונות], "cols": [...], "rows": [[...], ...],
   "summary": {"by_cat": {גיליון: %}, "equity": {רכיב: %}}}
שורה = רשימה (לא אובייקט - חיסכון של ~60% בנפח ב-D1), לפי HOLDING_COLS.
"""
from collections import defaultdict

from .derivatives_exposure import (
    FUTURES_CATEGORY, OPTIONS_LISTED_CATEGORY, OPTIONS_OTC_CATEGORY, SWAP_CATEGORY,
    SWAP_EQUITY_ASSET_TYPE, _futures_exposure, _options_exposure, _swap_exposure, total_assets_by_key,
)
from .excel_io import text_from, to_ratio
from .funds import FUND_CATEGORIES, PLACEHOLDERS, _build_fund_map, _build_isin_set, _classify
from .funds_classification import fund_siveg
from .index_exposure import DIRECT_EQUITY_CATEGORIES, EQUITY_FUND_SIVEGS, report_month_by_key
from .sheet_source import PCT_COL

# עמודות השורה: גיליון (אינדקס ל-cats), שם, מספר נייר, מנפיק, % מהנכסים, שווי (אלפי ש"ח),
# מטבע, מדינה, פרט (דירוג+פדיון לאג"ח / נכס בסיס לנגזר / סוג), חשיפה למניות, רכיב חשיפה
HOLDING_COLS = ["cat", "name", "id", "issuer", "pct", "value", "ccy", "country", "info", "equity", "component"]

NAME_COLS = ("שם נייר ערך", "שם הלוואה", "שם הבנק", "טיקר", "שם מנפיק", "מאפיין עיקרי")
ID_COLS = ("מספר נייר ערך", "מספר הלוואה", "מספר מזהה בנק", "מספר עסקה (רגל 1)")
VALUE_COLS = ('שווי הוגן (באלפי ש"ח)', 'שווי הנכסים באפיק (באלפי ש"ח)', 'שווי הוגן (נטו באלפי ש"ח)',
              'עלות מופחתת (באלפי ש"ח)')
CCY_COLS = ("מטבע פעילות", "מטבע פעילות (רגל 1)")
INFO_COLS = ("נכס בסיס", "סוג הנכס", "מאפיין עיקרי", "ענף מסחר")


def _first(row: dict, cols) -> object:
    for c in cols:
        v = row.get(c)
        if v not in (None, "") and text_from(v).strip() not in PLACEHOLDERS:
            return v
    return None


def _round(v, nd):
    return round(v, nd) if isinstance(v, (int, float)) else None


def _info(row: dict) -> str | None:
    parts = []
    rating = row.get("דירוג")
    if rating not in (None, "") and text_from(rating).strip() not in PLACEHOLDERS:
        parts.append(text_from(rating).strip())
    mat = row.get("מועד פדיון")
    if hasattr(mat, "strftime"):
        parts.append(mat.strftime("%m/%Y"))
    for c in INFO_COLS:
        v = row.get(c)
        if v not in (None, "") and text_from(v).strip() not in PLACEHOLDERS:
            parts.append(text_from(v).strip())
            break
    return " · ".join(parts) or None


def _fund_equity_fraction(row: dict, fund_map, isin_set, ref_by_num, ref_by_isin, isin_fractions) -> tuple[float, str]:
    """(שבר מניות, רכיב) לשורת קרן - כמו validate_equity_exposure: IL/נסחרת בסיווג
    מחקה-מניות = 1, חוץ = שבר המניות מהשכבות (ETF/SEC/Yahoo/OpenFIGI)."""
    sec_num = row.get("מספר נייר ערך")
    if sec_num is None or sec_num == "" or text_from(sec_num).strip() in PLACEHOLDERS:
        return 0.0, ""
    fund_number, sug = _classify(sec_num, fund_map, isin_set)
    num = str(fund_number or "").strip()
    if sug in ("IL", "נסחרת"):
        r = ref_by_num.get(num) or ref_by_isin.get(num.upper())
        if r and any(s in fund_siveg(r) for s in EQUITY_FUND_SIVEGS):
            return 1.0, "funds_il"
        return 0.0, ""
    frac = (isin_fractions.get(num.upper()) or {}).get("equity") or 0.0
    return float(frac), ("funds_foreign" if frac else "")


def _derivative_exposure(source: list[dict]) -> dict[int, tuple[float, bool, str]]:
    """id(שורה) -> (חשיפה כשבר מנכסי המסלול, האם מניות, רכיב)."""
    totals = total_assets_by_key(source)
    out: dict[int, tuple[float, bool, str]] = {}
    fut: list[dict] = []
    _futures_exposure(source, totals, fut)
    for d in fut:
        out[id(d["row"])] = (d["ratio"], bool(d["equity"]), "futures")
    sw: list[dict] = []
    _swap_exposure(source, totals, sw)
    for d in sw:
        out[id(d["row"])] = (d["ratio"], d["row"].get("סוג הנכס") == SWAP_EQUITY_ASSET_TYPE, "swaps")
    for cat in (OPTIONS_LISTED_CATEGORY, OPTIONS_OTC_CATEGORY):
        opt: list[dict] = []
        _options_exposure(source, totals, cat, opt)
        for d in opt:
            out[id(d["row"])] = (d["ratio"], True, "options")
    return out


def build_holdings_detail(source: list[dict], isin_swap: list[dict], funds_ref: list[dict],
                          isin_fractions: dict[str, dict]) -> dict[str, dict]:
    fund_map, isin_set = _build_fund_map(isin_swap), _build_isin_set(isin_swap)
    ref_by_num = {str(r["מספר קרן"]): r for r in funds_ref if r.get("מספר קרן")}
    ref_by_isin = {str(r["ISIN"]).upper(): r for r in funds_ref if r.get("ISIN")}
    deriv = _derivative_exposure(source)
    period = report_month_by_key(source)

    cats_by_key: dict[str, list[str]] = defaultdict(list)
    rows_by_key: dict[str, list[list]] = defaultdict(list)
    by_cat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    equity: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        cat = rec["Category"]
        for row in rec["Clean"]:
            key = row.get("מפתח")
            if key is None:
                continue
            pct = to_ratio(row.get(PCT_COL))
            value = _first(row, VALUE_COLS)
            value = value if isinstance(value, (int, float)) else None
            name = _first(row, NAME_COLS)
            if not pct and not value and name is None:
                continue  # שורת מילוי ריקה ("ריק במקור", מסגרת אשראי 0)

            eq, comp = 0.0, ""
            if cat in DIRECT_EQUITY_CATEGORIES:
                eq, comp = (pct or 0.0), "direct"
            elif cat in FUND_CATEGORIES:
                frac, comp = _fund_equity_fraction(row, fund_map, isin_set, ref_by_num, ref_by_isin, isin_fractions)
                eq = (pct or 0.0) * frac
            elif id(row) in deriv:
                ratio, is_eq, comp = deriv[id(row)]
                eq = ratio if is_eq else 0.0
                if not is_eq:
                    comp = comp + ":other"  # חשיפה (נוציונל) לא-מנייתית - מוצגת, לא נספרת

            cats = cats_by_key[key]
            if cat not in cats:
                cats.append(cat)
            issuer = row.get("שם מנפיק")
            rows_by_key[key].append([
                cats.index(cat),
                text_from(name).strip() if name is not None else None,
                text_from(_first(row, ID_COLS)).strip() if _first(row, ID_COLS) is not None else None,
                text_from(issuer).strip() if issuer not in (None, "") and issuer != name else None,
                _round(pct, 6),
                _round(value, 1),
                _first(row, CCY_COLS),
                row.get("מדינה לפי חשיפה כלכלית") or row.get('ישראל/חו"ל'),
                _info(row),
                _round(eq, 6) if eq else (_round(deriv[id(row)][0], 6) if comp.endswith(":other") else None),
                comp or None,
            ])
            if pct:
                by_cat[key][cat] += pct
            if eq and not comp.endswith(":other"):
                equity[key][comp] += eq

    out = {}
    for key, rows in rows_by_key.items():
        out[key] = {
            "period": period.get(key),
            "cats": cats_by_key[key],
            "cols": HOLDING_COLS,
            "rows": rows,
            "summary": {
                "by_cat": {c: round(v, 6) for c, v in by_cat[key].items()},
                "equity": {c: round(v, 6) for c, v in equity[key].items()},
            },
        }
    return out
