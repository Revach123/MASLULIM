"""חשיפה למניות/אג"ח לקרנות זרות שאינן ישראליות ואינן נסחרות ב-TASE: "נתוני
קרנות" (funds_reference.py) מכיל רק קרנות ישראליות + 40 קרנות חוץ נסחרות
ב-TASE (כולן ISIN אירי - אומת בפועל). קרן זרה שמוחזקת ישירות (למשל ETF
אמריקאית שנסחרת רק ב-NYSE/Nasdaq, לא חוצה-רשומה ב-TASE) לא מזוהה בכלל
ע"י funds.py._classify - נופלת ל"חוץ" (fund_number = ה-ISIN הגולמי, לא
מספר קרן) בלי שום סיווג מניות/אג"ח, ונעלמת מהחשיפה המחושבת (נמצא בפועל
בבדיקת validate_equity_exposure.py: מסלולים עם חשיפה רשמית ~100% למניות
דרך קרנות כאלה, מחושב 0%).

שני מאגרים ב-revach סוגרים את הפער, ללא צורך בשינוי ב-revach עצמו:

1. אוניברסיטת ETF אירופית/גלובלית (iShares/Amundi/Invesco/SPDR/Vanguard/
   XTrackers/JustETF ועוד, בעיקר אירית/לוקסמבורגית) - /api/etf-funds,
   מוגן באותו guard() כמו /api/tracks; X-Match-Key עוקף (כמו
   tracks_reference.py). סיווג קטגורי בלבד (asset_class).
2. ETF אמריקאיות רשומות ב-SEC (~4,400 קרנות, כנראה נגזר מדיווחי N-PORT) -
   data/ETF/SEC/etf_exposure.json, קובץ סטטי בריפו (לא endpoint) - נשלף
   דרך GitHub Contents API עם PAT, בדיוק כמו funds_reference.py. שיעורי
   חשיפה מדויקים (eqTotalPct/bondTotalPct) - עדיף על הסיווג הקטגורי.
"""
import os

import requests

from .excel_io import to_ratio

ETF_FUNDS_URL = "https://revach.pages.dev/api/etf-funds"
MATCH_KEY_ENV = "REVACH_MATCH_KEY"

SEC_CONTENTS_URL = "https://api.github.com/repos/Revach123/revach/contents/data/ETF/SEC/etf_exposure.json"
TOKEN_ENV = "PAT"

FOREIGN_TYPE = "חוץ"
EQUITY_SIVEG = 'קרן מחקה - מניות בחו"ל'
BOND_SIVEG = 'קרן מחקה - אג"ח בחו"ל'
PLACEHOLDER_PCT = {"", "ריק במקור", "סוף מידע"}

BOND_ASSET_CLASSES = {"fixed income", "bond"}


def fetch_etf_universe(session: requests.Session | None = None) -> list[dict]:
    key = (os.environ.get(MATCH_KEY_ENV) or "").strip()
    if not key:
        raise SystemExit(f"[foreign_etf] משתנה הסביבה {MATCH_KEY_ENV} לא מוגדר")
    s = session or requests.Session()
    r = s.get(ETF_FUNDS_URL, headers={"X-Match-Key": key}, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_sec_etf_exposure(session: requests.Session | None = None) -> list[dict]:
    token = (os.environ.get(TOKEN_ENV) or "").strip()
    if not token:
        raise SystemExit(f"[foreign_etf] משתנה הסביבה {TOKEN_ENV} לא מוגדר")
    s = session or requests.Session()
    r = s.get(SEC_CONTENTS_URL, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw",
    }, timeout=60)
    r.raise_for_status()
    return r.json()


def _isin_key(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    return s or None


def build_isin_fractions(etf_universe: list[dict], sec_exposure: list[dict]) -> dict[str, dict[str, float]]:
    """ISIN (מנורמל) -> {"equity": שבר 0..1, "bond": שבר 0..1}. SEC (שיעורים
    מדויקים) דורס את האוניברסיטה האירופית (סיווג קטגורי בלבד: Equity->1.0,
    Fixed Income/Bond->0.0, שאר הסיווגים [Multi Asset/Commodity/...] מדולגים -
    לא ניתן להסיק מהם שבר מניות/אג"ח בינארי אמין)."""
    out: dict[str, dict[str, float]] = {}
    for rec in etf_universe:
        isin = _isin_key(rec.get("isin"))
        if isin is None:
            continue
        ac = (rec.get("asset_class") or "").strip().lower()
        if ac == "equity":
            out[isin] = {"equity": 1.0, "bond": 0.0}
        elif ac in BOND_ASSET_CLASSES:
            out[isin] = {"equity": 0.0, "bond": 1.0}

    for rec in sec_exposure:
        isin = _isin_key(rec.get("isin"))
        if isin is None:
            continue
        eq, bd = rec.get("eqTotalPct"), rec.get("bondTotalPct")
        if eq is None and bd is None:
            continue
        out[isin] = {"equity": (eq or 0.0) / 100, "bond": (bd or 0.0) / 100}
    return out


def build_foreign_equity(funds: list[dict], isin_fractions: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """מפתח -> {"קרן מחקה - מניות בחו\"ל": ..., "קרן מחקה - אג\"ח בחו\"ל": ...},
    לשורות "חוץ" בלבד (לא ישראליות, לא נסחרות ב-TASE - 'מספר קרן' הוא ה-ISIN
    הגולמי, ר' funds.py._classify) שמזוהות באחד משני המאגרים. לא נוגע בקרנות
    IL/נסחרת - אלה כבר מטופלות (או לא) ע"י funds_il.py בנפרד, בלי חפיפה
    אפשרית (כל שורה מסווגת לדיוק אחד מ-IL/נסחרת/חוץ)."""
    sums: dict[str, dict[str, float]] = {}
    for row in funds:
        if row["סוג"] != FOREIGN_TYPE:
            continue
        raw_pct = row.get("שיעור מסך נכסי ההשקעה")
        if isinstance(raw_pct, str) and raw_pct in PLACEHOLDER_PCT:
            continue
        pct = to_ratio(raw_pct)
        if pct is None:
            continue
        frac = isin_fractions.get(_isin_key(row.get("מספר קרן")))
        if frac is None:
            continue
        key = row["מפתח"]
        d = sums.setdefault(key, {})
        if frac["equity"]:
            d[EQUITY_SIVEG] = d.get(EQUITY_SIVEG, 0.0) + pct * frac["equity"]
        if frac["bond"]:
            d[BOND_SIVEG] = d.get(BOND_SIVEG, 0.0) + pct * frac["bond"]
    return sums
