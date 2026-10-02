"""חשיפה למט"ח לכל מסלול - מודל מקביל לחשיפה למניות, מאומת מול FOREIGN_CURRENCY_EXPOSURE
הרשמי (data.gov.il) לחודש הדוח.

רכיבים (שבר מנכסי המסלול, לפי רכיב - לבדיקה ולתצוגה):
- נכס במטבע חוץ ("מטבע פעילות" שאינו שקל): מזומן ופיקדונות, אג"ח, מניות, קרנות חו"ל, השקעות
  פרטיות/הלוואות/נדל"ן/אחר - לפי שיעורו מנכסי המסלול.
- קרן ישראלית (IL / נסחרת): שיעורה × החשיפה למט"ח שהקרן עצמה מדווחת (revach
  data/funds_info/exposure.csv) - קרן סל על S&P 500 בשקלים חשופה לדולר; קרן גידור מט"ח לא.
- נגזרים עם רגליים (פורוורד / סוואפ ב"לא סחיר נגזרים אחרים"): השווי המסומן של כל רגל במטבע
  חוץ ("שווי הוגן במטבע הנסחר", באלפים) × שער החליפין (מכירת דולר בפורוורד = שלילי; סוואפ ששתי
  רגליו בדולר מתקזז). מפוצל לפי "סוג הנכס" (מט"ח / מניות /
  ריבית) - פורוורד גידור מוריד את החשיפה, סוואפ על מדד זר בדולר מוסיף.
- חוזים עתידיים במטבע חוץ: הנוציונל - רכיב נפרד (מטבע החוזה הוא מט"ח, אבל רק המרווח הוא נכס
  בפועל - נבדק מול הנתון הרשמי).
- שורת נגזר נספרת רק דרך הרגליים / הנוציונל, לא לפי השווי ההוגן שלה.
"""
from __future__ import annotations

from collections import defaultdict

from .derivatives_exposure import _futures_exposure, _num, total_assets_by_key
from .excel_io import text_from, to_ratio
from .fund_exposure_reference import fund_number_key
from .funds import FUND_CATEGORIES, PLACEHOLDERS, _build_fund_map, _build_isin_set, _classify
from .sheet_source import PCT_COL

CCY_COL = "מטבע פעילות"
ILS = {"ILS", "NIS", "שקל", "שקל חדש", 'ש"ח', "שח", "₪", "ILA"}
LEGS_CATEGORY = "לא סחיר נגזרים אחרים"
FUTURES_CATEGORIES = {"חוזים עתידיים", "לא סחיר חוזים עתידיים"}
DERIVATIVE_CATEGORIES = {LEGS_CATEGORY, *FUTURES_CATEGORIES, "אופציות", "לא סחיר אופציות", "כתבי אופציה",
                         "לא סחיר כתבי אופציה"}
NOT_ASSET = {"יתרות התחייבות להשקעה", "מסגרות אשראי"}  # התחייבות / מסגרת לא מנוצלת - לא נכס
CASH = {"מזומנים ושווי מזומנים", "פיקדונות מעל 3 חודשים"}
STOCKS = {"מניות מבכ ויהש", "לא סחיר מניות מבכ ויהש"}
BONDS_WORD = ("איגרות חוב", "ניירות ערך מסחריים")
LEG_KIND = {'מט"ח': "fx", "מניות לרבות מדדי מניות": "equity", 'ריבית ואג"ח': "rates"}

IL_FUNDS_CCY = "קרנות ישראליות"  # חשיפה מדווחת של הקרן, בלי פירוט מטבע
OTHER_CCY = "אחר"
COMPONENTS = ("cash", "bonds", "stocks", "funds_foreign", "funds_il", "other", "legs_fx", "legs_equity",
              "legs_rates", "legs_other", "futures", "options")


def is_foreign_ccy(ccy) -> bool:
    c = str(ccy or "").strip().upper()
    return bool(c) and c not in ILS and c not in {x.upper() for x in ILS} and c not in PLACEHOLDERS \
        and c not in ("ריק במקור", "-", "NA", "תא ללא תוכן, המשך בתא הבא")


