"""אג"ח/ני"ע: worst-case לכל מסלול, לפי היתר עסקה (HARAV_LEVIN) ועדה,
בדיוק לפי סדר העדיפות שהמשתמש קבע (סדר עולה - הכי גרוע ראשון):
"אג"ח לא מזוהה" < "אין" < "בעלות גוי" < "כללי" < "פרטי" < "עדה?" < "עדה".

מקור: לא חלק מ-Autopilot_Section1.m - הרחבה חדשה, לפי הנחיית המשתמש.

התאמה: מספר נייר ערך (ISIN, "סוג מספר נייר ערך"=="ISIN" כשהעמודה קיימת;
"איגרות חוב ממשלתיות" חסרה עמודת-סוג אך הערכים בפורמט ISIN גם שם) מול
bonds_heter_reference.py (isin -> heter_bucket/ada_status). קטגוריית
"לא סחיר איגרות חוב מיועדות" מוחרגת - מזהה מספרי פנימי (לא ISIN), אג"ח
מיועדות/ערד שמונפקות ע"י המדינה (כמו אג"ח ממשלתי - "לא רלוונטי").

לכל נייר תואם עם heter_bucket == "לא רלוונטי" (אג"ח ממשלתי/מק"מ, אין
ח.פ מנפיק) - לא נכלל בכלל בדירוג (כמו בבונדס-הת"ע של revach עצמו).
לכל נייר אחר: הרמה היא הטובה מבין heter_bucket ו-ada_status (אם עדה
אומרת "עדה"/"עדה?" זה טוב מספיק גם אם heter_bucket גרוע יותר).
"""
from .excel_io import text_from

BOND_CATEGORIES = {
    "איגרות חוב", "איגרות חוב ממשלתיות", "ניירות ערך מסחריים",
    "לא סחיר איגרות חוב", "לא סחיר איגרות חוב ממשלתיות",
    "לא סחיר ניירות ערך מסחריים",
}
SECNO_TYPE_COL = "סוג מספר נייר ערך"
SECNO_COL = "מספר נייר ערך"
SECNAME_COL = "שם נייר ערך"

UNIDENTIFIED = 'אג"ח לא מזוהה'
NOT_RELEVANT = "לא רלוונטי"
LEVELS = [UNIDENTIFIED, "אין", "בעלות גוי", "כללי", "פרטי", "עדה?", "עדה"]
_RANK = {level: i for i, level in enumerate(LEVELS)}


def _bond_level(entry: dict | None) -> str | None:
    """None אם לא רלוונטי (אג"ח ממשלתי/מק"מ בלי ח.פ) - לא נכלל בדירוג בכלל."""
    if entry is None:
        return UNIDENTIFIED
    bucket = entry.get("heter_bucket")
    if bucket == NOT_RELEVANT:
        return None
    ada = entry.get("ada_status")
    rank = _RANK.get(bucket, _RANK["אין"])
    if ada and _RANK.get(ada, -1) > rank:
        rank = _RANK[ada]
    return LEVELS[rank]


def build_bonds_rank(source: list[dict], bonds_heter_by_isin: dict[str, dict]) -> dict[str, dict]:
    """מפתח -> {"אג\"ח": רמה}. מסלול בלי שום אג"ח מזוהה (רלוונטי) - לא מופיע."""
    worst_rank: dict[str, int] = {}
    for rec in source:
        if rec["Category"] not in BOND_CATEGORIES or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            track = row.get("מספר מסלול")
            if track is None or track == "":
                continue
            type_val = row.get(SECNO_TYPE_COL)
            if type_val is not None and type_val != "ISIN":
                continue  # "פנימי"/"אחר"/ריק/וכו' - לא ISIN, לא ניתן להצליב
            isin = row.get(SECNO_COL)
            if not isin or not isinstance(isin, str) or not isin.startswith("IL"):
                continue

            entry = bonds_heter_by_isin.get(isin)
            level = _bond_level(entry)
            if level is None:
                continue  # לא רלוונטי (ממשלתי/מק"מ)

            key = f"{rec['LegalId']}_{text_from(track)}"
            rank = _RANK[level]
            cur = worst_rank.get(key)
            if cur is None or rank < cur:
                worst_rank[key] = rank

    return {key: {'אג"ח': LEVELS[rank]} for key, rank in worst_rank.items()}
