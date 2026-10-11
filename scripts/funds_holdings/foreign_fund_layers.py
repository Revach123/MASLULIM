"""סיווג קרנות "חוץ" למניות/אג"ח - כל השכבות לפי סדר, משותף ל-main ול-validate_equity_exposure.

1. מאגרים קבועים: אוניברסיטת ה-ETF של revach + חשיפת SEC (build_isin_fractions).
1ב. הרישום האמריקאי של revach (us_registry_reference: רשימות SEC מסודרות, N-PORT, בלי הסקה משם) - קודם
   לכל סיווג לפי שם; לא דורס את שכבה 1.
2. השם בדוח (classify_from_report_names) והשם הרשמי במאגרים (classify_from_registry_names).
3. שכבות רשת על מה שחסר: SEC N-PORT חי, Yahoo/Morningstar, FT (קרנות נאמנות זרות - פילוח נכסים /
   קטגוריית Morningstar), OpenFIGI (שם מלא / סוג נייר).
4. מטמון שכבות הרשת: Yahoo/OpenFIGI נכשלים חלקית בכל ריצה (חסימה / מגבלת קצב), וקרן שסווגה
   אתמול נשארת היום בלי סיווג - בדף היא קופצת בין "מניות" ל"קרנות נאמנות". תוצאה טרייה תמיד
   קודמת; מה שנכשל בריצה הזו נלקח מהמטמון (FUND_CLASS_CACHE, נשמר ב-actions/cache).
5. מוצא אחרון - הסיווג שהגוף עצמו רשם בדוח ("סיווג הקרן" + "מאפיין עיקרי": Bond/Fixed Income Funds +
   אג"ח קונצרני -> אג"ח; Equity Funds / מניות בחו"ל / עוקב אחר מדדי מניות -> מניות), רק כשאין סתירה
   (ACC SICAV LI1165463954, LION III IE00B804LV55 - קרנות אג"ח שאינן באף מאגר).
6. תיקון ISIN עם טעות בקידומת (repair_isin_typos) ונרמול שבר מניות > 1 (sanitize_fractions).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from .us_registry_reference import fetch_us_registry, registry_fractions, registry_leveraged_isins
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


FUND_CLASS_COL, MAIN_TRAIT_COL = "סיווג הקרן", "מאפיין עיקרי"
_REPORT_EQUITY = re.compile(r'מניות|Equity Fund', re.IGNORECASE)
_REPORT_BOND = re.compile(r'אג"?ח|Bond|Fixed Income|Money Market|כספית', re.IGNORECASE)


_REPORT_OTHER = re.compile(r'Commodit|סחורות|Currency|מט"ח בלבד|Real Estate|נדל"ן', re.IGNORECASE)


def _report_class(row: dict) -> str | None:
    """"equity" / "bond" לפי שתי עמודות הסיווג של הדוח; "conflict" כשהן סותרות או מזכירות סחורות/מטבע/נדל"ן
    (Kijani Commodity: "Commodity Funds" + "מניות"); None כשאין הכרעה (Index Funds, אחר)."""
    found = set()
    for col in (FUND_CLASS_COL, MAIN_TRAIT_COL):
        v = str(row.get(col) or "")
        if _REPORT_OTHER.search(v):
            return "conflict"
        eq, bd = bool(_REPORT_EQUITY.search(v)), bool(_REPORT_BOND.search(v))
        if eq != bd:
            found.add("equity" if eq else "bond")
    if len(found) > 1:
        return "conflict"
    return next(iter(found)) if found else None


def _report_votes(source: list[dict], isins) -> dict[str, Counter]:
    want = {str(i).strip().upper() for i in isins}
    votes: dict[str, Counter] = {}
    for rec in source:
        if rec.get("Category") not in ("קרנות נאמנות", "קרנות סל"):
            continue
        for row in rec.get("Clean") or []:
            isin = str(row.get("מספר נייר ערך") or "").strip().upper()
            if isin in want:
                cls = _report_class(row)
                if cls:
                    votes.setdefault(isin, Counter())[cls] += 1
    return votes


def _decided(c: Counter, min_rows: int = 1) -> str | None:
    cls, n = c.most_common(1)[0]
    total = sum(c.values())
    return cls if cls != "conflict" and total >= min_rows and n >= 0.8 * total else None


def _frac(cls: str) -> dict[str, float]:
    return {"equity": 1.0, "bond": 0.0} if cls == "equity" else {"equity": 0.0, "bond": 1.0}


def classify_from_report_columns(source: list[dict], isins) -> dict[str, dict[str, float]]:
    """רוב השורות של אותו ISIN בכל הדוחות: הכרעה רק כש-80%+ מהשורות המכריעות/הסותרות מסכימות."""
    out = {}
    for isin, c in _report_votes(source, isins).items():
        cls = _decided(c)
        if cls:
            out[isin] = _frac(cls)
    return out


def report_overrides(source: list[dict], fractions: dict[str, dict[str, float]], strong: set[str]) -> dict[str, str]:
    """סיווג ממקור חלש (Yahoo / FT / OpenFIGI / שם / מטמון - לא אוניברסיטת ה-ETF / SEC) שסותר את סיווג הגוף
    בדוח (3+ שורות, 80%+ מסכימות): הדוח קובע. LO Funds Asia LU2332096192 - "מניות" 100% ממקור חלש, 38/38
    שורות בדוח: Bond/Fixed Income + אג"ח קונצרני."""
    weak = [i for i in fractions if i not in strong]
    out = {}
    for isin, c in _report_votes(source, weak).items():
        cls = _decided(c, min_rows=3)
        eq = fractions[isin].get("equity") or 0.0
        if cls == "bond" and eq > 0.5 or cls == "equity" and eq < 0.5 and not fractions[isin].get("stock"):
            fractions[isin] = _frac(cls)
            out[isin] = cls
    return out


