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

# חלק מקוראי האוניברסיטה האירופית (Invesco, JustETF - כ-1,888/3,604 קרנות,
# יותר ממחצית!) אף פעם לא ממלאים asset_class (מגבלת המקור עצמו - לא שדה
# חסר במקרה). לפני שנותרים בלי סיווג, מנסים להסיק מניות/אג"ח משם הקרן +
# המדד - נבדק בפועל על כל ה-1,888: משתחזר סיווג בטוח ל-1,511 (80%), כשמה
# שנשאר לא-מסווג הוא כמעט אך ורק סחורות/מטבעות דיגיטליים/מזומן (לא ניתן,
# ולא כדאי, להכריע כמניות/אג"ח) - לא נבדק לקרנות אג"ח נסתרות שהוחמצו.
_EXCLUDE_NAME_TERMS = (
    "bitcoin", "ethereum", "crypto", "cardano", "solana", "physical gold", "physical silver",
    "digital asset", "commodity", "commodities", "agriculture", " etp", "etp ", "autocallable",
    "option", "overnight rate", "money market", "buffer", "carry", "livestock",
    "multi-strategy", "multi asset", "multi-asset", "infrastructure mlp",
)
_BOND_NAME_TERMS = (
    "bond", "treasury", "gilt", "sovereign", "credit", "coco", "contingent convertible",
    "floating rate note", "municipal", "govt", "government bond", "aggregate",
)


def _classify_by_name(name, benchmark_index) -> str | None:
    """'equity'/'bond'/None לפי מילות מפתח בשם הקרן/המדד - רק כשיש סימן
    סביר (לא ניחוש בברירת מחדל לגמרי חופשי): לא סחורה/קריפטו/מזומן/מובנה,
    ואז אג"ח לפי מילת-מפתח מפורשת, אחרת מניות (רוב ETF שאינו סחורה/אג"ח/
    קריפטו הוא מניות - סקטוריאלי/תמטי/פקטורי/אזורי)."""
    text = f"{name or ''} {benchmark_index or ''}".lower()
    if any(t in text for t in _EXCLUDE_NAME_TERMS):
        return None
    if any(t in text for t in _BOND_NAME_TERMS):
        return "bond"
    if "ucits etf" in text or "etf " in text or text.strip().endswith("etf"):
        return "equity"
    return None


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


# מנפיקות ETF אמריקאיות ידועות/גדולות מאוד שנמצאו חסרות מ-data/ETF/SEC/
# etf_exposure.json (נבדק בפועל, ר' missing_foreign_funds.py) - חלקן (SPY/
# QQQ/DIA/MDY) הן Unit Investment Trust ולא קרן '40 Act רגילה, ולכן כנראה
# לא מגישות N-PORT בכלל (המקור הסביר ביותר לאותו קובץ) - זו לא "תקלת
# איסוף" שאפשר לתקן באותו מקור, אלא מגבלה מבנית של סוג המכשיר. שאר הרשימה
# (SPLG/RSP/IYC/EEM/SCHD/VFVA/SPYD) כן אמורות להגיש N-PORT - למה הן חסרות
# מהקובץ הקיים לא ידוע (אין סקריפט מקור לבדוק) - כאן כפתרון-ביניים ודאי,
# לא כתחליף לכיסוי SEC מלא ועדכני (ר' תכנית העבודה בהודעת הסיכום).
# כל אחת מזוהה ודאית כמניות-100% מהשם/הטיקר הציבורי הידוע שלה (לא ניחוש) -
# S&P 500 / Nasdaq-100 / Dow / MidCap 400 / Equal-Weight / סקטור/פקטור/
# דיבידנד - כולן חשיפת מניות טהורה, בלי מרכיב אג"ח.
KNOWN_MAJOR_EQUITY_ETFS = {
    "US78462F1030": "SPY - SPDR S&P 500 ETF Trust",
    "US46090E1038": "QQQ - Invesco QQQ Trust (Nasdaq-100)",
    "US78467X1090": "DIA - SPDR Dow Jones Industrial Average ETF Trust",
    "US78467Y1073": "MDY - SPDR S&P MidCap 400 ETF Trust",
    "US78464A8541": "SPLG - SPDR Portfolio S&P 500 ETF",
    "US46137V3814": "RSP - Invesco S&P 500 Equal Weight ETF",
    "US4642875805": "IYC - iShares US Consumer Discretionary ETF",
    "US4642872349": "EEM - iShares MSCI Emerging Markets ETF",
    "US8085247976": "SCHD - Schwab US Dividend Equity ETF",
    "US9219358051": "VFVA - Vanguard US Value Factor ETF",
    "US78468R7888": "SPYD - SPDR S&P 500 High Dividend ETF",
}

