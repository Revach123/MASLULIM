"""חשיפה אמיתית לנגזרים: תיקון לבאג לפיו "שיעור מסך נכסי ההשקעה" שמדווח
בגיליונות "חוזים עתידיים" ו"לא סחיר נגזרים אחרים" (עסקאות החלף/פורוורד)
משקף רק את השווי ההוגן של המכשיר (מרווח/רווח-הפסד שוטף) - לא את החשיפה
הכלכלית שהוא יוצר. לחוזה עתידי אין עלות רכישה (leverage מובנה): השווי ההוגן
הוא רק הרווח/הפסד שנצבר, בעוד שהחוזה בפועל שולט בנכס בסיס ששווה פי כמה
וכמה. אותו הדבר לעסקת פורוורד/סוואפ: השווי ההוגן נטו הוא ההפרש הקטן בין
שתי הרגליים, לא הסכום (הנקוב) שכל רגל שלה חושפת.

מקור: לא חלק מ-Autopilot_Section1.m - הרחבה חדשה, לפי הנחיית המשתמש
("הנתונים הם שיעור מנכסים, לא חשיפה - בפרט בחוזים עתידיים ועסקאות החלף").

שיטה
----
1. שווי כולל נכסי מסלול (באלפי ש"ח): לא מדווח במפורש בגיליונות הפרטניים,
   אבל ניתן לגזור אותו מהיחס שמגדיר את "שיעור מסך נכסי ההשקעה" בכל שורה
   בכל גיליון (כולל נגזרים): pct = שווי_הוגן / שווי_כולל. לכל מסלול
   לוקחים את שווי_הוגן/pct מהשורה עם |שווי הוגן| הגדול ביותר (יציבה
   נומרית יותר משורות עם pct זעיר).

2. חוזים עתידיים: החשיפה הכלכלית = ערך נקוב (יחידות, עם סימן - קניה/מכירה)
   כפול שער נייר הערך (מחיר/רמת מדד) כפול שער חליפין. זו בדיוק אותה נוסחה
   ששווי מניה/אג"ח בדוחות האלה מחושב לפיה (ערך נקוב × שער [× שער חליפין]),
   רק שעבור חוזה עתידי היא נותנת את השווי שהחוזה *שולט* בו (notional) -
   לא את "השווי ההוגן" המדווח (מרג'ין+רווח/הפסד, קטן בהרבה כמעט תמיד).
   מגבלה מתועדת: אין בדוח "מכפיל חוזה" (למשל $50/נקודה ב-ES future) - אם
   "ערך נקוב" הוא מספר החוזים הגולמי בלי הכפלה במכפיל, החשיפה בפועל
   תת-מוערכת. אין בדוח, ואין במקור אחר בריפו, דרך לאמת מכפיל per-instrument.

3. עסקאות החלף/פורוורד ("לא סחיר נגזרים אחרים"): כל עסקה מדווחת בשתי
   רגליים, כל אחת עם "ערך נקוב" ו"שער חליפין" משלה. החשיפה = ממוצע הערך
   המוחלט (בש"ח) של שתי הרגליים - בד"כ קרובות זו לזו (אותה עסקה, שתי
   יחידות מדידה); הממוצע מנטרל סטיות קטנות מתנודות שער/ריבית מאז שהעסקה
   ננעלה.

4. התוצאה מיועדת *להחליף* (לא להצטרף ל-) שתי הקטגוריות האלה בפלט של
   category_pct.build_category_pct - שאר הקטגוריות (מזומן, אג"ח, מניות,
   קרנות...) כבר משקפות שווי שוק אמיתי, אין בהן את הבאג.
"""
from .excel_io import to_ratio
from .sheet_source import PCT_COL

FAIR_VALUE_COL = 'שווי הוגן (באלפי ש"ח)'
SWAP_NET_FAIR_VALUE_COL = 'שווי הוגן (נטו באלפי ש"ח)'

# תקרת סבירות לשורה בודדת: חשיפה נוציונלית שמשתמעת ליותר מ-300% משווי המסלול
# כולו ממכשיר נגזר *יחיד* אינה סבירה עבור מסלול פנסיוני מפוזר - ונצפה בפועל
# (למשל אג"ח סינתטית עם "ערך נקוב" במוסכמת שווי-נקוב-100, לא מספר חוזים גולמי,
# שנופלת על אותו שם עמודה כמו חוזה CME רגיל). בשורה כזו לא ניתן לסמוך על
# הנוסחה (מוסכמת היחידות/מחיר של השורה הזו כנראה שונה) - נופלים חזרה לערך
# שהדוח עצמו מדווח (שווי הוגן/שווי כולל) לשורה הספציפית הזו בלבד, כפי שהיה
# לפני התיקון - עדיף על תוצאה מנופחת שאי אפשר לסמוך עליה.
SANITY_CAP = 3.0

