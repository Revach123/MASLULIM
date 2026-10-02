"""סיווג קרנות "חוץ" למניות/אג"ח - כל השכבות לפי סדר, משותף ל-main ול-validate_equity_exposure.

1. מאגרים קבועים: אוניברסיטת ה-ETF של revach + חשיפת SEC (build_isin_fractions).
2. השם בדוח (classify_from_report_names) והשם הרשמי במאגרים (classify_from_registry_names).
3. שכבות רשת על מה שחסר: SEC N-PORT חי, Yahoo/Morningstar, OpenFIGI (שם מלא / סוג נייר).
4. מטמון שכבות הרשת: Yahoo/OpenFIGI נכשלים חלקית בכל ריצה (חסימה / מגבלת קצב), וקרן שסווגה
   אתמול נשארת היום בלי סיווג - בדף היא קופצת בין "מניות" ל"קרנות נאמנות". תוצאה טרייה תמיד
   קודמת; מה שנכשל בריצה הזו נלקח מהמטמון (FUND_CLASS_CACHE, נשמר ב-actions/cache).
5. תיקון ISIN עם טעות בקידומת (repair_isin_typos) ונרמול שבר מניות > 1 (sanitize_fractions).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .foreign_etf_reference import (
    build_isin_fractions, classify_from_registry_names, classify_from_report_names, classify_via_openfigi_names,
    collect_unclassified_foreign_isins, fetch_etf_universe, fetch_sec_etf_exposure, fetch_us_security_names,
    official_fund_names, repair_isin_typos, sanitize_fractions,
)

CACHE_PATH = Path(os.environ.get("FUND_CLASS_CACHE") or ".cache/fund_classification.json")


def _load_cache(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(path: Path, cache: dict[str, dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except OSError as e:
        print(f"[fund_class] שמירת המטמון נכשלה: {e}")


def _online_layers():
    def nport(missing):
        from .sec_nport_reference import build_isin_fractions_via_nport
        return build_isin_fractions_via_nport(missing)

    def yahoo(missing):
        from .yahoo_fund_reference import build_isin_fractions_via_yahoo
        return build_isin_fractions_via_yahoo(missing)

    return (("N-PORT חי", nport), ("Yahoo/Morningstar", yahoo), ("OpenFIGI", classify_via_openfigi_names))


def build_foreign_fractions(source: list[dict], funds: list[dict], tag: str, cache_path: Path = CACHE_PATH):
    """-> (isin_fractions, etf_universe, sec_exposure, official_names)."""
    etf_universe = fetch_etf_universe()
    sec_exposure = fetch_sec_etf_exposure()
    official_names = official_fund_names(etf_universe, sec_exposure, fetch_us_security_names())
    isin_fractions = build_isin_fractions(etf_universe, sec_exposure)
    for isin, frac in classify_from_report_names(source).items():
        isin_fractions.setdefault(isin, frac)
    missing = collect_unclassified_foreign_isins(funds, isin_fractions)
    for isin, frac in classify_from_registry_names(missing, official_names).items():
        isin_fractions.setdefault(isin, frac)
    print(f"[{tag}] {len(isin_fractions)} ISIN מסווגים (ETF זרות: אירופה+SEC+שם בדוח+שם רשמי)")

    online: dict[str, dict] = {}
    for label, layer in _online_layers():
        missing = collect_unclassified_foreign_isins(funds, isin_fractions)
        try:
            res = layer(missing) if missing else {}
        except Exception as e:  # רשת - לא מפיל את הפייפליין
            print(f"[{tag}] שכבת {label} נכשלה (מדלג): {e}")
            res = {}
        for isin, frac in res.items():
            if isin not in isin_fractions:
                isin_fractions[isin] = online[isin] = frac
        print(f"[{tag}] {len(isin_fractions)} ISIN מסווגים סה\"כ (+{label})")

    cache = _load_cache(cache_path)
    from_cache = 0
    for isin in collect_unclassified_foreign_isins(funds, isin_fractions):
        if isin in cache:
            isin_fractions[isin] = cache[isin]
            from_cache += 1
    cache.update(online)
    _save_cache(cache_path, cache)
    print(f"[{tag}] מטמון שכבות רשת: {from_cache} ISIN מהמטמון (נכשלו בריצה הזו), "
          f"{len(online)} עודכנו, {len(cache)} במטמון")

    repaired = repair_isin_typos(funds, isin_fractions)
    for bad, good in repaired.items():
        if good in official_names:
            official_names.setdefault(bad, official_names[good])
    print(f"[{tag}] {len(repaired)} ISIN עם טעות בקידומת המדינה (ספרת ביקורת) - סווגו לפי המתוקן: {repaired}")
    fixed = sanitize_fractions(isin_fractions, source)
    print(f"[{tag}] {len(fixed)} ISIN עם שבר מניות > 1 בקרן לא ממונפת - נורמלו: {fixed[:10]}")
    return isin_fractions, etf_universe, sec_exposure, official_names
