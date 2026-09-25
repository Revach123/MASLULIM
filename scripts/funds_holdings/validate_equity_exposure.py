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
    FUTURES_CATEGORY, SWAP_CATEGORY, build_derivatives_exposure, total_assets_by_key,
)
from .excel_io import to_ratio
from .file_list import get_file_list
from .funds import build_funds
from .funds_reference import build_funds_reference
from .funds_il import build_funds_il
from .isin_swap import build_isin_swap
from .sheet_source import PCT_COL, build_source
from .tracks_reference import fetch_tracks, track_key

EQUITY_UNDERLYING = 'מניות לרבות מדדי מניות'
FUT_BASE_COL = "נכס בסיס"
SWAP_TYPE_COL = "סוג הנכס"

DIRECT_EQUITY_CATEGORIES = ("מניות מבכ ויהש", "לא סחיר מניות מבכ ויהש")
OPTIONS_CATEGORIES = ("אופציות", "לא סחיר אופציות")
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

    category_pct = build_category_pct(source)

    fut_old = _equity_derivative_pct(source, FUTURES_CATEGORY, FUT_BASE_COL, use_fixed=False)
    fut_new = _equity_derivative_pct(source, FUTURES_CATEGORY, FUT_BASE_COL, use_fixed=True)
    swap_old = _equity_derivative_pct(source, SWAP_CATEGORY, SWAP_TYPE_COL, use_fixed=False)
    swap_new = _equity_derivative_pct(source, SWAP_CATEGORY, SWAP_TYPE_COL, use_fixed=True)

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
        options = sum(cats.get(c, 0.0) for c in OPTIONS_CATEGORIES)
        siveg = il_sums.get(key, {})
        funds_eq = sum(v for k, v in siveg.items() if any(s in k for s in EQUITY_FUND_SIVEGS))

        base = direct + options + funds_eq
        old_total = base + fut_old.get(key, 0.0) + swap_old.get(key, 0.0)
        new_total = base + fut_new.get(key, 0.0) + swap_new.get(key, 0.0)
        rows.append((key, official[key], old_total, new_total))

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

    old_errs = [abs(old - off) for _, off, old, _ in rows]
    new_errs = [abs(new - off) for _, off, _, new in rows]
    old_mae = sum(old_errs) / len(old_errs)
    new_mae = sum(new_errs) / len(new_errs)
    improved = sum(1 for o, n in zip(old_errs, new_errs) if n < o)
    worsened = sum(1 for o, n in zip(old_errs, new_errs) if n > o)
    same = len(rows) - improved - worsened

    print(f"\nMAE (שגיאה ממוצעת מוחלטת מול הרשמי):")
    print(f"  שיטה ישנה (שווי הוגן): {old_mae*100:.3f} נק' אחוז")
    print(f"  שיטה חדשה (נוציונלי):  {new_mae*100:.3f} נק' אחוז")
    print(f"  שופר: {improved} | הורע: {worsened} | ללא שינוי: {same} (מתוך {len(rows)})")

    rows_sorted = sorted(rows, key=lambda r: -abs(r[3] - r[1]))
    print("\n15 הפערים הגדולים ביותר (שיטה חדשה מול רשמי):")
    print(f"{'מפתח':<20}{'רשמי':>10}{'ישן':>10}{'חדש':>10}{'|חדש-רשמי|':>14}")
    for key, off, old, new in rows_sorted[:15]:
        print(f"{key:<20}{off*100:>9.2f}%{old*100:>9.2f}%{new*100:>9.2f}%{abs(new-off)*100:>13.2f}%")

    print("\n15 השיפורים הגדולים ביותר (שיטה חדשה קרובה בהרבה יותר לרשמי):")
    by_improvement = sorted(rows, key=lambda r: (abs(r[2]-r[1]) - abs(r[3]-r[1])), reverse=True)
    for key, off, old, new in by_improvement[:15]:
        print(f"{key:<20}{off*100:>9.2f}%{old*100:>9.2f}%{new*100:>9.2f}%"
              f"  (ישן-רשמי={abs(old-off)*100:.2f}%, חדש-רשמי={abs(new-off)*100:.2f}%)")


if __name__ == "__main__":
    main()
