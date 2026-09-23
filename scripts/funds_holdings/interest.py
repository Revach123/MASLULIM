"""ריבית: האם למסלול יש חשיפה לריבית ממזומן/פיקדונות, מפוצלת לפי היתר עסקה.

מקור: Autopilot_Section1.m, שאילתת ריבית.
שינויים מכוונים (לפי הנחיית המשתמש):
  1. שתי העמודות המקוריות (ריבית ממזומן / ריבית מפקדונות) מאוחדות
     לבדיקה אחת "יש ריבית" (ממזומן ו/או מפקדונות, לא משנה מאיזה).
  2. אותה עמודה מפוצלת מחדש לשתיים - לפי אם לבנק שמחזיק את המזומן/
     הפיקדון יש היתר עסקה (HARAV_LEVIN, דינמי בכל הרצה) או לא.
     בנק זר, לא ידוע, או TBD (ר' bank_reference.csv) -> "אין היתר עסקה".
"""
import logging

from .bank_names import ALIASES as _KNOWN_NAMES
from .bank_names import load_bank_reference, resolve_bank
from .excel_io import text_from
from .heter_iska import STATUS_NONE
from . import heter_iska as heter_iska_module

logger = logging.getLogger(__name__)

CASH_CATEGORY = "מזומנים ושווי מזומנים"
DEPOSITS_CATEGORY = "פיקדונות מעל 3 חודשים"
INTEREST_CATEGORIES = {CASH_CATEGORY, DEPOSITS_CATEGORY}

COL_WITH_HETER = "ריבית - בנק עם היתר עסקה"
COL_WITHOUT_HETER = "ריבית - בנק בלי היתר עסקה"


def _rate_num(v):
    """try Number.From(...) otherwise null."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_interest(source: list[dict], heter_by_chp: dict[str, str] | None = None) -> dict[str, dict]:
    """מפתח -> {COL_WITH_HETER: bool|None, COL_WITHOUT_HETER: bool|None}.

    heter_by_chp: תוצאת heter_iska.build() (ניתנת כפרמטר כדי לאפשר בדיקה
    עם מוק, בלי לפגוע ב-API החי בכל הרצה של הפייפליין - נשלף פעם אחת).
    """
    if heter_by_chp is None:
        heter_by_chp = heter_iska_module.build()
    bank_ref = load_bank_reference()

    unmatched_names: set[str] = set()
    out: dict[str, dict] = {}

    for rec in source:
        if rec["Category"] not in INTEREST_CATEGORIES or rec["מידע"] != "מידע":
            continue
        legal_id = rec["LegalId"]
        for row in rec["Clean"]:
            track = row.get("מספר מסלול")
            if track is None or track == "":
                continue
            rate = _rate_num(row.get("שיעור ריבית"))
            if rate is None or rate == 0:
                continue  # אין ריבית בפועל בשורה הזו - לא רלוונטי לפיצול

            key = f"{legal_id}_{text_from(track)}"
            bank_name = row.get("שם הבנק")
            chp = resolve_bank(bank_name, bank_ref)
            has_heter = chp is not None and heter_by_chp.get(chp, STATUS_NONE) != STATUS_NONE

            if bank_name and bank_name not in _KNOWN_NAMES:
                unmatched_names.add(bank_name)

            d = out.setdefault(key, {COL_WITH_HETER: None, COL_WITHOUT_HETER: None})
            col = COL_WITH_HETER if has_heter else COL_WITHOUT_HETER
            d[col] = "ריבית"

    if unmatched_names:
        logger.warning("שמות בנק לא מזוהים (לא ב-ALIASES): %s", sorted(unmatched_names))

    return out
