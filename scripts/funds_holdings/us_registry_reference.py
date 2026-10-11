"""רישום הקרנות האמריקאיות של revach (data/funds_us/*.json, נבנה מרשימות SEC מסודרות בלבד) כמקור
הסיווג של קרנות "חוץ" עם ISIN אמריקאי - לפני כל ניחוש משם הקרן.

למה: classify_from_report_names / classify_from_registry_names מסיקות מניות/אג"ח ממילות מפתח בשם
("equity", "bond", "msci"...) - שביר: שם קצוץ, שם שלא מכיל מונח, קרן עם שם מטעה. הרישום נבנה
ללא שום הסקה משם:
  * ISIN -> קרן: fund_class.json (ISIN מרשימות SEC / סיווג הבורסה), רק כשה-ISIN שייך לקרן אחת;
    ISIN שמופיע בכמה קרנות - לא נכנס (דו-משמעי, אין ניחוש).
  * חשיפה למניות/אג"ח: fund_exposure.json (N-PORT: החזקות פיזיות + נגזרים, אותה שיטה כמו
    data/ETF/SEC/etf_exposure.json) - רק כשיש דוח N-PORT לקרן וסוג הנכס אינו "Unknown".
  * ממונפת / הפוכה: fund_series.json style = leveraged_inverse (דגל N-CEN C.3) - במקום regex על השם.

כשל רשת / PAT חסר - מחזיר ריק (השכבות הקיימות ממשיכות כמו קודם).

בדיקה עצמית (בלי רשת):  python -m scripts.funds_holdings.us_registry_reference
"""
from __future__ import annotations

import os
from collections import defaultdict

BASE_URL = "https://api.github.com/repos/Revach123/revach/contents/data/funds_us/"
TOKEN_ENV = "PAT"
UNKNOWN_ASSET_CLASS = "Unknown"   # אין הרכב מוכר (דוח חסר/לא פענוח) - לא נרשם


def _fetch_json(name: str, session) -> dict:
    token = (os.environ.get(TOKEN_ENV) or "").strip()
    r = session.get(BASE_URL + name, headers={"Authorization": f"Bearer {token}",
                                              "Accept": "application/vnd.github.raw"}, timeout=180)
    r.raise_for_status()
    return r.json()


def fetch_us_registry(session=None) -> dict:
    """{"class": fund_class, "series": fund_series, "exposure": fund_exposure}; {} אם לא זמין."""
    if not (os.environ.get(TOKEN_ENV) or "").strip():
        print("[us_registry] PAT לא מוגדר - מדלג על הרישום האמריקאי")
        return {}
    try:
        import requests
        s = session or requests.Session()
        out = {"class": _fetch_json("fund_class.json", s), "series": _fetch_json("fund_series.json", s),
               "exposure": _fetch_json("fund_exposure.json", s)}
    except Exception as e:  # רשת / מכסה - לא מפיל את הפייפליין
        print(f"[us_registry] הרישום לא זמין (מדלג): {e}")
        return {}
    print(f"[us_registry] {len(out['class'])} מחלקות, {len(out['series'])} סדרות, {len(out['exposure'])} חשיפות")
    return out


def _isin_to_fund(registry: dict) -> dict[str, str]:
    """ISIN -> fund_key, רק ISIN שמצביע על קרן אחת."""
    owners: dict[str, set[str]] = defaultdict(set)
    for c in (registry.get("class") or {}).values():
        isin = str(c.get("isin") or "").strip().upper()
        if isin and c.get("fund_key"):
            owners[isin].add(c["fund_key"])
    return {isin: next(iter(keys)) for isin, keys in owners.items() if len(keys) == 1}


def registry_fractions(registry: dict) -> dict[str, dict[str, float]]:
    """ISIN -> {"equity", "bond"[, "synth"]} באותו פורמט כמו build_isin_fractions (שברים 0..1; ממונפת > 1)."""
    out: dict[str, dict[str, float]] = {}
    exposure = registry.get("exposure") or {}
    for isin, key in _isin_to_fund(registry).items():
        e = exposure.get(key)
        if not e or e.get("asset_class") == UNKNOWN_ASSET_CLASS:
            continue
        eq, bd = e.get("eq_total_pct"), e.get("bond_total_pct")
        if eq is None and bd is None:
            continue
        frac = {"equity": (eq or 0.0) / 100, "bond": (bd or 0.0) / 100}
        if (e.get("eq_synth_pct") or 0) > 0:
            frac["synth"] = e["eq_synth_pct"] / 100   # מניות דרך נגזרים; האג"ח הן בטוחה (כמו ב-sec_exposure)
        out[isin] = frac
    return out


