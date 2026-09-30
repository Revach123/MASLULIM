"""בדיקת אמת: חשיפה כוללת למניות (מוחזקות ישירות + קרנות עוקבות-מניות +
חוזים עתידיים + אופציות + עסקאות החלף על בסיס מניות/מדדי מניות) מול
"חשיפה למניות" הרשמית שהמסלול מדווח ל-data.gov.il (tracks_reference).

מטרה: לבדוק אם התיקון ל-derivatives_exposure.py (חוזים עתידיים/עסקאות החלף
לפי נוציונל, לא שווי הוגן) מקרב את הסכום המחושב לנתון הרשמי, בהשוואה
לשיטה הישנה (הבאגית) - לא רק "לא קורס", אלא "מתקרב לאמת הידועה".

הרצה: python -m scripts.funds_holdings.validate_equity_exposure [--reports-dir reports]
"""
import argparse
import os
from pathlib import Path

from .category_pct import build_category_pct
from .derivatives_exposure import (
    FUTURES_CATEGORY, FUTURES_EQUITY_COLUMN, OPTIONS_LISTED_CATEGORY, OPTIONS_OTC_CATEGORY, SWAP_CATEGORY,
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
from .track_pct_normalize import normalize_track_pct
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
    if use_fixed and category == FUTURES_CATEGORY:
        # חוזים: המקור המלא - זיהוי החוזה לומד משמות/רמות של כל השורות, והסיווג
        # למניות נעשה לפי החוזה שזוהה (ר' futures_notional.NON_EQUITY_ROOTS).
        deriv = build_derivatives_exposure(source)
        return {k: v[FUTURES_EQUITY_COLUMN] for k, v in deriv.items() if FUTURES_EQUITY_COLUMN in v}
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
    rescaled = normalize_track_pct(source)
    print(f"[validate] {len(rescaled)} מסלולים נורמלו (שיעור מסך נכסי ההשקעה לא הסתכם ל-100%)")

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

    still_missing_yahoo = collect_unclassified_foreign_isins(funds, isin_fractions)
    try:
        from .yahoo_fund_reference import build_isin_fractions_via_yahoo
        for isin, frac in build_isin_fractions_via_yahoo(still_missing_yahoo).items():
            isin_fractions.setdefault(isin, frac)
    except Exception as e:
        print(f"[validate] שכבת Yahoo/Morningstar נכשלה (מדלג): {e}")
    print(f"[validate] {len(isin_fractions)} ISIN מסווגים סה\"כ (+Yahoo/Morningstar)")

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

    # חודש הדוח האחרון לכל מסלול (YYYYMM) - להשוואה מול "נכון לחודש" של הנתון הרשמי
    report_month: dict[str, str] = {}
    for rec in source:
        d = rec.get("ReportMonth")
        if d is None:
            continue
        ym = f"{d.year}{d.month:02d}"
        for r in rec["Clean"]:
            k = r.get("מפתח")
            if k is not None and ym > report_month.get(k, ""):
                report_month[k] = ym

    official = {}
    official_month: dict[str, str] = {}
    domain_track: dict[str, tuple[str, str]] = {}
    for t in tracks:
        key = track_key(t)
        if key is None:
            continue
        official_month[key] = str(t.get("נכון לחודש") or "").strip()
        domain_track[key] = (str(t.get("תחום") or "").strip(), key.split("_", 1)[1])
        raw = t.get("חשיפה למניות") or t.get("STOCK_MARKET_EXPOSURE")
        v = to_ratio(raw) if isinstance(raw, str) and raw.strip() else raw
        if v is not None:
            try:
                official[key] = float(v) / (100 if abs(float(v)) > 1.5 else 1)
            except (TypeError, ValueError):
                pass

    # הנתון הרשמי לחודש הדוח עצמו (לא לחודש האחרון), מ-data.gov.il
    official_at_report: dict[str, float] = {}
    try:
        from .official_history import fetch_stock_exposure
        hist = fetch_stock_exposure({m for m in report_month.values() if m})
        for key, (dom, track) in domain_track.items():
            v = hist.get((dom, track, report_month.get(key, "")))
            if v is not None:
                official_at_report[key] = v
        print(f"[validate] {len(hist)} ערכים רשמיים מ-data.gov.il לחודשי הדוחות, "
              f"{len(official_at_report)} מסלולים הותאמו")
    except Exception as e:
        print(f"[validate] data.gov.il לא זמין (מדלג על השוואה לחודש הדוח): {e}")

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
        if os.environ.get("DUMP_EQUITY_COMPONENTS"):
            print("COMP|" + "|".join(str(x) for x in (
                key, official[key], direct, funds_eq, foreign_eq,
                fut_new.get(key, 0.0), swap_new.get(key, 0.0), _opt_new(key), key in category_pct,
                official_month.get(key, ""), report_month.get(key, ""),
                official_at_report.get(key, ""))))
        # has_data: האם קיימת ולו שורת דוח אחת (בכל גיליון/קטגוריה) למסלול
        # הזה בארכיון המקומי - לא "0% חשיפה למניות בפועל" (מסלול אג"ח טהור
        # לגיטימי, שגם הוא יכול לצאת old=deriv=full=0.0 בלי שום בעיה), אלא
        # אין בכלל קובצי דוח/שורות לטיקר הזה (ר' 517085874 שנבדק בעבר).
        rows.append((key, official[key], old_total, deriv_only, full, key in category_pct,
                     official_month.get(key, ""), report_month.get(key, ""), official_at_report.get(key)))

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

    # has_data (r[5]): האם קיימת ולו שורת דוח אחת (בכל גיליון) למסלול הזה
    # בארכיון המקומי - נגזר מ-category_pct בתוך compute_equity_totals, לא
    # מ-"old=deriv=full=0.0" (זה היה שגוי: מסלול אג"ח טהור לגיטימי, עם דוח
    # מלא אבל בלי אחזקות מניות/נגזרים כלל, גם הוא יוצא 0.0 בכל השיטות ואינו
    # "בלי נתונים" באמת - ר' 517085874 לדוגמה אמיתית ל"בלי נתונים"). כלילת
    # מסלולים "בלי נתונים" ב-MAE מנפחת אותו באופן שאינו קשור לאיכות החישוב
    # על מסלולים שיש להם בכלל נתונים - מדווחים בנפרד.
    rows_with_data = [r for r in rows if r[5]]
    no_data_count = len(rows) - len(rows_with_data)

    def mae(idx, rows_subset):
        errs = [abs(r[idx] - r[1]) for r in rows_subset]
        return sum(errs) / len(errs) if errs else 0.0

    def compare(idx_a, idx_b, rows_subset):
        a_errs = [abs(r[idx_a] - r[1]) for r in rows_subset]
        b_errs = [abs(r[idx_b] - r[1]) for r in rows_subset]
        improved = sum(1 for a, b in zip(a_errs, b_errs) if b < a)
        worsened = sum(1 for a, b in zip(a_errs, b_errs) if b > a)
        return improved, worsened, len(rows_subset) - improved - worsened

    print(f"\nMAE (שגיאה ממוצעת מוחלטת מול הרשמי), {len(rows)} מסלולים "
          f"({no_data_count} מהם בלי נתוני דוח כלל - מוצגים בנפרד למטה):")
    print(f"  שיטה ישנה (שווי הוגן, בלי ETF זרות):      {mae(2, rows)*100:.3f} נק' אחוז")
    print(f"  + תיקון נגזרים (נוציונלי+דלתא לאופציות):  {mae(3, rows)*100:.3f} נק' אחוז")
    print(f"  + תיקון נגזרים + קרנות ETF זרות:          {mae(4, rows)*100:.3f} נק' אחוז")
    i1, w1, s1 = compare(2, 3, rows)
    print(f"  תיקון נגזרים בלבד מול ישן: שופר {i1} | הורע {w1} | ללא שינוי {s1}")
    i2, w2, s2 = compare(3, 4, rows)
    print(f"  + ETF זרות מול תיקון נגזרים בלבד: שופר {i2} | הורע {w2} | ללא שינוי {s2}")

    print(f"\nMAE ללא מסלולים בלי נתוני דוח כלל, {len(rows_with_data)} מסלולים:")
    print(f"  שיטה ישנה (שווי הוגן, בלי ETF זרות):      {mae(2, rows_with_data)*100:.3f} נק' אחוז")
    print(f"  + תיקון נגזרים (נוציונלי+דלתא לאופציות):  {mae(3, rows_with_data)*100:.3f} נק' אחוז")
    print(f"  + תיקון נגזרים + קרנות ETF זרות:          {mae(4, rows_with_data)*100:.3f} נק' אחוז")
    i1d, w1d, s1d = compare(2, 3, rows_with_data)
    print(f"  תיקון נגזרים בלבד מול ישן: שופר {i1d} | הורע {w1d} | ללא שינוי {s1d}")
    i2d, w2d, s2d = compare(3, 4, rows_with_data)
    print(f"  + ETF זרות מול תיקון נגזרים בלבד: שופר {i2d} | הורע {w2d} | ללא שינוי {s2d}")

    rows = rows_with_data

    # המדד הראשי: מול הנתון הרשמי *לחודש הדוח* (data.gov.il, STOCK_MARKET_EXPOSURE /
    # TOTAL_ASSETS לאותו REPORT_PERIOD) - לא הנתון באתר, שהוא מהחודש האחרון או
    # הזנה ידנית (מסלולים חדשים). מסלול בלי נתון לחודש הדוח לא נכלל כאן.
    dated = [(r[0], r[8], r[2], r[3], r[4], r[5]) for r in rows if r[8] is not None]
    if dated:
        print(f"\nMAE מול הנתון הרשמי לתאריך הדוח (data.gov.il), {len(dated)} מסלולים "
              f"({len(rows) - len(dated)} בלי נתון רשמי לחודש הדוח - לא נכללים):")
        print(f"  שיטה ישנה (שווי הוגן, בלי ETF זרות):      {mae(2, dated)*100:.3f} נק' אחוז")
        print(f"  + תיקון נגזרים (נוציונלי+דלתא לאופציות):  {mae(3, dated)*100:.3f} נק' אחוז")
        print(f"  + תיקון נגזרים + קרנות ETF זרות:          {mae(4, dated)*100:.3f} נק' אחוז")
        print("  15 הפערים הגדולים (מלא מול רשמי לתאריך הדוח):")
        for key, off, old, deriv, full, _ in sorted(dated, key=lambda r: -abs(r[4] - r[1]))[:15]:
            print(f"    {key:<20}{off*100:>9.2f}%{full*100:>9.2f}%{abs(full-off)*100:>9.2f}%")

    # הנתון הרשמי ("נכון לחודש") לא תמיד מאותו חודש כמו הדוח - במסלולים חדשים
    # הוא מוזן ידנית ומתאריך אחר. MAE לפי חודש הנתון הרשמי, ובנפרד רק מסלולים
    # שבהם הוא זהה לחודש הדוח האחרון של המסלול.
    by_month: dict[str, list] = {}
    for r in rows:
        by_month.setdefault(r[6] or "?", []).append(r)
    print("\nMAE (שיטה מלאה) לפי חודש הנתון הרשמי ('נכון לחודש'):")
    for m in sorted(by_month, key=lambda m: -len(by_month[m])):
        print(f"  {m:>8}: {len(by_month[m]):5d} מסלולים, MAE {mae(4, by_month[m])*100:.3f} נק' אחוז")
    same = [r for r in rows if r[6] and r[6] == r[7]]
    print(f"MAE (שיטה מלאה) רק כשחודש הנתון הרשמי = חודש הדוח: {len(same)} מסלולים, "
          f"{mae(4, same)*100:.3f} נק' אחוז")
    at = [r for r in rows if r[8] is not None]
    if at:
        mae_at = sum(abs(r[4] - r[8]) for r in at) / len(at)
        print(f"MAE (שיטה מלאה) מול הנתון הרשמי לחודש הדוח (data.gov.il): {len(at)} מסלולים, "
              f"{mae_at*100:.3f} נק' אחוז (מול החודש האחרון, אותם מסלולים: {mae(4, at)*100:.3f})")

    rows_sorted = sorted(rows, key=lambda r: -abs(r[4] - r[1]))
    print("\n15 הפערים הגדולים ביותר (שיטה מלאה מול רשמי):")
    print(f"{'מפתח':<20}{'רשמי':>10}{'ישן':>10}{'נגזרים':>10}{'מלא':>10}{'|מלא-רשמי|':>14}")
    for key, off, old, deriv, full, *_ in rows_sorted[:15]:
        print(f"{key:<20}{off*100:>9.2f}%{old*100:>9.2f}%{deriv*100:>9.2f}%{full*100:>9.2f}%{abs(full-off)*100:>13.2f}%")

    print("\n15 השיפורים הגדולים ביותר (שיטה מלאה קרובה בהרבה יותר לרשמי מהישנה):")
    by_improvement = sorted(rows, key=lambda r: (abs(r[2]-r[1]) - abs(r[4]-r[1])), reverse=True)
    for key, off, old, deriv, full, *_ in by_improvement[:15]:
        print(f"{key:<20}{off*100:>9.2f}%{old*100:>9.2f}%{deriv*100:>9.2f}%{full*100:>9.2f}%"
              f"  (ישן-רשמי={abs(old-off)*100:.2f}%, מלא-רשמי={abs(full-off)*100:.2f}%)")


if __name__ == "__main__":
    main()