# שוק יפני: אין לו כיסוי בשום מאגר קיים (לא אירופה, לא SEC - קרנות יפניות
# לא רשומות ב-SEC בכלל). כל 6 הקרנות שנמצאו חסרות (ר' missing_foreign_funds.py)
# הן קרנות מדד רחבות מוכרות היטב על ניקיי225/TOPIX/TOPIX-בנקים/Mid&Small -
# כולן חשיפת מניות יפניות טהורה בהגדרה (עוקבות מדד מניות) - זיהוי ודאי
# מהשם, לא ניחוש, בדיוק כמו הרשימה האמריקאית למעלה.
KNOWN_JAPAN_EQUITY_ETFS = {
    "JP3027710007": "iShares Core Nikkei 225 ETF",
    "JP3027630007": "Nomura ETF (Nikkei/TOPIX)",
    "JP3027620008": "Daiwa ETF TOPIX",
    "JP3040170007": "Nomura ETF Banks (TOPIX-17 Banks sector)",
    "JP3049420007": "Global X Japan Mid & Small Cap ETF (2837)",
    "JP3048120004": "iShares Core TOPIX ETF",
}

# עוגנים ידניים נוספים לקרנות ספציפיות שנמצאו בראש רשימת missing_foreign_funds.py
# (משקל מצטבר גבוה) אך לא זוהו בשום מאגר/שכבה אחרת - השם המדווח בדוח קצוץ/
# מקוצר (למשל "NB GLB FLEX CRE" חתוך מ-"...Flexible Credit Fund") ולכן גם
# _classify_by_report_name לא תופס אותן, אבל זהות הקרן ודאית מהשם החלקי +
# ידע ציבורי (משפחת הקרן, לא ניחוש) - אותו עיקרון כמו KNOWN_MAJOR_EQUITY_ETFS.
KNOWN_EQUITY_FUNDS_OTHER = {
    "US5007673065": "KraneShares CSI China Internet ETF (KWEB)",
    "LU2126068639": "Kotak Funds - India Midcap Fund",
    "LU0675383409": "Kotak Funds - India Midcap Fund (סדרת יחידות נוספת)",
}
KNOWN_BOND_FUNDS_OTHER = {
    "LU0569863243": "UBAM - Global High Yield Solution",
    "IE00BMD7Z621": "Neuberger Berman Global Flexible Credit Fund",
    "IE0034085260": "PIMCO GIS Global Investment Grade Credit Fund",
    "IE00B8HR7G48": "Neuberger Berman Global Senior Floating Rate Income Fund",
}


def build_isin_fractions(etf_universe: list[dict], sec_exposure: list[dict]) -> dict[str, dict[str, float]]:
    """ISIN (מנורמל) -> {"equity": שבר 0..1, "bond": שבר 0..1}. SEC (שיעורים
    מדויקים) דורס את האוניברסיטה האירופית (סיווג קטגורי בלבד: Equity->1.0,
    Fixed Income/Bond->0.0, שאר הסיווגים [Multi Asset/Commodity/...] מדולגים -
    לא ניתן להסיק מהם שבר מניות/אג"ח בינארי אמין)."""
    out: dict[str, dict[str, float]] = {
        isin: {"equity": 1.0, "bond": 0.0}
        for isin in (*KNOWN_MAJOR_EQUITY_ETFS, *KNOWN_JAPAN_EQUITY_ETFS, *KNOWN_EQUITY_FUNDS_OTHER)
    }
    for isin in KNOWN_BOND_FUNDS_OTHER:
        out[isin] = {"equity": 0.0, "bond": 1.0}
    for rec in etf_universe:
        isin = _isin_key(rec.get("isin"))
        if isin is None:
            continue
        ac = (rec.get("asset_class") or "").strip().lower()
        if ac == "equity":
            out[isin] = {"equity": 1.0, "bond": 0.0}
        elif ac in BOND_ASSET_CLASSES:
            out[isin] = {"equity": 0.0, "bond": 1.0}
        else:
            by_name = _classify_by_name(rec.get("name"), rec.get("benchmark_index"))
            if by_name == "equity":
                out[isin] = {"equity": 1.0, "bond": 0.0}
            elif by_name == "bond":
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


