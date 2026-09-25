"""בניית הטבלה הראשית: שורה למסלול (מפתח), נתוני tracks + כל הטורים שנוספו
גליון-גליון. גם שומר בנפרד את הרשימה המפורטת לכל מסלול (לפתיחה בלחיצה
על הטבלה הראשית בעתיד - לא נכנס לטבלה הראשית עצמה).

הרצה: python -m funds_holdings.main [--reports-dir reports] [--out-dir out]
"""
import argparse
import json
from pathlib import Path

from . import heter_iska as heter_iska_module
from .bonds_detail import build_bonds_detail
from .bonds_heter_reference import build_bonds_heter_by_isin
from .bonds_rank import build_bonds_rank
from .category_pct import build_category_pct
from .derivatives_exposure import DERIVATIVE_CATEGORIES, build_derivatives_exposure
from .file_list import get_file_list
from .foreign_etf_reference import (
    build_foreign_equity, build_isin_fractions, classify_from_report_names,
    collect_unclassified_foreign_isins, fetch_etf_universe, fetch_sec_etf_exposure,
)
from .funds import build_funds
from .funds_detail import build_funds_detail
from .funds_il import build_funds_il, build_funds_il_kashrut
from .funds_reference import build_funds_reference
from .interest import build_interest
from .isin_swap import build_isin_swap
from .kashrut_rank import NO_KASHRUT, build_kashrut_by_num, build_track_kashrut
from .sheet_source import build_source
from .tracks_reference import fetch_tracks, track_key


