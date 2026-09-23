"""ריבית: האם למסלול יש חשיפה לריבית ממזומן ו/או מפיקדונות.

מקור: Autopilot_Section1.m, שאילתת ריבית.
שינוי מכוון (לפי הנחיית המשתמש): ב-M יש פיבוט לשתי עמודות נפרדות
("ריבית ממזומן", "ריבית מפקדונות"). כאן, לטבלה הראשית, שתי העמודות
מאוחדות לעמודה אחת - "ריבית" - שערכה "ריבית" אם יש ריבית בכל אחד
מהשניים (Category = מזומנים ושווי מזומנים או פיקדונות מעל 3 חודשים),
אחרת None.
"""
from .excel_io import text_from

CASH_CATEGORY = "מזומנים ושווי מזומנים"
DEPOSITS_CATEGORY = "פיקדונות מעל 3 חודשים"
INTEREST_CATEGORIES = {CASH_CATEGORY, DEPOSITS_CATEGORY}


def _rate_num(v):
    """try Number.From(...) otherwise null."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_interest(source: list[dict]) -> dict[str, bool]:
    """מפתח -> True אם יש ריבית (ממזומן ו/או מפקדונות), אחרת המפתח לא ברשימה.

    Table.Group ב-M מקבץ לפי (מפתח, מידע, Category) ובודק אם יש ריבית לא-אפסית
    בתוך הקבוצה (List.AnyTrue). כאן: מקבצים ישירות לפי מפתח בלבד, על שני
    ה-Category יחד, כי התוצאה הסופית מאוחדת לעמודה אחת ממילא.
    """
    has_interest: dict[str, bool] = {}
    for rec in source:
        if rec["Category"] not in INTEREST_CATEGORIES or rec["מידע"] != "מידע":
            continue
        legal_id = rec["LegalId"]
        for row in rec["Clean"]:
            track = row.get("מספר מסלול")
            if track is None or track == "":
                continue
            key = f"{legal_id}_{text_from(track)}"
            rate = _rate_num(row.get("שיעור ריבית"))
            if rate is not None and rate != 0:
                has_interest[key] = True
            else:
                has_interest.setdefault(key, False)
    return has_interest