def registry_isins(registry: dict) -> set[str]:
    """כל ה-ISIN שהרישום מכיר (חד-משמעית), גם בלי חשיפה."""
    return set(_isin_to_fund(registry))


LEVERAGED_EQ_PCT = 150.0   # חשיפה למניות של פי 1.5 ומעלה (N-PORT, כולל נגזרים) = ממונפת בפועל; MAGS (109%) לא


def registry_leveraged_isins(registry: dict) -> set[str]:
    """ISIN של קרנות ממונפות/הפוכות, בלי שם: דגל N-CEN (style = leveraged_inverse), או חשיפה מדווחת
    של פי 1.5+ למניות ב-N-PORT (ממונפת יחידנית כמו קרנות 2X על מניה בודדת - לא מסומנת כמדד הפוך)."""
    series, exposure = registry.get("series") or {}, registry.get("exposure") or {}
    out = set()
    for isin, key in _isin_to_fund(registry).items():
        if (series.get(key) or {}).get("style") == "leveraged_inverse" or \
                ((exposure.get(key) or {}).get("eq_total_pct") or 0.0) >= LEVERAGED_EQ_PCT:
            out.add(isin)
    return out


def self_test() -> None:
    reg = {
        "class": {"C1": {"isin": "US0000000011", "fund_key": "S1"}, "C2": {"isin": "us0000000029", "fund_key": "S2"},
                  "C3": {"isin": "US0000000037", "fund_key": "S3"}, "C4": {"isin": "US0000000037", "fund_key": "S4"},
                  "C5": {"isin": "US0000000045", "fund_key": "S5"}, "C6": {"isin": "", "fund_key": "S6"},
                  "C7": {"isin": "US0000000052", "fund_key": "S6"}, "C8": {"isin": "US0000000060", "fund_key": "S7"}},
        "series": {"S2": {"style": "leveraged_inverse"}, "S1": {"style": "index"}},
        "exposure": {"S1": {"asset_class": "Equity", "eq_total_pct": 99.9, "bond_total_pct": 0.0, "eq_synth_pct": 0.0},
                     "S2": {"asset_class": "Equity", "eq_total_pct": 200.0, "bond_total_pct": 0.0, "eq_synth_pct": 150.0},
                     "S3": {"asset_class": "Equity", "eq_total_pct": 100.0, "bond_total_pct": 0.0},
                     "S4": {"asset_class": "Bonds", "eq_total_pct": 0.0, "bond_total_pct": 99.0},
                     "S5": {"asset_class": "Unknown", "eq_total_pct": 0.0, "bond_total_pct": 0.0},
                     "S6": {"asset_class": "Equity", "eq_total_pct": 109.0, "bond_total_pct": 53.0, "eq_synth_pct": 66.0},
                     "S7": {"asset_class": "Equity", "eq_total_pct": 198.0, "bond_total_pct": 0.0, "eq_synth_pct": 98.0}},
    }
    fr = registry_fractions(reg)
    assert abs(fr["US0000000011"]["equity"] - 0.999) < 1e-9 and fr["US0000000011"]["bond"] == 0.0, fr
    assert fr["US0000000029"]["equity"] == 2.0 and fr["US0000000029"]["synth"] == 1.5, fr      # ISIN באותיות קטנות
    assert "US0000000037" not in fr, "ISIN דו-משמעי (שתי קרנות) לא נכנס"
    assert "US0000000045" not in fr, "Unknown לא נרשם"
    # S2: דגל N-CEN; S7: חשיפה 198% (2X בלי דגל); S6 (MAGS, 109%) אינה ממונפת
    assert registry_leveraged_isins(reg) == {"US0000000029", "US0000000060"}, registry_leveraged_isins(reg)
    assert "US0000000037" not in registry_isins(reg) and "US0000000045" in registry_isins(reg)
    print("us_registry_reference: self-test OK")


if __name__ == "__main__":
    self_test()
