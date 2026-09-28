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
תקינים. מסלול עם סכום זעיר-מדי (מתחת ל-MIN_RELIABLE_TOTAL) לא מנורמל -
אין מספיק אות כדי לסמוך על מכפיל ענק (למשל פי 30,000).

רץ פעם אחת ישירות אחרי build_source(), *לפני* כל צרכן (כולם קוראים
PCT_COL מחדש מה-source בכל פעם) - מעדכן את source במקום (in-place),
כך שכל הצרכנים מקבלים את הערך המנורמל אוטומטית, בלי לשנות אותם."""
from collections import defaultdict

from .excel_io import to_ratio
from .sheet_source import PCT_COL

# מעל הסף הזה נחשב "כבר תקין" (מוסכמת %-של-המסלול-עצמו) - לא מנורמלים,
# כדי לא לגעת ב-99.96%-127% התקינים שנמצאו בפועל (רעש טבעי סביב 100%).
RESCALE_BELOW = 0.9

# מתחת לסף הזה אין מספיק אות כדי לסמוך על מכפיל (עד פי 1/MIN = 1000) -
# משאירים כמו שהוא (מסלול כזה כנראה חסר-נתונים אמיתי, לא רק בקנה מידה שגוי).
MIN_RELIABLE_TOTAL = 0.001


def normalize_track_pct(source: list[dict]) -> dict[str, float]:
    """מנרמל את source במקום, מחזיר {מפתח: מכפיל} למסלולים שתוקנו (לשקיפות)."""
    totals: dict[str, float] = defaultdict(float)
    rows_by_key: dict[str, list[dict]] = defaultdict(list)
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            if key is None:
                continue
            pct = to_ratio(row.get(PCT_COL))
            if pct is None:
                continue
            totals[key] += pct
            rows_by_key[key].append(row)

    scale_by_key: dict[str, float] = {}
    for key, total in totals.items():
        if not (MIN_RELIABLE_TOTAL <= total < RESCALE_BELOW):
            continue
        scale = 1.0 / total
        scale_by_key[key] = scale
        for row in rows_by_key[key]:
            raw = to_ratio(row.get(PCT_COL))
            if raw is not None:
                row[PCT_COL] = raw * scale

    return scale_by_key
