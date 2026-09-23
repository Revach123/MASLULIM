"""קרנות IL: פיבוט אחוז השקעה לפי סיווג (קרן מחקה - סיווג ראשי), לכל מסלול.

מקור: Autopilot_Section1.m, שאילתת קרנות IL.
"""
from .excel_io import text_from, to_ratio
from .funds_classification import fund_siveg
from .kashrut_rank import NO_KASHRUT, _RANK

PLACEHOLDER_PCT = {"", "ריק במקור", "סוף מידע"}


def _fund_number_key(v) -> str | None:
    """מנרמל מספר קרן ל-int-כמחרוזת, כדי להצליב בין קרנות (int) לנתוני קרנות (str)."""
    if v is None:
        return None
    try:
        return text_from(int(float(v)))
    except (TypeError, ValueError):
        return text_from(v)


def build_funds_il(funds: list[dict], funds_ref: list[dict]) -> dict[str, dict[str, float]]:
    """מפתח -> {סיווג: סכום שיעור}."""
    siveg_by_num: dict[str, str] = {}
    for r in funds_ref:
        k = _fund_number_key(r.get("מספר קרן"))
        if k is not None:
            siveg_by_num[k] = fund_siveg(r)

    sums: dict[str, dict[str, float]] = {}
    for row in funds:
        if row["סוג"] != "IL":
            continue
        raw_pct = row.get("שיעור מסך נכסי ההשקעה")
        if isinstance(raw_pct, str) and raw_pct in PLACEHOLDER_PCT:
            continue
        pct = to_ratio(raw_pct)
        if pct is None:
            continue
        siveg = siveg_by_num.get(_fund_number_key(row.get("מספר קרן")))
        if siveg is None:
            continue
        key = row["מפתח"]
        d = sums.setdefault(key, {})
        d[siveg] = d.get(siveg, 0.0) + pct

    return sums


def build_funds_il_kashrut(
    funds: list[dict], funds_ref: list[dict], kashrut_by_num: dict[str, str]
) -> dict[str, dict[str, str]]:
    """מפתח -> {סיווג: כשרות הכי-גרועה מבין קרנות ה-IL מאותו סיווג באותו מסלול}.

    שינוי מכוון (לפי הנחיית המשתמש): פירוט כשרות לכל עמודת אחוז-סיווג
    בנפרד, לא רק הכי-גרוע הכולל למסלול (kashrut_rank.build_track_kashrut).
    אותה קבוצת שורות בדיוק כמו build_funds_il (סוג=IL, אחוז תקין, סיווג
    מזוהה) - כדי שהכשרות תתאים לאותן הקרנות שסוכמו לאחוז.
    """
    siveg_by_num: dict[str, str] = {}
    for r in funds_ref:
        k = _fund_number_key(r.get("מספר קרן"))
        if k is not None:
            siveg_by_num[k] = fund_siveg(r)

    worst: dict[str, dict[str, str]] = {}
    for row in funds:
        if row["סוג"] != "IL":
            continue
        raw_pct = row.get("שיעור מסך נכסי ההשקעה")
        if isinstance(raw_pct, str) and raw_pct in PLACEHOLDER_PCT:
            continue
        if to_ratio(raw_pct) is None:
            continue
        num_key = _fund_number_key(row.get("מספר קרן"))
        siveg = siveg_by_num.get(num_key)
        if siveg is None:
            continue
        level = kashrut_by_num.get(num_key, NO_KASHRUT)
        key = row["מפתח"]
        d = worst.setdefault(key, {})
        cur = d.get(siveg)
        if cur is None or _RANK[level] > _RANK[cur]:
            d[siveg] = level

    return worst
