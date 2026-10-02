"""חשיפה למט"ח לכל מסלול - מודל מקביל לחשיפה למניות, מאומת מול FOREIGN_CURRENCY_EXPOSURE
הרשמי (data.gov.il) לחודש הדוח.

רכיבים (שבר מנכסי המסלול, לפי רכיב - לבדיקה ולתצוגה):
- נכס במטבע חוץ ("מטבע פעילות" שאינו שקל): מזומן ופיקדונות, אג"ח, מניות, קרנות חו"ל, השקעות
  פרטיות/הלוואות/נדל"ן/אחר - לפי שיעורו מנכסי המסלול.
- קרן ישראלית (IL / נסחרת): שיעורה × החשיפה למט"ח שהקרן עצמה מדווחת (revach
  data/funds_info/exposure.csv) - קרן סל על S&P 500 בשקלים חשופה לדולר; קרן גידור מט"ח לא.
- נגזרים עם רגליים (פורוורד / סוואפ ב"לא סחיר נגזרים אחרים"): כל רגל במטבע חוץ, מסומנת - בעסקת
  מט"ח הערך הנקוב × שער החליפין, בסוואפ מניות/ריבית השווי ("שווי הוגן במטבע הנסחר", באלפים) ×
  השער (מכירת דולר בפורוורד = שלילי; סוואפ ששתי רגליו בדולר מתקזז). שער שמצוטט ל-100 יחידות (ין)
  מנורמל; עסקה בין שני מטבעות חוץ לא משנה את הסך, רק מעבירה בין מטבעות. מפוצל לפי "סוג הנכס" (מט"ח / מניות /
  ריבית) - פורוורד גידור מוריד את החשיפה, סוואפ על מדד זר בדולר מוסיף.
- חוזים עתידיים במטבע חוץ: הנוציונל - רכיב נפרד (מטבע החוזה הוא מט"ח, אבל רק המרווח הוא נכס
  בפועל - נבדק מול הנתון הרשמי).
- שורת נגזר נספרת רק דרך הרגליים / הנוציונל, לא לפי השווי ההוגן שלה.
"""
from __future__ import annotations

import re
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

_ILS_HEDGED = re.compile(r"(ILS|NIS|SHEKEL|שקל)\W{0,3}(H\b|HDG|HEDGED)|HEDGED\W{0,3}(ILS|NIS)|מנוטרל|מגודר", re.IGNORECASE)
IL_FUNDS_CCY = "קרנות ישראליות"  # חשיפה מדווחת של הקרן, בלי פירוט מטבע
OTHER_CCY = "אחר"
COMPONENTS = ("cash", "bonds", "stocks", "funds_foreign", "funds_il", "other", "legs_fx", "legs_equity",
              "legs_rates", "legs_other", "legs_cross", "futures", "options")
# מה שנכנס לסך החשיפה - לפי האימות מול הנתון הרשמי (validate_fx_exposure, ריצה 102 / 1,182 מסלולים):
# חוזים עתידיים - רק המרווח הוא נכס במטבע החוזה, לא הנוציונל (MAE 11.26 עם / 3.36 בלי); רגלי סוואפ
# מניות - לא נספרות ברשמי (3.36 עם / 2.92 בלי); אופציות - שולי (3.357 / 3.355)
TOTAL_COMPONENTS = ("cash", "bonds", "stocks", "funds_foreign", "funds_il", "other", "legs_fx", "legs_rates",
                    "legs_other", "legs_cross")


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


RATE_COLS = ("שער חליפין (רגל 1)", "שער חליפין (רגל 2)", "שער חליפין")
CCY_FOR_RATE = {"שער חליפין (רגל 1)": "מטבע פעילות (רגל 1)", "שער חליפין (רגל 2)": "מטבע פעילות (רגל 2)",
                "שער חליפין": CCY_COL}


