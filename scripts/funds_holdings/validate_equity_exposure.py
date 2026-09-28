"""בדיקת אמת: חשיפה כוללת למניות (מוחזקות ישירות + קרנות עוקבות-מניות +
חוזים עתידיים + אופציות + עסקאות החלף על בסיס מניות/מדדי מניות) מול
"חשיפה למניות" הרשמית שהמסלול מדווח ל-data.gov.il (tracks_reference).

מטרה: לבדוק אם התיקון ל-derivatives_exposure.py (חוזים עתידיים/עסקאות החלף
לפי נוציונל, לא שווי הוגן) מקרב את הסכום המחושב לנתון הרשמי, בהשוואה
לשיטה הישנה (הבאגית) - לא רק "לא קורס", אלא "מתקרב לאמת הידועה".

הרצה: python -m scripts.funds_holdings.validate_equity_exposure [--reports-dir reports]
"""
import argparse
from pathlib import Path

from .category_pct import build_category_pct
from .derivatives_exposure import (
    FUTURES_CATEGORY, OPTIONS_LISTED_CATEGORY, OPTIONS_OTC_CATEGORY, SWAP_CATEGORY,
    build_derivatives_exposure, total_assets_by_key,
)
from .excel_io import to_ratio
from .file_list import get_file_list
from .foreign_etf_reference import (
    build_foreign_equity, build_isin_fractions, classify_from_report_names,
    classify_via_openfigi_names, collect_unclassified_foreign_isins,
    fetch_etf_universe, fetch_sec_etf_exposure,
)
from .funds import build_funds
from .funds_reference import build_funds_reference
from .funds_il import build_funds_il
from .isin_swap import build_isin_swap
from .sheet_source import PCT_COL, build_source
from .tracks_reference import fetch_tracks, track_key

EQUITY_UNDERLYING = 'מניות לרבות מדדי מניות'
FUT_BASE_COL = "נכס בסיס"
SWAP_TYPE_COL = "סוג הנכס"
OPT_BASE_COL = "נכס בסיס"

DIRECT_EQUITY_CATEGORIES = ("מניות מבכ ויהש", "לא סחיר מניות מבכ ויהש")
OPTIONS_CATEGORIES = (OPTIONS_LISTED_CATEGORY, OPTIONS_OTC_CATEGORY)
EQUITY_FUND_SIVEGS = ("מחקה - מניות בארץ", "מחקה - מניות בחו\"ל")


def _equity_derivative_pct(source, category, base_col, use_fixed):
    """מפתח -> שיעור חשיפה (ישן=שווי הוגן / חדש=נוציונלי מתוקן), רק לשורות
    עם נכס בסיס/סוג נכס == מניות. use_fixed=False משחזר את החישוב הישן
    (כמו category_pct המקורי, לפני התיקון) לצורך השוואה בלבד."""
    if use_fixed:
        # דרך build_derivatives_exposure, אבל מסוננת לשורות מניות בלבד -
        # קוראים לפונקציות הפנימיות ישירות דרך source מסונן.
        filtered = []
        for rec in source:
            if rec["Category"] != category:
                filtered.append(rec)
                continue
            keep_rows = [r for r in rec["Clean"] if r.get(base_col) == EQUITY_UNDERLYING]
            filtered.append({**rec, "Clean": keep_rows})
        totals = total_assets_by_key(filtered)
        deriv = build_derivatives_exposure(filtered)
        return {k: v.get(category, 0.0) for k, v in deriv.items()}

    sums = {}
    for rec in source:
        if rec["Category"] != category or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            if row.get(base_col) != EQUITY_UNDERLYING:
                continue
            key = row.get("מפתח")
            pct = to_ratio(row.get(PCT_COL))
            if key is None or pct is None:
                continue
            sums[key] = sums.get(key, 0.0) + pct
    return sums