def build_master_table(
    reports_dir: Path, tracks: list[dict]
) -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    files = get_file_list(reports_dir)
    source = build_source(files)

    funds_ref = build_funds_reference()
    print(f"[main] {len(funds_ref)} קרנות מ-נתוני קרנות (revach)")
    isin_swap = build_isin_swap(funds_ref)

    funds = build_funds(source, isin_swap)
    print(f"[main] {len(funds)} שורות קרנות (מקור_גליונות)")

    heter_by_chp = heter_iska_module.build()
    interest = build_interest(source, heter_by_chp=heter_by_chp)
    category_pct = build_category_pct(source)

    # "שיעור מסך נכסי ההשקעה" בדוחות עבור חוזים עתידיים ועסקאות החלף הוא
    # שיעור השווי ההוגן (מרווח/רווח-הפסד שוטף), לא שיעור החשיפה הכלכלית
    # שהמכשירים האלה יוצרים (leverage). מחליפים את שתי הקטגוריות האלה
    # בחשיפה אמיתית (notional) - שאר הקטגוריות נשארות כשווי-שוק, נכון כבר.
    derivatives_exposure = build_derivatives_exposure(source)
    for key, cols in derivatives_exposure.items():
        d = category_pct.setdefault(key, {})
        for cat in DERIVATIVE_CATEGORIES:
            if cat in cols:
                d[cat] = cols[cat]

    il_sums = build_funds_il(funds, funds_ref)

    # קרנות "חוץ" (לא ישראליות, לא נסחרות ב-TASE - funds_ref לא מזהה אותן
    # בכלל) - מזוהות/מסווגות למניות/אג"ח דרך שני מאגרי ETF זרים ב-revach
    # (אוניברסיטת ETF אירופית + חשיפת ETF אמריקאיות לפי SEC) שלא ממופים
    # כרגע דרך funds_reference.py. מצטרף לאותן עמודות "קרן מחקה - ..." -
    # אין חפיפה עם il_sums (כל שורת קרן מסווגת בדיוק ל-IL/נסחרת/חוץ אחת).
    isin_fractions = build_isin_fractions(fetch_etf_universe(), fetch_sec_etf_exposure())
    # שכבת מוצא-אחרון: קרנות לא-מזוהות באף מאגר - לפי שם הקרן כפי שמדווח
    # בדוח עצמו (ר' תיעוד ב-classify_from_report_names). לא דורס נתון קיים.
    for isin, frac in classify_from_report_names(source).items():
        isin_fractions.setdefault(isin, frac)
    print(f"[main] {len(isin_fractions)} ISIN מסווגים (ETF זרות: אירופה+SEC+שם-קרן)")

    # שכבה אחרונה, יקרה (קריאות רשת חיות ל-SEC) - רק על מה שעדיין חסר
    # (ר' תיעוד ב-sec_nport_reference.py). כשלון רשת כולל (OpenFIGI/SEC לא
    # זמינים בסביבת הריצה) לא מפיל את הפייפליין - מדלג בשקט (רשימה ריקה).
    still_missing = collect_unclassified_foreign_isins(funds, isin_fractions)
    try:
        from .sec_nport_reference import build_isin_fractions_via_nport
        for isin, frac in build_isin_fractions_via_nport(still_missing).items():
            isin_fractions.setdefault(isin, frac)
    except Exception as e:
        print(f"[main] שכבת SEC N-PORT חי נכשלה (מדלג): {e}")
    print(f"[main] {len(isin_fractions)} ISIN מסווגים סה\"כ (+N-PORT חי)")

    for key, cols in build_foreign_equity(funds, isin_fractions).items():
        d = il_sums.setdefault(key, {})
        for siveg, pct in cols.items():
            d[siveg] = d.get(siveg, 0.0) + pct

    kashrut_by_num = build_kashrut_by_num(funds_ref)
    il_kashrut = build_funds_il_kashrut(funds, funds_ref, kashrut_by_num)
    track_kashrut = build_track_kashrut(funds, kashrut_by_num)
    funds_detail = build_funds_detail(funds, funds_ref)

    bonds_heter_by_isin = build_bonds_heter_by_isin()
    print(f"[main] {len(bonds_heter_by_isin)} ניירות מ-bonds_heter (revach)")
    bonds_rank = build_bonds_rank(source, bonds_heter_by_isin)
    bonds_detail = build_bonds_detail(source, bonds_heter_by_isin)

    rows: dict[str, dict] = {}
    for t in tracks:
        key = track_key(t)
        if key is None:
            continue
        rows[key] = dict(t)
        rows[key]["מפתח"] = key

    def row_for(key: str) -> dict:
        return rows.setdefault(key, {"מפתח": key})

    for key, cols in interest.items():
        row_for(key).update(cols)

    for key, cols in bonds_rank.items():
        row_for(key).update(cols)

    for key, cat_sums in category_pct.items():
        row_for(key).update(cat_sums)

    for key, siveg_sums in il_sums.items():
        row_for(key).update(siveg_sums)

    # כשרות לכל עמודת אחוז-סיווג בנפרד (מוצג בפרונט מתחת לאחוז) - מפתח
    # מסומן בסיומת " |כשרות" כדי לא להתנגש עם מפתח האחוז (siveg) עצמו.
    for key, siveg_kashrut in il_kashrut.items():
        row = row_for(key)
        for siveg, level in siveg_kashrut.items():
            row[f"{siveg} |כשרות"] = level

    for key, level in track_kashrut.items():
        row_for(key)["כשרות"] = level

    # מסלול בלי שום נתוני החזקות בדוחות (לא ב-funds בכלל) = "בלי כשרות",
    # לא "לא ידוע" - אותו עיקרון כמו קרן שלא זוהתה (kashrut_rank.py).
    for row in rows.values():
        row.setdefault("כשרות", NO_KASHRUT)

    return list(rows.values()), funds_detail, bonds_detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--out-dir", type=Path, default=Path("out"))
    args = ap.parse_args()

    tracks = fetch_tracks()
    print(f"[main] {len(tracks)} מסלולים מ-tracks")

    master, funds_detail, bonds_detail = build_master_table(args.reports_dir, tracks)
    print(f"[main] {len(master)} שורות בטבלה הראשית")
    print(f"[main] {len(funds_detail)} מסלולים עם רשימת קרנות מפורטת")
    print(f"[main] {len(bonds_detail)} מסלולים עם רשימת אג\"ח מפורטת")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out_dir / "master.json", "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    with open(args.out_dir / "funds_detail.json", "w", encoding="utf-8") as f:
        json.dump(funds_detail, f, ensure_ascii=False, indent=2)
    with open(args.out_dir / "bonds_detail.json", "w", encoding="utf-8") as f:
        json.dump(bonds_detail, f, ensure_ascii=False, indent=2)
    print(f"[main] נשמר -> {args.out_dir}/master.json, {args.out_dir}/funds_detail.json, "
          f"{args.out_dir}/bonds_detail.json")


if __name__ == "__main__":
    main()
