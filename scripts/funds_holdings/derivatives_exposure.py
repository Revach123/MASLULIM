"""חשיפה אמיתית לנגזרים: תיקון לבאג לפיו "שיעור מסך נכסי ההשקעה" שמדווח
בגיליונות "חוזים עתידיים" ו"לא סחיר נגזרים אחרים" (עסקאות החלף/פורוורד)
משקף רק את השווי ההוגן של המכשיר (מרווח/רווח-הפסד שוטף) - לא את החשיפה
הכלכלית שהוא יוצר. לחוזה עתידי אין עלות רכישה (leverage מובנה): השווי ההוגן
הוא רק הרווח/הפסד שנצבר, בעוד שהחוזה בפועל שולט בנכס בסיס ששווה פי כמה
וכמה. אותו הדבר לעסקת פורוורד/סוואפ: השווי ההוגן נטו הוא ההפרש הקטן בין
שתי הרגליים, לא הסכום (הנקוב) שכל רגל שלה חושפת.

מקור: לא חלק מ-Autopilot_Section1.m - הרחבה חדשה, לפי הנחיית המשתמש
("הנתונים הם שיעור מנכסים, לא חשיפה - בפרט בחוזים עתידיים ועסקאות החלף").

אישוש רגולטורי (לא רק היסק אמפירי): החוזר המאוחד, שער 5 חלק 4 פרק 3,
נספח 5.4.3.2 חלק ג' - "רשימת נכסים ברמת הנכס הבודד", סעיף 4.22 "לא סחיר
נגזרים אחרים", קובע במפורש שהעמודות "מספר נייר ערך", "מטבע", "ערך נקוב",
"שער", "שווי הוגן", "שיעור מנכסי אפיק ההשקעה" ו"שיעור מסך נכסי ההשקעה"
מדווחות "עבור כל רגל בנפרד" - כלומר "שיעור מסך נכסי ההשקעה" הוא באמת
לפי-רגל (לא לפי-עסקה), ו"ערך נקוב" מוגדר שם (בסעיף ההגדרות הכללי) כ"מספר
היחידות" (לא סכום נקוב במטבע) - בדיוק ההנחות שהקוד למטה בונה עליהן.
נספח 5.4.3.5 - "אופן חישוב חשיפות בדוחות חודשיים" - קובע כעיקרון כללי
לחישוב חשיפה בנגזרים ש"חישוב החשיפה יעשה... על פי... אקוויוולנט של נכס
הבסיס בחוזה" (ערך נקוב × שער נכס הבסיס), לא לפי השווי ההוגן המדווח - מאשש
את העיקרון המרכזי של המודול הזה (לא רק ניחוש סביר).

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

   שתי תקלות עקביות נוספות שנמצאו בבדיקה בפועל על כל הארכיון (לא הודעה
   תיאורטית - כל אחת אומתה בנתונים אמיתיים):
   - JPY: חלק מהמגישים רושמים "שער חליפין" ליין לפי מוסכמת "יחס ל-100"
     (כמו שער בנק ישראל) במקום שער ליחידה - לא עקבי אפילו בתוך אותו מגיש
     (רוב השורות ~0.018, חלקן ~1.83 - פי 100 בדיוק). מזוהה ומתוקן לפי סף
     (שער אמיתי ליין תמיד נמוך בהרבה מ-1).
   - "התחייבות"-Index (רגל מימון סינתטית, למשל "09/2026 JPM ESU6 Index
     התחייבות"): "שער נייר הערך" קבוע בדיוק על 100 - מוסכמת ערך-נקוב-100
     (כמו אג"ח), לא רמת מדד גולמית. יחידות בסדר גודל של מיליונים עם המוסכמה
     הרגילה (יחידות × 100 × שער) מייצרות חשיפה מנופחת פי 100 - מזוהות לפי
     שער == 100.0 בדיוק ומטופלות כמו אג"ח (יחידות/100 × שער, לא יחידות×שער).

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

# תקרת מנוף לשורה בודדת (חוזים עתידיים): נמצא בבדיקה שלמגישים שונים יש
# מוסכמות שונות/לא-עקביות ל"שער נייר הערך" (לא רק מוסכמת ערך-נקוב-100 -
# גם מגישים ששמים את המחיר בקנה מידה שרירותי אחר, למשל פי 100 מהנדרש, מבלי
# שזה בולט ביחס לשווי המסלול הכולל אם המסלול גדול מספיק). בדיקה יחסית
# עמידה-למגיש: חשיפה נוציונלית אמיתית של חוזה ממונף היא בד"כ כפולה סבירה
# (לא יותר מפי ~75) מהשווי ההוגן (המרווח) שאותה שורה בדיוק מדווחת - שיעורי
# מרג'ין סטנדרטיים לחוזי מדד/ריבית נעים בד"כ 1%-15% מהנוציונל. חריגה מכך
# היא סימן חזק שקנה המידה של יחידות/מחיר בשורה הזו שונה ממה שהנוסחה מניחה.
LEVERAGE_CAP = 75.0

FUTURES_CATEGORY = "חוזים עתידיים"
SWAP_CATEGORY = "לא סחיר נגזרים אחרים"
DERIVATIVE_CATEGORIES = (FUTURES_CATEGORY, SWAP_CATEGORY)

FUT_UNITS_COL = "ערך נקוב (יחידות)"
FUT_FX_COL = "שער חליפין"
FUT_PRICE_COL = "שער נייר הערך"
FUT_CURRENCY_COL = "מטבע פעילות"

SWAP_LEGS = (
    {"units": "ערך נקוב (רגל 1)", "fx": "שער חליפין (רגל 1)", "currency": "מטבע פעילות (רגל 1)"},
    {"units": "ערך נקוב (רגל 2)", "fx": "שער חליפין (רגל 2)", "currency": "מטבע פעילות (רגל 2)"},
)
SWAP_UNDERLYING_PRICE_COL = "שער נכס הבסיס במועד ההתקשרות בעסקה"
# שם העמודה עצמו (לפי החוזר: שער החליפין/נכס הבסיס לנגזרים לא סחירים מוצג
# "נכון למועד ההתקשרות בעסקה") מאשר שזהו מחיר נכס הבסיס *בפתיחת העסקה*, לא
# מחיר שוק עדכני - זה בדיוק ההסבר לכך שרגל1×מחיר זה שווה לרגל2 (שתי הרגליים
# נעולות לאותו נוציונל מקורי). מגבלה ידועה: לעסקת סוואפ ישנה שנפתחה הרבה
# לפני תאריך הדוח, החשיפה הכלכלית ה"חיה" (הנגזרת ממחיר השוק הנוכחי) עשויה
# לסטות מהנוציונל המקורי הזה ככל שהשוק זז מאז ההתקשרות - אין בדוח עמודת
# "מחיר נוכחי" נפרדת לרגל 1 כדי לתקן זאת.

# JPY: נמצא בבדיקה שחלק מהמגישים רושמים את שער החליפין לפי מוסכמת "יחס ל-100
# יין" (כמו שער בנק ישראל ליין) במקום שער ליחידה - אותו קובץ/מגיש לא עקבי:
# ברוב השורות 0.018-ish (נכון), בחלקן 1.83-ish (פי 100, שגוי). השער האמיתי
# ליין תמיד נמוך בהרבה מ-1 - כל ערך מעל הסף הוא ודאי המוסכמה השגויה.
JPY_100_THRESHOLD = 0.5

# כל מטבע זר (לא ILS) עם שער חליפין קרוב ל-1.0 הוא בהכרח פלייסהולדר שגוי -
# אין מטבע שנסחר קרוב ל-1:1 מול ש"ח (נמצא בפועל: USD/EUR ברגל 1 של חלק
# מהמגישים, כשהשער האמיתי מדווח בעמודה אחרת - "שער הנגזר במועד ההתקשרות
# בעסקה" - שלא תמיד קיימת/עקבית מספיק כדי לסמוך עליה). מטפלים בזה לא
# בתיקון (אין ערך אמין להציב), אלא בפסילת הרגל - ממוצעים רק את הרגליים
# התקינות, ובלי אף רגל תקינה נופלים לשווי ההוגן הנטו כמו כל מקרה גבולי.
FOREIGN_FX_PLACEHOLDER_TOL = 0.01

# רגל-מימון סינתטית ("...Index התחייבות"): "שער נייר הערך" קבוע בדיוק על 100 -
# מוסכמת ערך-נקוב-100 כמו אג"ח (ראו bonds_rank/מניות: value = units*price/100),
# לא רמת מדד גולמית. יחידות בסדר גודל מיליונים + הנוסחה הרגילה (בלי /100)
# מייצרות חשיפה מנופחת פי 100 בדיוק - מזוהה לפי שער == 100.0 בדיוק.
PAR_QUOTED_PRICE = 100.0


def _normalize_fx(currency, fx: float | None) -> float | None:
    if fx is None:
        return None
    if currency == "JPY" and fx > JPY_100_THRESHOLD:
        return fx / 100
    if currency and currency != "ILS" and abs(fx - 1.0) < FOREIGN_FX_PLACEHOLDER_TOL:
        return None
    return fx


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
            fx = _normalize_fx(row.get(FUT_CURRENCY_COL), _num(row.get(FUT_FX_COL)))
            if price is not None and abs(price - PAR_QUOTED_PRICE) < 1e-6:
                price = price / 100  # רגל-מימון סינתטית במוסכמת ערך-נקוב-100, לא רמת מדד
            fv = _num(row.get(FAIR_VALUE_COL))
            fv_ratio = (fv / total) if fv is not None else None

            line_ratio = None
            if units is not None and price is not None and fx is not None:
                notional_thousands = units * price * fx / 1000  # לאלפי ש"ח, כמו שווי הוגן
                line_ratio = notional_thousands / total
                if fv_ratio is not None and abs(line_ratio) > LEVERAGE_CAP * abs(fv_ratio):
                    line_ratio = None  # קנה מידה לא סביר ביחס לשווי ההוגן של השורה עצמה
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                line_ratio = fv_ratio if fv_ratio is not None else 0.0
            sums[key] = sums.get(key, 0.0) + line_ratio
    return sums


def _swap_exposure(source: list[dict], total_assets: dict[str, float]) -> dict[str, float]:
    """נמצא בבדיקה בפועל (לא ניחוש): "ערך נקוב" (רגל 1) ו"ערך נקוב" (רגל 2)
    אינם תמיד באותה יחידת מידה. עבור "Unfunded Forward" (למשל פורוורד מט"ח)
    שתי הרגליים כבר סכום נקוב במטבע - קרובות זו לזו כצפוי. אבל עבור
    "Unfunded Swap" על מניות/מדדים (סוואפ תשואה-כוללת), רגל 1 היא כמות
    *יחידות גולמית* של נכס הבסיס (לא סכום נקוב), ורגל 2 היא כבר הסכום
    הנקוב הנכון. אומת ישירות מול reports/2026Q2/512065202_gm_0226.xlsx:
    על 542/542 שורות סוואפ-מניות, רגל1 × "שער נכס הבסיס במועד ההתקשרות
    בעסקה" (× שער חליפין רגל 1) שווה בדיוק לרגל 2 (עד כדי עיגול). לכן רגל 1
    צריכה הכפלה בשער נכס הבסיס כדי להיות ברת-השוואה לרגל 2 - לא נוסחת
    ה-units×fx הרגילה שמשמשת לכל שאר הקטגוריות. אין דגל מפורש בדוח שמבחין
    בין "Unfunded Swap" ל"Unfunded Forward", ולכן הבחירה אדפטיבית לכל שורה:
    בין הפרשנות הגולמית לפרשנות המוכפלת-במחיר לרגל 1, נבחרת זו שקרובה יותר
    לרגל 2 (שנמצא בפועל שהיא תמיד כבר תקינה).

    גם אחרי התיקון הזה, נמצא בפועל שחלק מהמגישים רושמים את "שער נכס הבסיס"
    בקנה מידה שגוי (למשל פי ~100, אותה תבנית תקלה כמו JPY/ערך-נקוב-100
    בחוזים עתידיים) - לא עקבי אפילו בתוך אותה קרן/טיקר. מטופל באותו עקרון
    LEVERAGE_CAP שכבר קיים לחוזים עתידיים: משווים את החשיפה הנוציונלית
    שהתקבלה לשווי ההוגן נטו שאותה שורה בדיוק מדווחת - יחס גבוה מדי מסמן קנה
    מידה לא אמין, ונופלים לערך המדווח (PCT_COL) לשורה הזו בלבד. תקרת
    ה-SANITY_CAP הקיימת (ברמת שורה) ותקרת מסלול נוספת (סכום מצטבר על פני כל
    שורות ה-swap במסלול) נשארות כרשת ביטחון אחרונה."""
    notional_sums: dict[str, float] = {}
    fv_sums: dict[str, float] = {}
    leg1_col, leg2_col = SWAP_LEGS
    for rec in source:
        if rec["Category"] != SWAP_CATEGORY or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            total = total_assets.get(key) if key is not None else None
            if not total:
                continue
            # ה-fallback (כשקנה המידה לא אמין) משתמש בעמודת האחוז כפי שהדוח
            # עצמו מדווח - נמצא בפועל מדויק יותר מ-fv/total_assets_by_key
            # (שהאומדן שלה לשווי הכולל לא תמיד מתאים בדיוק לאומדן הדוח עצמו
            # לכל שורה בנפרד).
            row_pct = to_ratio(row.get(PCT_COL)) or 0.0
            fv_sums[key] = fv_sums.get(key, 0.0) + row_pct

            units1 = _num(row.get(leg1_col["units"]))
            fx1 = _normalize_fx(row.get(leg1_col["currency"]), _num(row.get(leg1_col["fx"])))
            units2 = _num(row.get(leg2_col["units"]))
            fx2 = _normalize_fx(row.get(leg2_col["currency"]), _num(row.get(leg2_col["fx"])))
            price = _num(row.get(SWAP_UNDERLYING_PRICE_COL))

            leg2_val = abs(units2 * fx2) / 1000 if units2 is not None and fx2 is not None else None
            leg1_raw = abs(units1 * fx1) / 1000 if units1 is not None and fx1 is not None else None
            leg1_priced = (abs(units1 * fx1 * price) / 1000
                            if units1 is not None and fx1 is not None and price is not None else None)

            leg1_val = leg1_raw
            if leg1_priced is not None and (
                leg1_raw is None or leg2_val is None
                or abs(leg1_priced - leg2_val) < abs(leg1_raw - leg2_val)
            ):
                leg1_val = leg1_priced

            candidates = [v for v in (leg1_val, leg2_val) if v is not None]
            line_ratio = None
            if candidates:
                notional_thousands = sum(candidates) / len(candidates)
                line_ratio = notional_thousands / total

                fv = _num(row.get(SWAP_NET_FAIR_VALUE_COL))
                fv_ratio = (fv / total) if fv is not None else None
                if fv_ratio is not None and abs(line_ratio) > LEVERAGE_CAP * abs(fv_ratio):
                    line_ratio = None  # קנה מידה לא סביר ביחס לשווי ההוגן של השורה עצמה
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                line_ratio = row_pct
            notional_sums[key] = notional_sums.get(key, 0.0) + line_ratio

    return {
        key: val if abs(val) <= SANITY_CAP else fv_sums.get(key, 0.0)
        for key, val in notional_sums.items()
    }


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