# שכבת מוצא-אחרון: קרנות "חוץ" שלא נמצאו בשום מאגר חיצוני (לא אירופה, לא SEC,
# לא עוגן ידני) - מנסים להסיק מניות/אג"ח מהשם עצמו כפי שהוא מדווח בדוח
# הפנסיוני (row["שם נייר ערך"], לא שם רשמי מלא - לרוב מקוצר/מקוצר-אוטומטית
# ע"י מערכת המשמורת, למשל "PIMCO HIGH YIELD BO"/"NEU BER GL SE FL RT").
# שמרני בהרבה מ-_classify_by_name: *לא* ברירת-מחדל-למניות סתם על כל "ETF" -
# שם מקוצר/לא רשמי נותן פחות ודאות, ולכן נדרש מונח מובהק (אג"ח או מניות)
# ולא רק העדר מונח-אג"ח. מדולג (לא מסווג) כשאין מונח מובהק משני הצדדים.
_REPORT_NAME_BOND_TERMS = (
    "bond", "treasury", "gilt", "sovereign", "high yiel", "senior loan", "corp debt",
    "floating rate", "credit", "govt", "municipal", "debenture",
)
_REPORT_NAME_EQUITY_TERMS = (
    "equity", "eqy", "growth", "value", "dividend", "dvd", "biotech", "technology",
    "thematic", "rotation", "water", "agtech", "food innovat", "momentum", "quality",
    "factor", "equal weight", "msci", "s&p", "russell", "nasdaq", "topix", "nikkei",
    "stoxx", "ftse", "mid cap", "small cap", "life scie", "discretionary", "discret",
    "meme", "uranium", "index fund", "index equity",
)


def _classify_by_report_name(name: str | None) -> str | None:
    if not name:
        return None
    text = name.lower()
    if any(t in text for t in _REPORT_NAME_BOND_TERMS):
        return "bond"
    if any(t in text for t in _REPORT_NAME_EQUITY_TERMS):
        return "equity"
    return None


def classify_from_report_names(source: list[dict]) -> dict[str, dict[str, float]]:
    """ISIN -> {"equity":.., "bond":..} לפי "שם נייר ערך" כפי שמדווח בגיליונות
    'קרנות סל'/'קרנות נאמנות' עצמם - מיועד כשכבת מוצא-אחרון (ר' תיעוד למעלה),
    לא כתחליף למאגרים החיצוניים."""
    out: dict[str, dict[str, float]] = {}
    for rec in source:
        if rec["Category"] not in ("קרנות סל", "קרנות נאמנות") or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            isin = _isin_key(row.get("מספר נייר ערך"))
            if isin is None or isin in out:
                continue
            cls = _classify_by_report_name(row.get("שם נייר ערך"))
            if cls == "equity":
                out[isin] = {"equity": 1.0, "bond": 0.0}
            elif cls == "bond":
                out[isin] = {"equity": 0.0, "bond": 1.0}
    return out


def collect_unclassified_foreign_isins(funds: list[dict], isin_fractions: dict[str, dict[str, float]]) -> list[str]:
    """ISIN-ים ייחודיים של קרנות "חוץ" שעדיין לא מסווגים באף שכבה קיימת -
    מיועד להזנה לשכבה האחרונה, היקרה (sec_nport_reference.py: OpenFIGI +
    N-PORT חי), כדי להריץ אותה רק על מה שבאמת חסר, לא על כל קרנות החוץ."""
    out: set[str] = set()
    for row in funds:
        if row["סוג"] != FOREIGN_TYPE:
            continue
        isin = _isin_key(row.get("מספר קרן"))
        if isin and isin not in isin_fractions:
            out.add(isin)
    return list(out)


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