def _asset_component(cat: str) -> str:
    if cat in CASH:
        return "cash"
    if cat in STOCKS:
        return "stocks"
    if any(w in cat for w in BONDS_WORD):
        return "bonds"
    return "other"


def build_fx_exposure(source: list[dict], isin_swap: list[dict], funds_ref: list[dict],
                      fund_fx: dict[str, float] | None = None,
                      by_currency: dict[str, dict[str, float]] | None = None) -> dict[str, dict[str, float]]:
    """מפתח -> {רכיב: שבר}. fund_fx: מספר קרן -> חשיפה למט"ח מדווחת (fetch_fund_fx_exposure).
    by_currency (אופציונלי) מתמלא: מפתח -> {מטבע: שבר} - קרנות ישראליות (בלי פירוט מטבע) תחת IL_FUNDS_CCY."""
    fund_fx = fund_fx or {}
    fund_map, isin_set = _build_fund_map(isin_swap), _build_isin_set(isin_swap)
    ref_by_num = {str(r["מספר קרן"]): r for r in funds_ref if r.get("מספר קרן")}
    ref_by_isin = {str(r["ISIN"]).upper(): r for r in funds_ref if r.get("ISIN")}
    totals = total_assets_by_key(source)
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    ccy_out = by_currency if by_currency is not None else {}

    def add(key, comp, value, ccy):
        out[key][comp] += value
        c = str(ccy or "").strip().upper() or OTHER_CCY
        d = ccy_out.setdefault(key, {})
        d[c] = d.get(c, 0.0) + value

    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        cat = rec["Category"]
        if cat in NOT_ASSET or cat in FUTURES_CATEGORIES:
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            if key is None:
                continue
            if cat == LEGS_CATEGORY:
                total = totals.get(key)
                if not total:
                    continue
                kind = LEG_KIND.get(str(row.get("סוג הנכס") or "").strip(), "other")
                for leg in (1, 2):
                    if not is_foreign_ccy(row.get(f"מטבע פעילות (רגל {leg})")):
                        continue
                    # שווי הרגל במטבע שלה (באלפים) - "ערך נקוב" של רגל מדד הוא כמות יחידות, לא סכום
                    fv = _num(row.get(f"שווי הוגן במטבע הנסחר (רגל {leg})"))
                    rate = _num(row.get(f"שער חליפין (רגל {leg})"))
                    if fv is None or not rate:
                        continue
                    add(key, "legs_" + kind, fv * rate / total, row.get(f"מטבע פעילות (רגל {leg})"))
                continue
            pct = to_ratio(row.get(PCT_COL))
            if not pct:
                continue
            if cat in DERIVATIVE_CATEGORIES:
                if is_foreign_ccy(row.get(CCY_COL)):
                    add(key, "options", pct, row.get(CCY_COL))
                continue
            if cat in FUND_CATEGORIES:
                sec = row.get("מספר נייר ערך")
                if sec not in (None, "") and text_from(sec).strip() not in PLACEHOLDERS:
                    num, sug = _classify(sec, fund_map, isin_set)
                    if sug in ("IL", "נסחרת"):
                        ref = ref_by_num.get(str(num).strip()) or ref_by_isin.get(str(num).strip().upper())
                        fx = fund_fx.get(fund_number_key(ref.get("מספר קרן")) or "") if ref else None
                        if fx is not None:
                            add(key, "funds_il", pct * fx, IL_FUNDS_CCY)
                            continue
                if is_foreign_ccy(row.get(CCY_COL)):
                    add(key, "funds_foreign", pct, row.get(CCY_COL))
                continue
            if is_foreign_ccy(row.get(CCY_COL)):
                add(key, _asset_component(cat), pct, row.get(CCY_COL))

    # חוזים עתידיים: הנוציונל של חוזה במטבע חוץ (אותו חישוב כמו בחשיפה למניות)
    fut: list[dict] = []
    _futures_exposure(source, totals, fut)
    for d in fut:
        if is_foreign_ccy(d["row"].get(CCY_COL)):
            add(d["key"], "futures", d["ratio"], d["row"].get(CCY_COL))
    return {k: dict(v) for k, v in out.items()}


def fx_total(components: dict[str, float], include=COMPONENTS) -> float:
    return sum(v for c, v in components.items() if c in include)