def _online_layers():
    def nport(missing):
        from .sec_nport_reference import build_isin_fractions_via_nport
        return build_isin_fractions_via_nport(missing)

    def yahoo(missing):
        from .yahoo_fund_reference import build_isin_fractions_via_yahoo
        return build_isin_fractions_via_yahoo(missing)

    def ft(missing):
        from .ft_fund_reference import build_isin_fractions_via_ft
        return build_isin_fractions_via_ft(missing)

    return (("N-PORT חי", nport), ("Yahoo/Morningstar", yahoo), ("FT", ft), ("OpenFIGI", classify_via_openfigi_names))


def _side(frac: dict[str, float]) -> str:
    eq, bd = frac.get("equity") or 0.0, frac.get("bond") or 0.0
    return "equity" if eq > bd and eq >= 0.5 else "bond" if bd > eq and bd >= 0.5 else "other"


def _report_registry_vs_names(tag: str, reg_fractions: dict, by_report_name: dict, official_names: dict) -> None:
    """מדד לשבירות הסיווג לפי שם: ISIN שהרישום (N-PORT) והסיווג לפי שם הדוח חלוקים עליו."""
    both = [i for i in reg_fractions if i in by_report_name]
    diff = [i for i in both if _side(reg_fractions[i]) != _side(by_report_name[i])]
    print(f"[{tag}] רישום מול סיווג לפי שם הדוח: {len(both)} ISIN משותפים, {len(diff)} חלוקים"
          + (": " + "; ".join(f"{i} ({official_names.get(i, '')[:28]}) רישום={_side(reg_fractions[i])} שם={_side(by_report_name[i])}"
                              for i in sorted(diff)[:10]) if diff else ""))


def build_foreign_fractions(source: list[dict], funds: list[dict], tag: str, cache_path: Path = CACHE_PATH):
    """-> (isin_fractions, etf_universe, sec_exposure, official_names)."""
    etf_universe = fetch_etf_universe()
    sec_exposure = fetch_sec_etf_exposure()
    official_names = official_fund_names(etf_universe, sec_exposure, fetch_us_security_names())
    isin_fractions = build_isin_fractions(etf_universe, sec_exposure)
    # הרישום האמריקאי (רשימות SEC מסודרות) - לפני כל סיווג לפי שם; לא דורס את המאגרים של שכבה 1
    registry = fetch_us_registry()
    reg_fractions = registry_fractions(registry)
    added = 0
    for isin, frac in reg_fractions.items():
        if isin not in isin_fractions:
            isin_fractions[isin] = frac
            added += 1
    print(f"[{tag}] הרישום האמריקאי: {len(reg_fractions)} ISIN עם חשיפה, {added} חדשים מעבר לשכבה 1")
    strong = set(isin_fractions)  # אוניברסיטת ה-ETF / SEC / הרישום - לא נדרסים ע"י סיווג הדוח
    by_report_name = classify_from_report_names(source)
    _report_registry_vs_names(tag, reg_fractions, by_report_name, official_names)
    for isin, frac in by_report_name.items():
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

    missing = collect_unclassified_foreign_isins(funds, isin_fractions)
    from_report = classify_from_report_columns(source, missing) if missing else {}
    for isin, frac in from_report.items():
        isin_fractions.setdefault(isin, frac)
    print(f"[{tag}] סיווג הגוף בדוח (מוצא אחרון): {len(from_report)} מתוך {len(missing)} ISIN שנותרו: "
          f"{sorted(from_report)[:10]}")

    overridden = report_overrides(source, isin_fractions, strong)
    print(f"[{tag}] {len(overridden)} ISIN שסיווגם ממקור חלש סתר את סיווג הגוף בדוח - לפי הדוח: "
          f"{dict(list(overridden.items())[:10])}")

    repaired = repair_isin_typos(funds, isin_fractions)
    for bad, good in repaired.items():
        if good in official_names:
            official_names.setdefault(bad, official_names[good])
    print(f"[{tag}] {len(repaired)} ISIN עם טעות בקידומת המדינה (ספרת ביקורת) - סווגו לפי המתוקן: {repaired}")
    fixed = sanitize_fractions(isin_fractions, source, leveraged_isins=registry_leveraged_isins(registry),
                               registry_isins=set(reg_fractions))
    print(f"[{tag}] {len(fixed)} ISIN עם שבר מניות > 1 בקרן לא ממונפת - נורמלו: {fixed[:10]}")
    return isin_fractions, etf_universe, sec_exposure, official_names