FUTURES_CATEGORY = "חוזים עתידיים"
SWAP_CATEGORY = "לא סחיר נגזרים אחרים"
DERIVATIVE_CATEGORIES = (FUTURES_CATEGORY, SWAP_CATEGORY)

FUT_UNITS_COL = "ערך נקוב (יחידות)"
FUT_FX_COL = "שער חליפין"
FUT_PRICE_COL = "שער נייר הערך"

SWAP_LEGS = (
    {"units": "ערך נקוב (רגל 1)", "fx": "שער חליפין (רגל 1)"},
    {"units": "ערך נקוב (רגל 2)", "fx": "שער חליפין (רגל 2)"},
)


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", ""))
    except ValueError:
        return None


def total_assets_by_key(source: list[dict]) -> dict[str, float]:
    """מפתח -> שווי כולל נכסי מסלול (באלפי ש"ח), נגזר מ-שווי הוגן/שיעור מסך
    נכסי ההשקעה של השורה עם |שווי הוגן| הגדול ביותר לאותו מסלול."""
    best: dict[str, tuple[float, float]] = {}
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            if key is None:
                continue
            fv = _num(row.get(FAIR_VALUE_COL))
            pct = to_ratio(row.get(PCT_COL))
            if fv is None or not pct:
                continue
            total = fv / pct
            cur = best.get(key)
            if cur is None or abs(fv) > cur[0]:
                best[key] = (abs(fv), total)
    return {k: v[1] for k, v in best.items()}


def _futures_exposure(source: list[dict], total_assets: dict[str, float]) -> dict[str, float]:
    sums: dict[str, float] = {}
    for rec in source:
        if rec["Category"] != FUTURES_CATEGORY or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            total = total_assets.get(key) if key is not None else None
            if not total:
                continue
            units = _num(row.get(FUT_UNITS_COL))
            price = _num(row.get(FUT_PRICE_COL))
            fx = _num(row.get(FUT_FX_COL))
            line_ratio = None
            if units is not None and price is not None and fx is not None:
                notional_thousands = units * price * fx / 1000  # לאלפי ש"ח, כמו שווי הוגן
                line_ratio = notional_thousands / total
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                fv = _num(row.get(FAIR_VALUE_COL))
                line_ratio = (fv / total) if fv is not None else 0.0
            sums[key] = sums.get(key, 0.0) + line_ratio
    return sums


def _swap_exposure(source: list[dict], total_assets: dict[str, float]) -> dict[str, float]:
    sums: dict[str, float] = {}
    for rec in source:
        if rec["Category"] != SWAP_CATEGORY or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            total = total_assets.get(key) if key is not None else None
            if not total:
                continue
            leg_values = []
            for leg in SWAP_LEGS:
                units = _num(row.get(leg["units"]))
                fx = _num(row.get(leg["fx"]))
                if units is None or fx is None:
                    continue
                leg_values.append(abs(units * fx) / 1000)  # לאלפי ש"ח
            line_ratio = None
            if leg_values:
                notional_thousands = sum(leg_values) / len(leg_values)
                line_ratio = notional_thousands / total
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                fv = _num(row.get(SWAP_NET_FAIR_VALUE_COL))
                line_ratio = (fv / total) if fv is not None else 0.0
            sums[key] = sums.get(key, 0.0) + line_ratio
    return sums


def build_derivatives_exposure(source: list[dict]) -> dict[str, dict[str, float]]:
    """מפתח -> {קטגוריה: שיעור חשיפה אמיתי}, לשתי הקטגוריות בלבד (חוזים
    עתידיים, לא סחיר נגזרים אחרים). מיועד להחליף את הערכים המבוססי-שווי-הוגן
    שמחשב category_pct.build_category_pct לאותן שתי קטגוריות בדיוק - ולא
    לגעת בשאר הקטגוריות."""
    total_assets = total_assets_by_key(source)
    futures = _futures_exposure(source, total_assets)
    swaps = _swap_exposure(source, total_assets)

    out: dict[str, dict[str, float]] = {}
    for key, val in futures.items():
        out.setdefault(key, {})[FUTURES_CATEGORY] = val
    for key, val in swaps.items():
        out.setdefault(key, {})[SWAP_CATEGORY] = val
    return out