def compute_equity_totals(reports_dir: Path, tracks: list[dict]):
    files = get_file_list(reports_dir)
    source = build_source(files)

    funds_ref = build_funds_reference()
    isin_swap = build_isin_swap(funds_ref)
    funds = build_funds(source, isin_swap)
    il_sums = build_funds_il(funds, funds_ref)

    isin_fractions = build_isin_fractions(fetch_etf_universe(), fetch_sec_etf_exposure())
    for isin, frac in classify_from_report_names(source).items():
        isin_fractions.setdefault(isin, frac)
    print(f"[validate] {len(isin_fractions)} ISIN מסווגים (ETF זרות: אירופה+SEC+שם-קרן)")

    still_missing = collect_unclassified_foreign_isins(funds, isin_fractions)
    try:
        from .sec_nport_reference import build_isin_fractions_via_nport
        for isin, frac in build_isin_fractions_via_nport(still_missing).items():
            isin_fractions.setdefault(isin, frac)
    except Exception as e:
        print(f"[validate] שכבת SEC N-PORT חי נכשלה (מדלג): {e}")
    print(f"[validate] {len(isin_fractions)} ISIN מסווגים סה\"כ (+N-PORT חי)")

    still_missing_2 = collect_unclassified_foreign_isins(funds, isin_fractions)
    try:
        for isin, frac in classify_via_openfigi_names(still_missing_2).items():
            isin_fractions.setdefault(isin, frac)
    except Exception as e:
        print(f"[validate] שכבת שמות-מלאים OpenFIGI נכשלה (מדלג): {e}")
    print(f"[validate] {len(isin_fractions)} ISIN מסווגים סה\"כ (+שמות מלאים)")

    foreign_equity = build_foreign_equity(funds, isin_fractions)

    category_pct = build_category_pct(source)

    fut_old = _equity_derivative_pct(source, FUTURES_CATEGORY, FUT_BASE_COL, use_fixed=False)
    fut_new = _equity_derivative_pct(source, FUTURES_CATEGORY, FUT_BASE_COL, use_fixed=True)
    swap_old = _equity_derivative_pct(source, SWAP_CATEGORY, SWAP_TYPE_COL, use_fixed=False)
    swap_new = _equity_derivative_pct(source, SWAP_CATEGORY, SWAP_TYPE_COL, use_fixed=True)
    opt_listed_old = _equity_derivative_pct(source, OPTIONS_LISTED_CATEGORY, OPT_BASE_COL, use_fixed=False)
    opt_listed_new = _equity_derivative_pct(source, OPTIONS_LISTED_CATEGORY, OPT_BASE_COL, use_fixed=True)
    opt_otc_old = _equity_derivative_pct(source, OPTIONS_OTC_CATEGORY, OPT_BASE_COL, use_fixed=False)
    opt_otc_new = _equity_derivative_pct(source, OPTIONS_OTC_CATEGORY, OPT_BASE_COL, use_fixed=True)

    def _opt_old(key):
        return opt_listed_old.get(key, 0.0) + opt_otc_old.get(key, 0.0)

    def _opt_new(key):
        return opt_listed_new.get(key, 0.0) + opt_otc_new.get(key, 0.0)

    official = {}
    for t in tracks:
        key = track_key(t)
        if key is None:
            continue
        raw = t.get("חשיפה למניות") or t.get("STOCK_MARKET_EXPOSURE")
        v = to_ratio(raw) if isinstance(raw, str) and raw.strip() else raw
        if v is not None:
            try:
                official[key] = float(v) / (100 if abs(float(v)) > 1.5 else 1)
            except (TypeError, ValueError):
                pass

    keys = set(official)
    rows = []
    for key in keys:
        cats = category_pct.get(key, {})
        direct = sum(cats.get(c, 0.0) for c in DIRECT_EQUITY_CATEGORIES)
        siveg = il_sums.get(key, {})
        funds_eq = sum(v for k, v in siveg.items() if any(s in k for s in EQUITY_FUND_SIVEGS))
        foreign_eq = sum(v for k, v in foreign_equity.get(key, {}).items()
                          if any(s in k for s in EQUITY_FUND_SIVEGS))

        base = direct + funds_eq
        old_total = base + fut_old.get(key, 0.0) + swap_old.get(key, 0.0) + _opt_old(key)
        deriv_only = base + fut_new.get(key, 0.0) + swap_new.get(key, 0.0) + _opt_new(key)
        full = deriv_only + foreign_eq
        rows.append((key, official[key], old_total, deriv_only, full))

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = ap.parse_args()

    tracks = fetch_tracks()
    print(f"[validate] {len(tracks)} מסלולים מ-tracks")

    rows = compute_equity_totals(args.reports_dir, tracks)
    print(f"[validate] {len(rows)} מסלולים עם חשיפה למניות רשמית + נתוני דוח מקומיים")
    if not rows:
        return

    def mae(idx):
        errs = [abs(r[idx] - r[1]) for r in rows]
        return sum(errs) / len(errs)

    def compare(idx_a, idx_b):
        a_errs = [abs(r[idx_a] - r[1]) for r in rows]
        b_errs = [abs(r[idx_b] - r[1]) for r in rows]
        improved = sum(1 for a, b in zip(a_errs, b_errs) if b < a)
        worsened = sum(1 for a, b in zip(a_errs, b_errs) if b > a)
        return improved, worsened, len(rows) - improved - worsened

    print(f"\nMAE (שגיאה ממוצעת מוחלטת מול הרשמי), {len(rows)} מסלולים:")
    print(f"  שיטה ישנה (שווי הוגן, בלי ETF זרות):      {mae(2)*100:.3f} נק' אחוז")
    print(f"  + תיקון נגזרים (נוציונלי+דלתא לאופציות):  {mae(3)*100:.3f} נק' אחוז")
    print(f"  + תיקון נגזרים + קרנות ETF זרות:          {mae(4)*100:.3f} נק' אחוז")
    i1, w1, s1 = compare(2, 3)
    print(f"  תיקון נגזרים בלבד מול ישן: שופר {i1} | הורע {w1} | ללא שינוי {s1}")
    i2, w2, s2 = compare(3, 4)
    print(f"  + ETF זרות מול תיקון נגזרים בלבד: שופר {i2} | הורע {w2} | ללא שינוי {s2}")

    rows_sorted = sorted(rows, key=lambda r: -abs(r[4] - r[1]))
    print("\n15 הפערים הגדולים ביותר (שיטה מלאה מול רשמי):")
    print(f"{'מפתח':<20}{'רשמי':>10}{'ישן':>10}{'נגזרים':>10}{'מלא':>10}{'|מלא-רשמי|':>14}")
    for key, off, old, deriv, full in rows_sorted[:15]:
        print(f"{key:<20}{off*100:>9.2f}%{old*100:>9.2f}%{deriv*100:>9.2f}%{full*100:>9.2f}%{abs(full-off)*100:>13.2f}%")

    print("\n15 השיפורים הגדולים ביותר (שיטה מלאה קרובה בהרבה יותר לרשמי מהישנה):")
    by_improvement = sorted(rows, key=lambda r: (abs(r[2]-r[1]) - abs(r[4]-r[1])), reverse=True)
    for key, off, old, deriv, full in by_improvement[:15]:
        print(f"{key:<20}{off*100:>9.2f}%{old*100:>9.2f}%{deriv*100:>9.2f}%{full*100:>9.2f}%"
              f"  (ישן-רשמי={abs(old-off)*100:.2f}%, מלא-רשמי={abs(full-off)*100:.2f}%)")


if __name__ == "__main__":
    main()
