"""חקירה חד-פעמית: מסלולים עם נתוני החזקות (category_pct/derivatives/siveg)
אבל בלי שום נתון מזהה (חברה/שם מסלול/מספר) - שאלת המשתמש.

הסיבה הארכיטקטונית הידועה: main.py בונה rows[key] מ-tracks_reference (המקור
היחיד לשמות/מספרים) בנפרד לגמרי מ-source/funds/category_pct (המקור היחיד
לנתוני החזקות) - שני "צינורות" נפרדים שממוזגים רק לפי "מפתח" משותף
(ח.פ._מספר-מסלול). row_for() ב-main.py יוצר שורה חדשה בלי אף שדה מזהה
כשמפתח מהחזקות לא נמצא ב-tracks_reference בכלל.

השאלה הפתוחה: האם זה "נורמלי" (מסלול חדש/סגור/משתנה שלא מסונכרן כרגע בין
שני המקורות) או שיש כאן תקלת-פורמט מפתח (למשל legal_id מקובץ ≠ ח.פ. חברה
מה-API). הרצה הזו בודקת בפועל.
"""
from pathlib import Path

from scripts.funds_holdings.file_list import get_file_list
from scripts.funds_holdings.sheet_source import build_source
from scripts.funds_holdings.tracks_reference import fetch_tracks, track_key


def main():
    files = get_file_list(Path("reports"))
    source = build_source(files)

    holdings_keys = set()
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            k = row.get("מפתח")
            if k:
                holdings_keys.add(k)

    tracks = fetch_tracks()
    track_keys = set()
    by_legal_tracks: dict[str, set[str]] = {}
    for t in tracks:
        k = track_key(t)
        if k:
            track_keys.add(k)
            legal, num = k.split("_", 1)
            by_legal_tracks.setdefault(legal, set()).add(num)

    only_in_holdings = holdings_keys - track_keys
    print(f"[probe] holdings keys: {len(holdings_keys)}, track keys: {len(track_keys)}, "
          f"only-in-holdings (bare rows): {len(only_in_holdings)}")

    affected_companies = set(k.split("_", 1)[0] for k in only_in_holdings)
    companies_totally_missing = affected_companies - set(by_legal_tracks.keys())
    companies_partial = affected_companies & set(by_legal_tracks.keys())
    print(f"[probe] affected companies: {len(affected_companies)} total, "
          f"{len(companies_totally_missing)} entirely absent from tracks_reference, "
          f"{len(companies_partial)} partially matched (some tracks found, some not)")

    print("\n[probe] sample (up to 40) of bare-row keys:")
    for k in sorted(only_in_holdings)[:40]:
        legal, num = k.split("_", 1)
        same_company_nums = by_legal_tracks.get(legal)
        if same_company_nums:
            shown = sorted(same_company_nums)[:8]
            more = "..." if len(same_company_nums) > 8 else ""
            print(f"  {k:<20} company {legal} IS in tracks_reference, has track#s: {shown}{more} (but not {num})")
        else:
            print(f"  {k:<20} company {legal} NOT in tracks_reference at all ({len(track_keys)} total tracks)")

    print(f"\n[probe] entirely-missing companies (sample 20): {sorted(companies_totally_missing)[:20]}")


if __name__ == "__main__":
    main()
