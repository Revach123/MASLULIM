"""קרנות IL: פיבוט אחוז השקעה לפי סיווג (קרן מחקה - סיווג ראשי), לכל מסלול.

מקור: Autopilot_Section1.m, שאילתת קרנות IL.
"""
from .excel_io import text_from, to_ratio
from .funds_classification import fund_siveg

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
