"""שכבת הגנה: "שיעור מסך נכסי ההשקעה" אמור להיות % מנכסי *המסלול עצמו*
(מסתכם ל-100% לכל מסלול על פני כל הגיליונות) - זו ההנחה שכל שאר הקוד
(category_pct, derivatives_exposure, funds, interest, bonds_rank...) בונה
עליה. אומת בפועל על 183 מסלולים (512237744+512065202): סכום לכל מסלול
נע 99.96%-127%, חציון בדיוק 100% - ההנחה נכונה ברוב המכריע של המקרים.

אבל: נמצא בבדיקה בפועל (514956465/מור) שלא כל החברות מדווחות לפי המוסכמה
הזו - שם השדה מדווח % *מכל נכסי הקובץ* (כל המסלולים ביחד), לא % מהמסלול:
514956465_gm_0226.xlsx מסתכם בדיוק ל-100% על פני *כל* 49 המסלולים יחד
(לא 49*100%). התוצאה: מסלול קטן יחסית בחברה כזו מקבל % זעיר (למשל 0.15%
למסלול "עוקב מדדי מניות" עם אחזקות מניות/קרנות/חוזים אמיתיות ומלאות)
בכל חישוב במורד הזרם, למרות שהוא בכלל לא "חסר" - הנתונים שם, רק בקנה
מידה שגוי.

התיקון: לכל מסלול, מסכמים את "שיעור מסך נכסי ההשקעה" על פני כל השורות
שלו (כל הקטגוריות) ב-source. אם הסכום רחוק משמעותית מ-100% (מתחת ל-
RESCALE_BELOW), מניחים שזו מוסכמת "% מכל הקובץ" ומכפילים כל שורה של
אותו מסלול ב-1/סכום (בדיוק ההצעה: "אם סך נכסים מגיע ל-0.5%, להכפיל הכל
ב-200") - כך שסך המסלול חוזר ל-100% בדיוק, בלי לגעת במסלולים שכבר
תקינים. מסלול עם סכום זעיר-מדי (מתחת ל-MIN_RELIABLE_TOTAL) לא מנורמל
לפי האות העצמי-שלו-בלבד - אין מספיק אות כדי לסמוך על מכפיל ענק (למשל
פי 30,000) רק מהמסלול עצמו.

שכבת-אות חזקה יותר, ברמת הקובץ (נמצא בפועל, לא ניחוש - 514956465_gm):
אם *כל* המסלולים באותו קובץ (CompanyType - למשל "514956465_gm", מ-
build_source) מסתכמים יחד לבדיוק ~100% (FILE_TOTAL_TOLERANCE), זה אישוש
חד-משמעי שהקובץ כולו נכתב במוסכמת %-מהקובץ - וכשקיים אישוש כזה, מנרמלים
את *כל* מסלולי אותו קובץ (כולל כאלה עם סכום-עצמי זעיר-מתחת-ל-
MIN_RELIABLE_TOTAL) לפי אותו מכפיל 1/סכום-המסלול, בלי לחשוש מ"אין מספיק
אות" - האות כבר לא מגיע מהמסלול הבודד אלא מ-49 מסלולים יחד. אומת בפועל:
514956465_gm_0226.xlsx מסתכם 99.99999...% על פני 49 מסלולים, כשחלקם
(15881/15883/15882) לבד מתחת ל-0.02% - קודם לא טופלו כלל, עכשיו כן.
קובץ שלא מגיע לאישוש כזה (לדוגמה 514956465_pn_0226.xlsx, שמסתכם 561.76% -
מוסכמה שלישית לא-מזוהה) ממשיך להתנהג בדיוק כמו קודם (רק בדיקת-האות-
העצמית של המסלול הבודד).

רץ פעם אחת ישירות אחרי build_source(), *לפני* כל צרכן (כולם קוראים
PCT_COL מחדש מה-source בכל פעם) - מעדכן את source במקום (in-place),
כך שכל הצרכנים מקבלים את הערך המנורמל אוטומטית, בלי לשנות אותם."""
from collections import defaultdict

from .excel_io import to_ratio
from .sheet_source import PCT_COL

# מעל הסף הזה נחשב "כבר תקין" (מוסכמת %-של-המסלול-עצמו) - לא מנורמלים,
# כדי לא לגעת ב-99.96%-127% התקינים שנמצאו בפועל (רעש טבעי סביב 100%).
RESCALE_BELOW = 0.9

# מעל הסף הזה - הדוח סופר חלק מהנכסים פעמיים (מגדל פנסיה/ביטוח: "אפיק השקעה מובטח
# תשואה" לצד "לא סחיר איגרות חוב מיועדות", סכום 110%-121%), והנתון הרשמי מחושב
# ממכנה של 100%. נמדד על כל המסלולים (CI, dump לכל מסלול): 22 מסלולים מעל 105%,
# MAE מול הרשמי שלהם 7.85 -> 3.35 נק' אחוז אחרי נרמול ל-100%.
RESCALE_ABOVE = 1.05

# מתחת לסף הזה אין מספיק אות *עצמי* כדי לסמוך על מכפיל (עד פי 1/MIN =
# 1000) - לא חל על מסלול שבקובץ שלו יש אישוש ברמת-הקובץ (ר' למטה).
MIN_RELIABLE_TOTAL = 0.001

