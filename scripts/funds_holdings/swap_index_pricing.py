"""מחיר מדד עדכני (נכון לתאריך הדוח, לא לתאריך פתיחת העסקה) לעסקאות סוואפ על
מדדי מניות, דרך revach123/INDICES (ריפו נפרד שמושך מדי יום מחירי מדדים
מ-Yahoo Finance - ר' README שם). נמצא בבדיקה בפועל (לא הנחה): "שער נכס הבסיס
במועד ההתקשרות בעסקה" בגיליון "לא סחיר נגזרים אחרים" הוא, כפי ששמו מרמז,
מחיר *בפתיחת* העסקה - לחשיפה נכונה ליום הדוח צריך את מחיר המדד *נכון לאותו
יום*, לא את המחיר ההיסטורי הזה.

מקור הטיקר: עמודת "טיקר" באותו גיליון (סוג הנכס=="מניות לרבות מדדי מניות").
המיפוי טיקר-סוואפ -> index_id ב-INDICES (data/swap_ticker_map.csv) נבנה
מסריקה מלאה של הארכיון בפועל (ר' commit ב-INDICES) - לא כל טיקר ממופה:
חלק (בעיקר סלים קנייניים של גופ בנקאי בודד - Goldman/JPM/Citi/Merrill,
עם קידומת GS*/JP*/CGAS*/MLBL*) אין להם מקור נתונים ציבורי בעליל, ומסומנים
במפורש ככאלה (index_id ריק + סיבה) - לא "עדיין לא נבדק".

כשל רשת/מיפוי חסר -> None (לא זריקת חריגה) - הקוד הקורא נופל בחזרה
לשיטת "שער נכס הבסיס במועד ההתקשרות" הקיימת.

אזהרה קריטית (נמצאה בבדיקה בפועל - MAE הורע, לא רק "לא השתפר", אחרי מעבר
ל-ETF-ים): index_id ב-swap_ticker_map.csv (INDICES) חייב להיות טיקר ברמת
מדד (Yahoo instrumentType=="INDEX"), לא מחיר יחידת ETF - גם אם ה-ETF
"מצטבר"/Acc ועוקב TR נאמנה. הקוד כאן מציב את המחיר ישירות בנוסחת
units×price שמניחה קנה-מידה זהה לרמת המדד עצמו (למשל Nasdaq-100 ~25,000
נקודות) - מחיר יחידת ETF (למשל ~1,755$) הוא בקנה-מידה שרירותי לגמרי, לא
פרופורציונלי לרמת המדד, ומייצר חשיפה שגויה בסדרי גודל בלי שה-LEVERAGE_CAP
ב-derivatives_exposure.py בהכרח תופס זאת. ר' README ב-INDICES לפירוט.
"""
import csv
import io
import re
from datetime import date, datetime
from functools import lru_cache

import requests

RAW_BASE = "https://raw.githubusercontent.com/Revach123/INDICES/main"
TICKER_MAP_URL = f"{RAW_BASE}/data/swap_ticker_map.csv"
PRICE_URL_TMPL = f"{RAW_BASE}/data/prices/{{index_id}}.csv"
TIMEOUT = 20

_SUFFIX_INDEX_EQUITY = re.compile(r"\s+(INDEX|EQUITY)$")
_SUFFIX_TRAILING_NUMBER = re.compile(r"\s+[0-9][0-9.,]*$")


def normalize_ticker(raw: str | None) -> str | None:
    """אותה נרמול שהופעל בזמן בניית swap_ticker_map.csv - חובה להיות זהה,
    אחרת המפתח לא יתאים לטבלת המיפוי."""
    if not raw:
        return None
    t = str(raw).strip().upper().replace("_X000D_", " ").replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = _SUFFIX_INDEX_EQUITY.sub("", t)
    t = _SUFFIX_TRAILING_NUMBER.sub("", t)
    return t or None


@lru_cache(maxsize=1)
def _load_ticker_map() -> dict[str, str]:
    r = requests.get(TICKER_MAP_URL, timeout=TIMEOUT)
    r.raise_for_status()
    out: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        index_id = (row.get("index_id") or "").strip()
        ticker = (row.get("swap_ticker") or "").strip().upper()
        if ticker and index_id:
            out[ticker] = index_id
    return out


@lru_cache(maxsize=64)
def _load_index_prices(index_id: str) -> tuple[tuple[date, float], ...]:
    r = requests.get(PRICE_URL_TMPL.format(index_id=index_id), timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            c = float(row["close"])
        except (ValueError, KeyError, TypeError):
            continue
        out.append((d, c))
    out.sort()
    return tuple(out)


def price_as_of(index_id: str, as_of: date) -> float | None:
    """מחיר הסגירה האחרון הידוע עד (וכולל) as_of. None אם אין מחיר במאגר
    לפני as_of, או שאין בכלל היסטוריה למדד הזה (רשת נכשלה/index_id שגוי)."""
    try:
        bars = _load_index_prices(index_id)
    except Exception:
        return None
    best = None
    for d, close in bars:
        if d > as_of:
            break
        best = close
    return best


def resolve_current_price(raw_ticker: str | None, report_date: date | None) -> tuple[float | None, str | None]:
    """(מחיר מדד עדכני נכון ל-report_date, index_id שנמצא) - (None, None) אם
    הטיקר לא ממופה, אין תאריך דוח, או שכשלה גישת הרשת. לא זורק."""
    if not report_date:
        return None, None
    key = normalize_ticker(raw_ticker)
    if not key:
        return None, None
    try:
        index_id = _load_ticker_map().get(key)
    except Exception:
        return None, None
    if not index_id:
        return None, None
    return price_as_of(index_id, report_date), index_id