def typical_rates(source: list[dict]) -> dict[str, float]:
    """מטבע -> שער החליפין החציוני בכל הדוחות (לשורות ולרגליים)."""
    from statistics import median
    vals: dict[str, list[float]] = defaultdict(list)
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            for rc in RATE_COLS:
                r = _num(row.get(rc))
                c = str(row.get(CCY_FOR_RATE[rc]) or "").strip().upper()
                if r and r > 0 and is_foreign_ccy(c):
                    vals[c].append(r)
    return {c: median(v) for c, v in vals.items() if v}


def norm_rate(rate: float | None, ccy, typical: dict[str, float]) -> float | None:
    """שער שמצוטט ל-100 יחידות (ין: 1.8341 ש"ח ל-100 ין, במקום 0.0183 ל-1) - מנורמל לפי השער הטיפוסי
    של אותו מטבע: פי ~100 ממנו -> חלקי 100 (ולהפך)."""
    t = typical.get(str(ccy or "").strip().upper())
    if not rate or not t:
        return rate
    q = rate / t
    if 30 < q < 300:
        return rate / 100
    if 1 / 300 < q < 1 / 30:
        return rate * 100
    return rate


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
    typical = typical_rates(source)
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
                c1, c2 = row.get("מטבע פעילות (רגל 1)"), row.get("מטבע פעילות (רגל 2)")
                if is_foreign_ccy(c1) and is_foreign_ccy(c2):
                    # שני מטבעות חוץ (USD מול JPY): לא משנה את סך החשיפה למט"ח, רק מעביר בין מטבעות -
                    # לפי הרגל הראשונה (רגל במטבע השני מדווחת לעיתים בקנה מידה אחר: 1,569 אלף ין מול 221
                    # מיליון דולר)
                    nominal = _num(row.get("ערך נקוב (רגל 1)"))
                    rate = norm_rate(_num(row.get("שער חליפין (רגל 1)")), c1, typical)
                    if nominal is not None and rate:
                        add(key, "legs_cross", nominal * rate / 1000 / total, c1)
                        add(key, "legs_cross", -nominal * rate / 1000 / total, c2)
                    continue
                for leg in (1, 2):
                    if not is_foreign_ccy(row.get(f"מטבע פעילות (רגל {leg})")):
                        continue
                    rate = norm_rate(_num(row.get(f"שער חליפין (רגל {leg})")), row.get(f"מטבע פעילות (רגל {leg})"), typical)
                    if not rate:
                        continue
                    # עסקת מט"ח: הערך הנקוב הוא סכום במטבע (יש גופים שמדווחים את "שווי הוגן במטבע הנסחר"
                    # כבר בשקלים). סוואפ מניות / ריבית: השווי (באלפים) - "ערך נקוב" של רגל מדד הוא יחידות
                    nominal = _num(row.get(f"ערך נקוב (רגל {leg})")) if kind == "fx" else None
                    if nominal is not None:
                        value = nominal * rate / 1000
                    else:
                        fv = _num(row.get(f"שווי הוגן במטבע הנסחר (רגל {leg})"))
                        if fv is None:
                            continue
                        value = fv * rate
                    add(key, "legs_" + kind, value / total, row.get(f"מטבע פעילות (רגל {leg})"))
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
                sec_txt = text_from(sec).strip().upper() if sec not in (None, "") else ""
                foreign_isin = len(sec_txt) == 12 and sec_txt[:2].isalpha() and not sec_txt.startswith("IL")
                name = str(row.get("שם נייר ערך") or "")
                if is_foreign_ccy(row.get(CCY_COL)):
                    add(key, "funds_foreign", pct, row.get(CCY_COL))
                elif foreign_isin and not _ILS_HEDGED.search(name):
                    # קרן זרה בדואלי בת"א (iShares / Invesco S&P 500, IE...) - נסחרת בשקלים, הנכסים בדולר
                    add(key, "funds_foreign", pct, OTHER_CCY)
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


def fx_total(components: dict[str, float], include=TOTAL_COMPONENTS) -> float:
    return sum(v for c, v in components.items() if c in include)