# טווח-סבילות לזיהוי "קובץ כולו במוסכמת %-מהקובץ": סכום כל המסלולים
# בקובץ קרוב ל-100% (לא בדיוק, ר' 99.99999...% בפועל - שגיאות עיגול).
FILE_TOTAL_TOLERANCE = 0.05

# "אפיק השקעה מובטח תשואה" (מנגנון השלמת המדינה לתשואת היעד בפנסיה, שהחליף את
# האג"ח המיועדות) - יש חברות שמדווחות את ה-% של שכבות האפיק ממכנה אחר מזה של
# שאר שורות המסלול. נמצא בפועל (514956465/מור פנסיה): שכבות האפיק מסתכמות ל-52%-
# 99.7% מהמסלול, אבל שווי/% שלהן נותן מכנה קטן פי 3-1000 מזה של שאר השורות
# (אג"ח, מזומנים, קרנות - כולן עקביות ביניהן). המשקל האמיתי (שווי האפיק חלקי
# אותו מכנה) יוצא 27%-29%, כמו בשאר החברות, והנתון הרשמי מתיישב איתו: מסלול
# 13915 - 4.5% -> 70.1% מול 69.7% רשמי. אצל החברות האחרות (כלל, מגדל, הפניקס,
# אינפיניטי...) היחס בין המכנים 0.91-1.0, ולכן הן לא מושפעות.
GUARANTEED_CHANNEL_CATEGORY = "אפיק השקעה מובטח תשואה"
REBASE_RATIO_LOW, REBASE_RATIO_HIGH = 0.8, 1.25


def _value_k(row: dict) -> float | None:
    """שווי השורה באלפי ש"ח (שווי הוגן / שווי הנכסים באפיק), אם יש."""
    for col, v in row.items():
        if "שווי" in col and "אלפי" in col and isinstance(v, (int, float)):
            return float(v)
    return None


def rebase_guaranteed_channel(source: list[dict]) -> dict[str, float]:
    """מחשב מחדש את ה-% של שורות האפיק המובטח לפי המכנה של שאר שורות המסלול,
    כשהמכנה המשתמע (שווי/%) של האפיק לא עקבי איתו. מעדכן במקום, מחזיר
    {מפתח: המשקל החדש של האפיק לפני נרמול ל-100%}. רץ לפני הנרמול, שמחזיר את
    סך המסלול ל-100%."""
    ch_rows: dict[str, list[tuple[dict, float, float]]] = defaultdict(list)
    ref_v: dict[str, float] = defaultdict(float)
    ref_p: dict[str, float] = defaultdict(float)
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        is_channel = rec.get("Category") == GUARANTEED_CHANNEL_CATEGORY
        for row in rec["Clean"]:
            key = row.get("מפתח")
            pct = to_ratio(row.get(PCT_COL))
            value = _value_k(row)
            if key is None or pct is None or value is None:
                continue
            if is_channel:
                ch_rows[key].append((row, pct, value))
            elif pct:
                ref_v[key] += value
                ref_p[key] += pct

    rebased: dict[str, float] = {}
    for key, rows in ch_rows.items():
        ch_p = sum(p for _, p, _ in rows)
        ch_v = sum(v for _, _, v in rows)
        if ch_p <= 0 or ch_v <= 0 or ref_p[key] <= 0 or ref_v[key] <= 0:
            continue
        ref_base = ref_v[key] / ref_p[key]
        ratio = (ch_v / ch_p) / ref_base
        if REBASE_RATIO_LOW <= ratio <= REBASE_RATIO_HIGH:
            continue
        for row, _, value in rows:
            row[PCT_COL] = value / ref_base
        rebased[key] = ch_v / ref_base
    return rebased


def normalize_track_pct(source: list[dict]) -> dict[str, float]:
    """מנרמל את source במקום, מחזיר {מפתח: מכפיל} למסלולים שתוקנו (לשקיפות)."""
    rebase_guaranteed_channel(source)
    totals: dict[str, float] = defaultdict(float)
    rows_by_key: dict[str, list[dict]] = defaultdict(list)
    company_type_by_key: dict[str, str] = {}
    file_totals: dict[str, float] = defaultdict(float)
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        company_type = rec.get("CompanyType")
        for row in rec["Clean"]:
            key = row.get("מפתח")
            if key is None:
                continue
            pct = to_ratio(row.get(PCT_COL))
            if pct is None:
                continue
            totals[key] += pct
            rows_by_key[key].append(row)
            if company_type is not None:
                company_type_by_key.setdefault(key, company_type)
                file_totals[company_type] += pct

    confirmed_pct_of_file_types = {
        ct for ct, total in file_totals.items()
        if abs(total - 1.0) < FILE_TOTAL_TOLERANCE
    }

    scale_by_key: dict[str, float] = {}
    for key, total in totals.items():
        if total > RESCALE_ABOVE:
            scale = 1.0 / total
            scale_by_key[key] = scale
            for row in rows_by_key[key]:
                raw = to_ratio(row.get(PCT_COL))
                if raw is not None:
                    row[PCT_COL] = raw * scale
            continue
        if total <= 0 or total >= RESCALE_BELOW:
            continue
        file_confirmed = company_type_by_key.get(key) in confirmed_pct_of_file_types
        if not file_confirmed and total < MIN_RELIABLE_TOTAL:
            continue
        scale = 1.0 / total
        scale_by_key[key] = scale
        for row in rows_by_key[key]:
            raw = to_ratio(row.get(PCT_COL))
            if raw is not None:
                row[PCT_COL] = raw * scale

    return scale_by_key
