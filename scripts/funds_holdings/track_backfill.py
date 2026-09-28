"""מסלול "פעיל" (מצב==פעיל ברפרנס הרשמי, tracks) שנעלם לגמרי מהדוח העדכני
ביותר (0 שורות בכל גיליון) מקבל 0% בכל חישוב - לא כי אין לו חשיפה, אלא כי
get_file_list()/latest_per_company() משתמש *רק* בקובץ העדכני ביותר לכל
חברה (file_list.py) ומוותר על כל הרבעונים הישנים יותר, גם כשיש בהם נתונים
אמיתיים למסלול שנעלם מהדוח האחרון.

נמצא בבדיקה בפועל (514956465/מור גמל ופנסיה): מסלולים שכל הפירוט שלהם היה
שורת-סוואפ יחידה נעלמו החל מרבעון מסוים, בעוד הנתון הרשמי המצטבר
(data.gov.il) עדיין מדווח עבורם חשיפה גבוהה - סימן שהחברה הפסיקה לדווח
פירוט ברמת-נכס למסלולים האלה בקובץ המבנה-האחיד עצמו, לא שהמסלול נסגר.

התיקון: למסלול "פעיל" שריק לגמרי בקובץ העדכני, מחפשים ברבעונים ישנים
יותר (אותה חברה, gm+pn) את הקובץ *האחרון* שבו יש לו בפועל נתון, ומאמצים
את כל השורות שלו משם (כל הגיליונות יחד, לא רק סוואפ - "הנתון המפורט
האחרון שבאמת קיים למסלול הזה", לא 0% מזויף). ReportMonth של אותן שורות
נשאר תאריך *הדוח הישן*, לא היום - כך שתמחור-חי (swap/option) ממשיך לתמחר
נכון ל"מתי הנתון הזה היה אמיתי", לא ליום ריצת הפייפליין.

מסלול "פעיל" שלא נמצא לו נתון בשום קובץ (למשל מסלול חדש, כמו 517085874)
נשאר ללא פירוט כרגיל - זו לא תקלת פייפליין, אין ממה לשלוף.
"""
from pathlib import Path

from .file_list import ReportFile, list_files
from .sheet_source import build_source_for_file
from .tracks_reference import track_key

ACTIVE_STATUS_FIELD = "מצב"
ACTIVE_STATUS_VALUE = "פעיל"
INFO_STATUS = "מידע"


def _present_active_keys(source: list[dict]) -> set[str]:
    keys = set()
    for rec in source:
        if rec["מידע"] != INFO_STATUS:
            continue
        for row in rec["Clean"]:
            k = row.get("מפתח")
            if k is not None:
                keys.add(k)
    return keys


def find_missing_active_tracks(source: list[dict], tracks: list[dict]) -> dict[str, set[str]]:
    """legal_id -> סט מפתחות של מסלולים "פעיל" שריקים לגמרי בדוח העדכני."""
    present = _present_active_keys(source)
    out: dict[str, set[str]] = {}
    for t in tracks:
        if t.get(ACTIVE_STATUS_FIELD) != ACTIVE_STATUS_VALUE:
            continue
        key = track_key(t)
        if key is None or key in present:
            continue
        legal_id = key.split("_", 1)[0]
        out.setdefault(legal_id, set()).add(key)
    return out


def backfill_missing_active_tracks(
    reports_dir: Path, current_files: list[ReportFile], source: list[dict], tracks: list[dict]
) -> tuple[list[dict], dict[str, str]]:
    """(רשומות-נוספות-להוסיף-ל-source, מפתח->שם-הקובץ-שממנו-נשלף) - לדגל
    בדשבורד שהנתון למסלול הזה מיושן (לא מהדוח העדכני)."""
    missing_by_legal = find_missing_active_tracks(source, tracks)
    if not missing_by_legal:
        return [], {}

    current_names = {f.name for f in current_files}
    older_by_legal: dict[str, list[ReportFile]] = {}
    for f in list_files(reports_dir):
        if f.name in current_names:
            continue
        legal_id = f.company_type.rsplit("_", 1)[0]
        if legal_id in missing_by_legal:
            older_by_legal.setdefault(legal_id, []).append(f)

    extra_records: list[dict] = []
    backfilled_from: dict[str, str] = {}
    for legal_id, missing_keys in missing_by_legal.items():
        still_missing = set(missing_keys)
        candidates = sorted(older_by_legal.get(legal_id, []), key=lambda f: f.sort_key, reverse=True)
        for f in candidates:
            if not still_missing:
                break
            found_in_file: set[str] = set()
            for rec in build_source_for_file(f):
                if rec["מידע"] != INFO_STATUS:
                    continue
                matched = [row for row in rec["Clean"] if row.get("מפתח") in still_missing]
                if matched:
                    extra_records.append({**rec, "Clean": matched})
                    found_in_file.update(row["מפתח"] for row in matched)
            for k in found_in_file:
                backfilled_from[k] = f.name
            still_missing -= found_in_file

    return extra_records, backfilled_from
