"""חשיפה אמיתית לנגזרים: תיקון לבאג לפיו "שיעור מסך נכסי ההשקעה" שמדווח
בגיליונות "חוזים עתידיים" ו"לא סחיר נגזרים אחרים" (עסקאות החלף/פורוורד)
משקף רק את השווי ההוגן של המכשיר (מרווח/רווח-הפסד שוטף) - לא את החשיפה
הכלכלית שהוא יוצר. לחוזה עתידי אין עלות רכישה (leverage מובנה): השווי ההוגן
הוא רק הרווח/הפסד שנצבר, בעוד שהחוזה בפועל שולט בנכס בסיס ששווה פי כמה
וכמה. אותו הדבר לעסקת פורוורד/סוואפ: השווי ההוגן נטו הוא ההפרש הקטן בין
שתי הרגליים, לא הסכום (הנקוב) שכל רגל שלה חושפת.

מקור: לא חלק מ-Autopilot_Section1.m - הרחבה חדשה, לפי הנחיית המשתמש
("הנתונים הם שיעור מנכסים, לא חשיפה - בפרט בחוזים עתידיים ועסקאות החלף").

אישוש רגולטורי (לא רק היסק אמפירי): החוזר המאוחד, שער 5 חלק 4 פרק 3,
נספח 5.4.3.2 חלק ג' - "רשימת נכסים ברמת הנכס הבודד", סעיף 4.22 "לא סחיר
נגזרים אחרים", קובע במפורש שהעמודות "מספר נייר ערך", "מטבע", "ערך נקוב",
"שער", "שווי הוגן", "שיעור מנכסי אפיק ההשקעה" ו"שיעור מסך נכסי ההשקעה"
מדווחות "עבור כל רגל בנפרד" - כלומר "שיעור מסך נכסי ההשקעה" הוא באמת
לפי-רגל (לא לפי-עסקה), ו"ערך נקוב" מוגדר שם (בסעיף ההגדרות הכללי) כ"מספר
היחידות" (לא סכום נקוב במטבע) - בדיוק ההנחות שהקוד למטה בונה עליהן.
נספח 5.4.3.5 - "אופן חישוב חשיפות בדוחות חודשיים" - קובע כעיקרון כללי
לחישוב חשיפה בנגזרים ש"חישוב החשיפה יעשה... על פי... אקוויוולנט של נכס
הבסיס בחוזה" (ערך נקוב × שער נכס הבסיס), לא לפי השווי ההוגן המדווח - מאשש
את העיקרון המרכזי של המודול הזה (לא רק ניחוש סביר).

שיטה
----
1. שווי כולל נכסי מסלול (באלפי ש"ח): לא מדווח במפורש בגיליונות הפרטניים,
   אבל ניתן לגזור אותו מהיחס שמגדיר את "שיעור מסך נכסי ההשקעה" בכל שורה
   בכל גיליון (כולל נגזרים): pct = שווי_הוגן / שווי_כולל. לכל מסלול
   לוקחים את שווי_הוגן/pct מהשורה עם |שווי הוגן| הגדול ביותר (יציבה
   נומרית יותר משורות עם pct זעיר).

2. חוזים עתידיים: החשיפה הכלכלית = ערך נקוב (יחידות, עם סימן - קניה/מכירה)
   כפול שער נייר הערך (מחיר/רמת מדד) כפול שער חליפין. זו בדיוק אותה נוסחה
   ששווי מניה/אג"ח בדוחות האלה מחושב לפיה (ערך נקוב × שער [× שער חליפין]),
   רק שעבור חוזה עתידי היא נותנת את השווי שהחוזה *שולט* בו (notional) -
   לא את "השווי ההוגן" המדווח (מרג'ין+רווח/הפסד, קטן בהרבה כמעט תמיד).
   מגבלה מתועדת: אין בדוח "מכפיל חוזה" (למשל $50/נקודה ב-ES future) - אם
   "ערך נקוב" הוא מספר החוזים הגולמי בלי הכפלה במכפיל, החשיפה בפועל
   תת-מוערכת. אין בדוח, ואין במקור אחר בריפו, דרך לאמת מכפיל per-instrument.

   שתי תקלות עקביות נוספות שנמצאו בבדיקה בפועל על כל הארכיון (לא הודעה
   תיאורטית - כל אחת אומתה בנתונים אמיתיים):
   - JPY: חלק מהמגישים רושמים "שער חליפין" ליין לפי מוסכמת "יחס ל-100"
     (כמו שער בנק ישראל) במקום שער ליחידה - לא עקבי אפילו בתוך אותו מגיש
     (רוב השורות ~0.018, חלקן ~1.83 - פי 100 בדיוק). מזוהה ומתוקן לפי סף
     (שער אמיתי ליין תמיד נמוך בהרבה מ-1).
   - "התחייבות"-Index (רגל מימון סינתטית, למשל "09/2026 JPM ESU6 Index
     התחייבות"): "שער נייר הערך" קבוע בדיוק על 100 - מוסכמת ערך-נקוב-100
     (כמו אג"ח), לא רמת מדד גולמית. יחידות בסדר גודל של מיליונים עם המוסכמה
     הרגילה (יחידות × 100 × שער) מייצרות חשיפה מנופחת פי 100 - מזוהות לפי
     שער == 100.0 בדיוק ומטופלות כמו אג"ח (יחידות/100 × שער, לא יחידות×שער).

3. עסקאות החלף/פורוורד ("לא סחיר נגזרים אחרים"): כל עסקה מדווחת בשתי
   רגליים, כל אחת עם "ערך נקוב" ו"שער חליפין" משלה. החשיפה = ממוצע הערך
   המוחלט (בש"ח) של שתי הרגליים - בד"כ קרובות זו לזו (אותה עסקה, שתי
   יחידות מדידה); הממוצע מנטרל סטיות קטנות מתנודות שער/ריבית מאז שהעסקה
   ננעלה.

4. התוצאה מיועדת *להחליף* (לא להצטרף ל-) שתי הקטגוריות האלה בפלט של
   category_pct.build_category_pct - שאר הקטגוריות (מזומן, אג"ח, מניות,
   קרנות...) כבר משקפות שווי שוק אמיתי, אין בהן את הבאג.
"""
import re

from .excel_io import to_ratio
from .sheet_source import PCT_COL
from .option_delta_pricing import price_as_of, resolve_option_delta
from .option_ticker_parse import is_call_option, parse_underlying
from .swap_index_pricing import resolve_current_price

FAIR_VALUE_COL = 'שווי הוגן (באלפי ש"ח)'
SWAP_NET_FAIR_VALUE_COL = 'שווי הוגן (נטו באלפי ש"ח)'

# תקרת סבירות לשורה בודדת: חשיפה נוציונלית שמשתמעת ליותר מ-300% משווי המסלול
# כולו ממכשיר נגזר *יחיד* אינה סבירה עבור מסלול פנסיוני מפוזר - ונצפה בפועל
# (למשל אג"ח סינתטית עם "ערך נקוב" במוסכמת שווי-נקוב-100, לא מספר חוזים גולמי,
# שנופלת על אותו שם עמודה כמו חוזה CME רגיל). בשורה כזו לא ניתן לסמוך על
# הנוסחה (מוסכמת היחידות/מחיר של השורה הזו כנראה שונה) - נופלים חזרה לערך
# שהדוח עצמו מדווח (שווי הוגן/שווי כולל) לשורה הספציפית הזו בלבד, כפי שהיה
# לפני התיקון - עדיף על תוצאה מנופחת שאי אפשר לסמוך עליה.
SANITY_CAP = 3.0

# תקרת מנוף לשורה בודדת (חוזים עתידיים): נמצא בבדיקה שלמגישים שונים יש
# מוסכמות שונות/לא-עקביות ל"שער נייר הערך" (לא רק מוסכמת ערך-נקוב-100 -
# גם מגישים ששמים את המחיר בקנה מידה שרירותי אחר, למשל פי 100 מהנדרש, מבלי
# שזה בולט ביחס לשווי המסלול הכולל אם המסלול גדול מספיק). בדיקה יחסית
# עמידה-למגיש: חשיפה נוציונלית אמיתית של חוזה ממונף היא בד"כ כפולה סבירה
# מהשווי ההוגן (המרווח) שאותה שורה בדיוק מדווחת - שיעורי מרג'ין סטנדרטיים
# לחוזי מדד/ריבית נעים בד"כ 1%-15% מהנוציונל, כלומר יחס נוציונל/שווי-הוגן
# עד בערך פי 100. חריגה מכך היא סימן חזק שקנה המידה של יחידות/מחיר בשורה
# הזו שונה ממה שהנוסחה מניחה.
#
# עודכן מ-75 ל-120 לפי ניתוח בפועל על כל שורות "חוזים עתידיים" בארכיון עם
# שווי הוגן חיובי (n=4,314): חציון יחס נוציונל/שווי-הוגן הוא בדיוק 100.0.
# ניסיון ראשון (75->120 בלבד) הוחמר בפועל ב-CI (10.246->11.904 נק' אחוז),
# משתי סיבות נפרדות שתוקנו כל אחת בנפרד - לא ע"י שינוי הסף עצמו:
# 1. מחיר שלילי לא-פתור (ר' ה-else למטה) שנתפס במקרה ע"י תקרה נמוכה, לא
#    בכוונה - מטופל עכשיו במפורש, בלי תלות ב-LEVERAGE_CAP בכלל.
# 2. תקרת-SANITY_CAP הייתה קיימת ל-swap *ברמת המסלול כולו* (capped, למטה)
#    אבל לא לחוזים עתידיים (רק ברמת-שורה) - נמצא בפועל (520028390_485/
#    520027251_484 ודומיהם) שורות זוגיות שכל אחת בנפרד עוברת LEVERAGE_CAP
#    בקלות, אבל סכומן המצטבר ברמת המסלול מגיע ל-700%+. עכשיו קיימת אותה
#    תקרת-מסלול גם לחוזים עתידיים (ר' capped ב-_futures_exposure).
LEVERAGE_CAP = 120.0

FUTURES_CATEGORY = "חוזים עתידיים"
SWAP_CATEGORY = "לא סחיר נגזרים אחרים"
OPTIONS_LISTED_CATEGORY = "אופציות"
OPTIONS_OTC_CATEGORY = "לא סחיר אופציות"
OPTIONS_CATEGORIES = (OPTIONS_LISTED_CATEGORY, OPTIONS_OTC_CATEGORY)
DERIVATIVE_CATEGORIES = (FUTURES_CATEGORY, SWAP_CATEGORY, *OPTIONS_CATEGORIES)

FUT_UNITS_COL = "ערך נקוב (יחידות)"
FUT_FX_COL = "שער חליפין"
FUT_PRICE_COL = "שער נייר הערך"
FUT_CURRENCY_COL = "מטבע פעילות"
FUT_TICKER_COL = "מספר נייר ערך"
FUT_UNDERLYING_COL = "נכס בסיס"

# "נכס בסיס"/"סוג הנכס" (חוזים/סוואפים/אופציות בהתאמה) - אותו ערך מדויק
# בשלושת הגיליונות, נבדק בפועל מול דוח אמיתי (512065202_gm_0226.xlsx).
# משמש לבניית "אזור חשיפה למניות" בדשבורד (ר' main.py) - לבודד את החלק
# שמקורו בנכס-בסיס מניות/מדדי-מניות בלבד מתוך כל קטגוריית נגזר.
EQUITY_UNDERLYING = "מניות לרבות מדדי מניות"

# עמודות הפלט הנוספות ("אזור חשיפה למניות") - לא מחליפות את הקטגוריות
# הקיימות (FUTURES_CATEGORY/SWAP_CATEGORY/OPTIONS_*), רק מוסיפות פילוח
# לפי נכס-בסיס=מניות בלבד, לצורך תצוגה בדשבורד.
FUTURES_EQUITY_COLUMN = "חוזים עתידיים - מניות"
OPTIONS_EQUITY_COLUMN = "אופציות - מניות"

# ניסוי (לא מאומת חיצונית מעבר למה שתועד למטה - לא למזג בלי בדיקת MAE אמיתית):
# "שער נייר הערך" שלילי בשורת חוזה עתידי הוא בלתי אפשרי מתמטית (רמת מדד/מחיר
# לא יכולה להיות שלילית) - נמצא בפועל בדיוק אותו תבנית-תקלה (מחיר שבור קבוע
# לאותו נייר בכל הארכיון, לא ניתן לכייל מרבעון אחר) עבור 23 מספרי-נייר שונים
# ברחבי הארכיון, לא רק ב-512065202/"קיימות". מטופל ע"י טבלת (רגקס-טיקר,
# סימול-מחיר-חי, מכפיל$) - הראשון שמתאים לניר הערך הספציפי.
#
# SLB (E-mini S&P 500 ESG): מזוהה חיצונית (עמוד אחזקות SPDR S&P 500 ESG ETF,
# מחזיק SLBZ6 תחת "EMINI S+P500 ESG DEC26") + מכפיל E-mini סטנדרטי ($50/נק')
# מאושר חיצונית (עמוד CME הרשמי: E-mini S&P 500 "one fifth the size of
# standard S&P futures", שהוא $250/נק'). בדיקת סבירות (~443.749 חוזים,
# S&P~6879 ב-2026-02-27, פי 50, שער דולר 2.978) -> ~455M ש"ח מול ~501M ש"ח
# נכסי המסלול, קרוב ל"חשיפה למניות" הרשמית (~99%) - CI-אומת (MAE שופר).
#
# ES/NQ: אותה תבנית מספר-נייר (רוט CME + אות-חודש + ספרת-שנה), רוטים
# סטנדרטיים ומתועדים פומבית ללא צורך באימות נוסף - ES=E-mini S&P 500 ($50/נק',
# CME), NQ=E-mini Nasdaq-100 ($20/נק', CME - שונה מ-SLB/ES בכוונה, לא טעות).
#
# CL (WTI Crude Oil, NYMEX/CME): מכפיל חוזה סטנדרטי ומתועד פומבית = 1{,}000
# חביות (כלומר $1{,}000 לכל $1/חבית בשער) - לא "נקודות מדד" כמו שאר הרשימה,
# אבל אותה נוסחה (units * price_usd_per_contract * fx) עובדת זהה.
#
# כל המכפילים האלה הנחות-מבוססות-ידע-ציבורי (לא ניתנות לאימות ישיר מתוך הדוח
# עצמו) - ר' תקרת-SANITY_CAP למטה כרשת ביטחון אם הנחה כלשהי שגויה למסלול
# ספציפי. טווח ה-MSCI World/EM/ACWI/TSX/Treasury (עוד ~14 מספרי-נייר שנמצאו
# בסריקת הארכיון) נשאר מחוץ לטבלה במכוון - מכפיל/זהות מדד לא מאומתים חיצונית
# עדיין לאותם רוטים (בניגוד ל-ES/NQ/CL/SLB שהם רוטי CME מוכרים וחד-משמעיים).
_CORRUPTED_FUTURES_TICKERS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"^SLB[A-Z]\d$"), "^GSPC", 50.0),    # E-mini S&P 500 ESG
    (re.compile(r"^ES[A-Z]\d$"), "^GSPC", 50.0),     # E-mini S&P 500
    (re.compile(r"^NQ[A-Z]\d$"), "^NDX", 20.0),      # E-mini Nasdaq-100
    (re.compile(r"^CL[A-Z]\d$"), "CL=F", 1000.0),    # WTI Crude Oil (NYMEX)
]


def _resolve_corrupted_futures_price(ticker, report_date) -> float | None:
    if not ticker or report_date is None:
        return None
    ticker = str(ticker)
    for pattern, price_symbol, multiplier in _CORRUPTED_FUTURES_TICKERS:
        if pattern.match(ticker):
            live_price = price_as_of(price_symbol, report_date)
            if live_price is not None:
                return live_price * multiplier
            return None
    return None

SWAP_LEGS = (
    {"units": "ערך נקוב (רגל 1)", "fx": "שער חליפין (רגל 1)", "currency": "מטבע פעילות (רגל 1)"},
    {"units": "ערך נקוב (רגל 2)", "fx": "שער חליפין (רגל 2)", "currency": "מטבע פעילות (רגל 2)"},
)
SWAP_UNDERLYING_PRICE_COL = "שער נכס הבסיס במועד ההתקשרות בעסקה"
SWAP_TICKER_COL = "טיקר"
SWAP_ASSET_TYPE_COL = "סוג הנכס"
SWAP_EQUITY_ASSET_TYPE = "מניות לרבות מדדי מניות"
SWAP_MAIN_TYPE_COL = "מאפיין עיקרי"  # "Unfunded Swap"/"Funded Total Return/Equity Swap"/... - נבדק בפועל
SWAP_LABEL_COL = SWAP_MAIN_TYPE_COL
FUNDED_SWAP_CATEGORY = "החלף עם מימון (Funded)"
UNFUNDED_SWAP_CATEGORY = "החלף בלי מימון (Unfunded)"

# "Funded" מול "Unfunded" (מאפיין עיקרי) נראים כשני מבנים כלכליים שונים
# לגמרי: ב-"Unfunded Swap" (512065202 - הפריט שאומת במקור ב-46114a8), רגל 1
# היא כמות *יחידות גולמית* של נכס הבסיס (צריכה הכפלה בשער כדי להיות
# ברת-השוואה לרגל 2). ב-"Funded Total Return/Equity Swap" (513611509,
# Yelin Lapidot S&P 500 tracker), רגל 1 היא כבר נוציונל במטבע (בדיוק כמו
# רגל 2, לפני סימן) - בלי צורך בהכפלה כלל.
#
# אבל (תיקון-משנה חשוב, נמצא בבדיקה נוספת על 513173393/אלטשולר שחם):
# התווית "מאפיין עיקרי" לבדה *אינה מספיק אמינה* כדי להכריע איזו משתי
# הפרשנויות נכונה - "Unfunded Total Return/Equity Swap" (התווית הנפוצה
# ביותר בארכיון, 11,218 שורות!) יכולה להיות "רגל 1 כבר נוציונל" בדיוק
# כמו Funded אצל מגיש מסוים, בזמן שאצל מגישים אחרים תחת אותה תווית בדיוק
# רגל 1 באמת יחידות גולמיות (התבנית המקורית שאומתה). לכן ההחלטה בפועל
# היא לא לפי is_funded (התווית) אלא לפי used_priced - ההשוואה עצמה בין
# הפרשנויות מול רגל 2, ברמת השורה הבודדת (ר' קוד למטה) - is_funded נשאר
# רק לפילוח הדיאגנוסטי (funded_sums/unfunded_sums), לא לקביעת קנה-המידה.
#
# שני באגים נובעים מהחלת ההנחה "רגל 1 = יחידות גולמיות" על שורה שבה
# used_priced=False בפועל (רגל 1 כבר נוציונל):
# 1. leg1_live (תמחור-חי): מכפיל רגל 1 *שוב* במחיר המדד החי - הכפלה כפולה
#    שמייצרת מספר דמיוני (נבדק בפועל: ~1.5 מיליארד ש"ח על שורת swap עם
#    נוציונל אמיתי ~100 מיליון - פי ~15,000), שנופל אוטומטית ב-SANITY_CAP
#    חזרה ל-row_pct הזעיר.
# 2. LEVERAGE_CAP (יחס נוציונל/שווי-הוגן-נטו): רלוונטי רק כש-used_priced
#    (זו הדרך היחידה שקנה-המידה של "שער נכס הבסיס" נכנס לחישוב בכלל).
#    כש-used_priced=False, שווי הוגן קטן/כמעט-אפס ביחס לנוציונל הוא
#    לגיטימי (Reset תקופתי, או Unfunded-בלי-Reset שנמצא בפועל שגם יכול
#    לעבור דרך fv≈0) - לא סימן לקנה-מידה שגוי, כי הנוציונל כבר אומת ישירות
#    מול רגל 2 (ההשוואה למעלה). נבדק בפועל (513173393_14865): 5 שורות
#    used_priced=False, יחס נוציונל/fv נע 10.7x עד 1893.6x (כולן legitimate) -
#    נוציונל אמיתי מצטבר 41.2% מהמסלול, מחושב בפועל (לפני התיקון) רק 1.11%.
_FUNDED_SWAP_PREFIX = "funded"


def _is_funded_swap(main_type) -> bool:
    return str(main_type or "").strip().lower().startswith(_FUNDED_SWAP_PREFIX)
# שם העמודה עצמו (לפי החוזר: שער החליפין/נכס הבסיס לנגזרים לא סחירים מוצג
# "נכון למועד ההתקשרות בעסקה") מאשר שזהו מחיר נכס הבסיס *בפתיחת העסקה*, לא
# מחיר שוק עדכני - זה בדיוק ההסבר לכך שרגל1×מחיר זה שווה לרגל2 (שתי הרגליים
# נעולות לאותו נוציונל מקורי). מגבלה ידועה: לעסקת סוואפ ישנה שנפתחה הרבה
# לפני תאריך הדוח, החשיפה הכלכלית ה"חיה" (הנגזרת ממחיר השוק הנוכחי) עשויה
# לסטות מהנוציונל המקורי הזה ככל שהשוק זז מאז ההתקשרות - אין בדוח עמודת
# "מחיר נוכחי" נפרדת לרגל 1 כדי לתקן זאת.

# JPY: נמצא בבדיקה שחלק מהמגישים רושמים את שער החליפין לפי מוסכמת "יחס ל-100
# יין" (כמו שער בנק ישראל ליין) במקום שער ליחידה - אותו קובץ/מגיש לא עקבי:
# ברוב השורות 0.018-ish (נכון), בחלקן 1.83-ish (פי 100, שגוי). השער האמיתי
# ליין תמיד נמוך בהרבה מ-1 - כל ערך מעל הסף הוא ודאי המוסכמה השגויה.
JPY_100_THRESHOLD = 0.5

# כל מטבע זר (לא ILS) עם שער חליפין קרוב ל-1.0 הוא בהכרח פלייסהולדר שגוי -
# אין מטבע שנסחר קרוב ל-1:1 מול ש"ח (נמצא בפועל: USD/EUR ברגל 1 של חלק
# מהמגישים, כשהשער האמיתי מדווח בעמודה אחרת - "שער הנגזר במועד ההתקשרות
# בעסקה" - שלא תמיד קיימת/עקבית מספיק כדי לסמוך עליה). מטפלים בזה לא
# בתיקון (אין ערך אמין להציב), אלא בפסילת הרגל - ממוצעים רק את הרגליים
# התקינות, ובלי אף רגל תקינה נופלים לשווי ההוגן הנטו כמו כל מקרה גבולי.
FOREIGN_FX_PLACEHOLDER_TOL = 0.01

# רגל-מימון סינתטית ("...Index התחייבות"): "שער נייר הערך" קבוע בדיוק על 100 -
# מוסכמת ערך-נקוב-100 כמו אג"ח (ראו bonds_rank/מניות: value = units*price/100),
# לא רמת מדד גולמית. יחידות בסדר גודל מיליונים + הנוסחה הרגילה (בלי /100)
# מייצרות חשיפה מנופחת פי 100 בדיוק - מזוהה לפי שער == 100.0 בדיוק.
PAR_QUOTED_PRICE = 100.0

# אופציות ("אופציות"/"לא סחיר אופציות"): לפי הרגולטור (אושר בבדיקה, לא
# הנחה - ר' חיפוש רשת 9.28.2026), החשיפה מחושבת לפי מודל בלק-שולס עם דלתא -
# לא לפי units×מחיר פשוט כמו חוזים עתידיים (ל"שער נייר הערך" באופציה יש
# משמעות אחרת: זו פרמיית האופציה עצמה, לא מחיר נכס הבסיס - אומת בפועל:
# units×שער/100×fx ≈ שווי הוגן בדיוק, מוסכמת אגורות כמו PAR_QUOTED_PRICE).
# דלתא מחושבת ב-option_delta_pricing.py (תנודתיות ריאליזד כקירוב ל-IV,
# ר' אזהרה שם). טיקר נכס-הבסיס מזוהה מ-"שם נייר ערך" (option_ticker_parse,
# אין עמודת טיקר נפרדת כמו בסוואפים) - כשלא מזוהה, נופלים לשווי-הוגן.
OPT_NAME_COL = "שם נייר ערך"
OPT_UNDERLYING_COL = "נכס בסיס"
OPT_EQUITY_UNDERLYING = "מניות לרבות מדדי מניות"
OPT_STRIKE_COL = "שער מימוש"
OPT_EXPIRY_COL = "תאריך פקיעה"
OPT_UNITS_COL = "ערך נקוב (יחידות)"
OPT_FX_COL = "שער חליפין"
OPT_CURRENCY_COL = "מטבע פעילות"


def _normalize_fx(currency, fx: float | None) -> float | None:
    if fx is None:
        return None
    if currency == "JPY" and fx > JPY_100_THRESHOLD:
        return fx / 100
    if currency and currency != "ILS" and abs(fx - 1.0) < FOREIGN_FX_PLACEHOLDER_TOL:
        return None
    return fx


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", ""))
    except ValueError:
        return None


def total_assets_by_key(source: list[dict]) -> dict[str, float]:
    """מפתח -> שווי כולל נכסי מסלול (באלפי ש"ח), נגזר מ-שווי הוגן/שיעור מסך
    נכסי ההשקעה של השורה עם |שווי הוגן| הגדול ביותר לאותו מסלול."""
    best: dict[str, tuple[float, float]] = {}
    for rec in source:
        if rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            key = row.get("מפתח")
            if key is None:
                continue
            fv = _num(row.get(FAIR_VALUE_COL))
            pct = to_ratio(row.get(PCT_COL))
            if fv is None or not pct:
                continue
            total = fv / pct
            cur = best.get(key)
            if cur is None or abs(fv) > cur[0]:
                best[key] = (abs(fv), total)
    return {k: v[1] for k, v in best.items()}


def _futures_exposure(
    source: list[dict], total_assets: dict[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    """מחזיר (sums, equity_sums) - equity_sums הוא תת-קבוצה של sums, רק שורות
    עם נכס בסיס = מניות/מדדי-מניות (FUT_UNDERLYING_COL), לאזור החשיפה
    למניות בדשבורד (ר' main.py) - לא משנה את sums עצמו (הקטגוריה הקיימת,
    מאומתת מול MAE).

    תקרת-מסלול (row_pct_sums/SANITY_CAP): נמצא בפועל (520028390_485 ודומיו) -
    שש שורות "חוזים עתידיים" (שלוש במוסכמת ערך-נקוב-100 עם ערך-נקוב שלילי-
    ענק, שלוש עם מחיר גולמי ענק) מדווחות בנפרד ב-PCT_COL בערכים קטנים
    ומתקזזים כמעט לגמרי (סכום ~0.08%) - עדות ישירה שה"מיקום הכלכלי" האמיתי
    לפי הדוח עצמו קטן וזניח. כל שורה בנפרד עברה את בדיקת ה-LEVERAGE_CAP
    (יחס נוציונל/שווי-הוגן סביר לכל שורה), אבל הסכום המצטבר של כל שש השורות
    יחד הגיע ל-700%+ - טעות-קנה-מידה שרק נראית תמימה ברמת שורה בודדת. בדיוק
    כמו שכבר קיים ל-swap (capped, למטה) - תקרת SANITY_CAP *ברמת המסלול כולו*
    (לא רק לכל שורה בנפרד), עם נפילה לסכום ה-PCT_COL המדווח (row_pct_sums) -
    שמייצג את מה שהדוח עצמו טוען, בלי שום הנחת-קנה-מידה מהמרת שלנו."""
    sums: dict[str, float] = {}
    equity_sums: dict[str, float] = {}
    row_pct_sums: dict[str, float] = {}
    equity_row_pct_sums: dict[str, float] = {}
    for rec in source:
        if rec["Category"] != FUTURES_CATEGORY or rec["מידע"] != "מידע":
            continue
        report_date = rec.get("ReportMonth")
        for row in rec["Clean"]:
            key = row.get("מפתח")
            total = total_assets.get(key) if key is not None else None
            if not total:
                continue
            is_equity = row.get(FUT_UNDERLYING_COL) == EQUITY_UNDERLYING
            row_pct = to_ratio(row.get(PCT_COL)) or 0.0
            row_pct_sums[key] = row_pct_sums.get(key, 0.0) + row_pct
            if is_equity:
                equity_row_pct_sums[key] = equity_row_pct_sums.get(key, 0.0) + row_pct
            units = _num(row.get(FUT_UNITS_COL))
            price = _num(row.get(FUT_PRICE_COL))
            fx = _normalize_fx(row.get(FUT_CURRENCY_COL), _num(row.get(FUT_FX_COL)))
            if price is not None and abs(price - PAR_QUOTED_PRICE) < 1e-6:
                price = price / 100  # רגל-מימון סינתטית במוסכמת ערך-נקוב-100, לא רמת מדד

            price_is_corrupted = False
            if price is not None and price < 0:
                resolved_price = _resolve_corrupted_futures_price(row.get(FUT_TICKER_COL), report_date)
                if resolved_price is not None:
                    price = resolved_price
                    price_is_corrupted = True
                else:
                    # מחיר שלילי לא-כלכלי (אין מחיר שלילי לחוזה עתידי/מדד) בלי
                    # תחליף-מחיר-חי מאומת - לא אמין לחישוב נוציונלי בשום קנה
                    # מידה, ואסור לו לעבור ישירות לנוסחה רק כי הוא נתפס
                    # (במקרה) ע"י תקרת-LEVERAGE_CAP. נמצא בפועל (512065202_15345,
                    # מיתב, טיקר ZWPU6/MSCI World): מחיר מדווח -181,177.9,
                    # שווי הוגן -1,688 אלפי ש"ח - יחס נוציונל/שווי-הוגן יוצא בדיוק
                    # פי 100, שנתפס בטעות ע"י LEVERAGE_CAP=75 (מקרי, לא בכוונה)
                    # אבל עובר בלי בעיה תחת LEVERAGE_CAP=120 - מייצר חשיפה שלילית
                    # דמיונית של כ-39% למסלול. מטופל כמו מחיר חסר לגמרי: נופל
                    # ל-fv_ratio/row_pct, לא לתקרת-מינוף שרירותית.
                    price = None

            fv = _num(row.get(FAIR_VALUE_COL))
            fv_ratio = (fv / total) if fv is not None else None

            line_ratio = None
            if units is not None and price is not None and fx is not None:
                notional_thousands = units * price * fx / 1000  # לאלפי ש"ח, כמו שווי הוגן
                line_ratio = notional_thousands / total
                # כשהמחיר המדווח שבור (price_is_corrupted), ה-fv המדווח לאותה
                # שורה נגזר מאותו מחיר שבור - לא עוגן אמין להשוואה כאן, בניגוד
                # לכל שורה רגילה אחרת. נשארת רק תקרת-SANITY_CAP המוחלטת למטה.
                if not price_is_corrupted and fv_ratio is not None and abs(line_ratio) > LEVERAGE_CAP * abs(fv_ratio):
                    line_ratio = None  # קנה מידה לא סביר ביחס לשווי ההוגן של השורה עצמה
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                line_ratio = fv_ratio if fv_ratio is not None else 0.0
            sums[key] = sums.get(key, 0.0) + line_ratio
            if is_equity:
                equity_sums[key] = equity_sums.get(key, 0.0) + line_ratio
    capped = {
        key: val if abs(val) <= SANITY_CAP else row_pct_sums.get(key, 0.0)
        for key, val in sums.items()
    }
    equity_capped = {
        key: val if abs(val) <= SANITY_CAP else equity_row_pct_sums.get(key, 0.0)
        for key, val in equity_sums.items()
    }
    return capped, equity_capped


def _swap_exposure(
    source: list[dict], total_assets: dict[str, float]
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, dict[str, float]]]:
    """נמצא בבדיקה בפועל (לא ניחוש): "ערך נקוב" (רגל 1) ו"ערך נקוב" (רגל 2)
    אינם תמיד באותה יחידת מידה. עבור "Unfunded Forward" (למשל פורוורד מט"ח)
    שתי הרגליים כבר סכום נקוב במטבע - קרובות זו לזו כצפוי. אבל עבור
    "Unfunded Swap" על מניות/מדדים (סוואפ תשואה-כוללת), רגל 1 היא כמות
    *יחידות גולמית* של נכס הבסיס (לא סכום נקוב), ורגל 2 היא כבר הסכום
    הנקוב הנכון. אומת ישירות מול reports/2026Q2/512065202_gm_0226.xlsx:
    על 542/542 שורות סוואפ-מניות, רגל1 × "שער נכס הבסיס במועד ההתקשרות
    בעסקה" (× שער חליפין רגל 1) שווה בדיוק לרגל 2 (עד כדי עיגול). לכן רגל 1
    צריכה הכפלה בשער נכס הבסיס כדי להיות ברת-השוואה לרגל 2 - לא נוסחת
    ה-units×fx הרגילה שמשמשת לכל שאר הקטגוריות. אין דגל מפורש בדוח שמבחין
    בין "Unfunded Swap" ל"Unfunded Forward", ולכן הבחירה אדפטיבית לכל שורה:
    בין הפרשנות הגולמית לפרשנות המוכפלת-במחיר לרגל 1, נבחרת זו שקרובה יותר
    לרגל 2 (שנמצא בפועל שהיא תמיד כבר תקינה).

    גם אחרי התיקון הזה, נמצא בפועל שחלק מהמגישים רושמים את "שער נכס הבסיס"
    בקנה מידה שגוי (למשל פי ~100, אותה תבנית תקלה כמו JPY/ערך-נקוב-100
    בחוזים עתידיים) - לא עקבי אפילו בתוך אותה קרן/טיקר. מטופל באותו עקרון
    LEVERAGE_CAP שכבר קיים לחוזים עתידיים: משווים את החשיפה הנוציונלית
    שהתקבלה לשווי ההוגן נטו שאותה שורה בדיוק מדווחת - יחס גבוה מדי מסמן קנה
    מידה לא אמין, ונופלים לערך המדווח (PCT_COL) לשורה הזו בלבד. תקרת
    ה-SANITY_CAP הקיימת (ברמת שורה) ותקרת מסלול נוספת (סכום מצטבר על פני כל
    שורות ה-swap במסלול) נשארות כרשת ביטחון אחרונה.

    שיפור: "שער נכס הבסיס במועד ההתקשרות בעסקה" הוא מחיר *בפתיחת* העסקה
    (ר' הערת המודול), לא מחיר עדכני - לחשיפה נכונה ליום הדוח משתמשים במקום
    זאת, כשאפשר, במחיר המדד החי נכון לתאריך הדוח (swap_index_pricing, דרך
    עמודת "טיקר" ומיפוי revach123/INDICES). כשהטיקר לא ממופה (בעיקר סלים
    קנייניים בנקאיים - ר' swap_ticker_map.csv שם) נופלים בחזרה לשיטת המחיר-
    בפתיחת-העסקה הקיימת. במקרה הזה leg2 (שקבוע לפי בנייה למחיר הפתיחה) כבר
    לא רלוונטי כעוגן לרגל 1 המתומחרת-חי - שתיהן מודדות דברים שונים בכוונה
    (נוציונל היסטורי מול חשיפה נוכחית) - לכן לא ממוצעים ביניהן.

    עדכון: leg1_live + LEVERAGE_CAP חלים *רק* כש-used_priced=True (רגל 1
    נבחרה בפועל, לפי ההשוואה מול רגל 2, כיחידות-גולמיות-הצריכות-מחיר) -
    *לא* לפי תווית Funded/Unfunded כמו שהיה קודם. נמצא בפועל שהתווית
    "מאפיין עיקרי" לבדה אינה אמינה: שורות "Unfunded Total Return/Equity
    Swap" (התווית הנפוצה ביותר בארכיון) יכולות להיות "רגל 1 כבר נוציונל"
    אצל מגיש מסוים (513173393/אלטשולר שחם) בדיוק כמו Funded, בעוד שאצל
    מגישים אחרים תחת אותה תווית בדיוק רגל 1 באמת יחידות גולמיות (כמו
    512065202 שאומת במקור) - ר' used_priced/is_funded למטה.

    מחזיר (notional_sums, funded_sums, unfunded_sums, equity_swaps) - הראשון
    הוא הסכום הכולל (המשמש להחלפת SWAP_CATEGORY, כמו קודם), השניים הבאים הם
    פילוח שקוף Funded/Unfunded (דיאגנוסטי בלבד, ר' build_derivatives_exposure),
    והאחרון הוא תת-קבוצה של notional_sums - רק שורות עם סוג הנכס=מניות,
    מפוצלות-שוב לפי הערך המדויק ב-"מאפיין עיקרי" (Funded/Unfunded X, כפי
    שמופיע בדוח בפועל), לאזור החשיפה למניות בדשבורד (ר' main.py)."""
    notional_sums: dict[str, float] = {}
    fv_sums: dict[str, float] = {}
    funded_sums: dict[str, float] = {}
    unfunded_sums: dict[str, float] = {}
    # equity_by_label: מפתח -> {"Unfunded Swap": שיעור, ...} - רק שורות עם
    # סוג הנכס = מניות, מפוצלות לפי הערך המדויק ב-SWAP_MAIN_TYPE_COL (Funded/
    # Unfunded X, כפי שמופיע בדוח בפועל - לא הנחה על אילו ערכים קיימים),
    # לאזור החשיפה למניות בדשבורד. שיעור-הוגן מקביל לכל bucket, לאותו
    # fallback-אם-קנה-המידה-לא-סביר כמו notional_sums הכולל.
    equity_by_label: dict[str, dict[str, float]] = {}
    equity_fv_by_label: dict[str, dict[str, float]] = {}
    leg1_col, leg2_col = SWAP_LEGS
    for rec in source:
        if rec["Category"] != SWAP_CATEGORY or rec["מידע"] != "מידע":
            continue
        report_date = rec.get("ReportMonth")
        for row in rec["Clean"]:
            key = row.get("מפתח")
            total = total_assets.get(key) if key is not None else None
            if not total:
                continue
            is_equity = row.get(SWAP_ASSET_TYPE_COL) == SWAP_EQUITY_ASSET_TYPE
            label = row.get(SWAP_LABEL_COL)
            # ה-fallback (כשקנה המידה לא אמין) משתמש בעמודת האחוז כפי שהדוח
            # עצמו מדווח - נמצא בפועל מדויק יותר מ-fv/total_assets_by_key
            # (שהאומדן שלה לשווי הכולל לא תמיד מתאים בדיוק לאומדן הדוח עצמו
            # לכל שורה בנפרד).
            row_pct = to_ratio(row.get(PCT_COL)) or 0.0
            fv_sums[key] = fv_sums.get(key, 0.0) + row_pct
            if is_equity and label:
                d = equity_fv_by_label.setdefault(key, {})
                d[label] = d.get(label, 0.0) + row_pct
            # is_funded: תווית "מאפיין עיקרי" בלבד - שימושי לפילוח דיאגנוסטי
            # (funded_sums/unfunded_sums), אבל *לא* אמין להחלטת קנה-המידה
            # עצמה (ר' used_priced למטה) - נמצא בפועל (513173393/אלטשולר
            # שחם) ששורות המתויגות "Unfunded Total Return/Equity Swap" -
            # התווית הנפוצה ביותר בארכיון, לא רק ב-512065202 שאומת במקור -
            # יכולות להיות "רגל 1 כבר נוציונל" בדיוק כמו Funded, תלוי מגיש
            # ספציפי (לא עקבי בין מגישים תחת אותה תווית בדיוק).
            is_funded = _is_funded_swap(row.get(SWAP_MAIN_TYPE_COL))

            units1 = _num(row.get(leg1_col["units"]))
            fx1 = _normalize_fx(row.get(leg1_col["currency"]), _num(row.get(leg1_col["fx"])))
            units2 = _num(row.get(leg2_col["units"]))
            fx2 = _normalize_fx(row.get(leg2_col["currency"]), _num(row.get(leg2_col["fx"])))
            price = _num(row.get(SWAP_UNDERLYING_PRICE_COL))

            leg2_val = abs(units2 * fx2) / 1000 if units2 is not None and fx2 is not None else None
            leg1_raw = abs(units1 * fx1) / 1000 if units1 is not None and fx1 is not None else None
            leg1_priced = (abs(units1 * fx1 * price) / 1000
                            if units1 is not None and fx1 is not None and price is not None else None)

            # used_priced: ההשוואה בפועל בין הפרשנויות (רגל1 גולמי מול רגל1
            # מוכפל-במחיר) ביחס לרגל2 - זו בדיקת-הסבירות ה*אמיתית* של קנה
            # המידה, ברמת השורה הבודדת, לא תלוית-תווית. True = רגל 1 הוא
            # באמת יחידות גולמיות (כמו 512065202 - התבנית שאומתה במקור).
            # False = רגל 1 כבר נוציונל (כמו Funded, וגם כמו חלק ניכר
            # מהשורות "Unfunded ..." בפועל - ר' הערה למעלה).
            used_priced = leg1_priced is not None and (
                leg1_raw is None or leg2_val is None
                or abs(leg1_priced - leg2_val) < abs(leg1_raw - leg2_val)
            )
            leg1_val = leg1_priced if used_priced else leg1_raw

            # leg1_live (תמחור-חי) מניח שרגל 1 היא יחידות גולמיות שצריך
            # לתמחר מחדש - תקף *רק* כשused_priced (לא is_funded - ר' הערה
            # למעלה): כשרגל 1 כבר נוציונל, תמחור חוזר יוצר מספר דמיוני
            # (נבדק בפועל: ~1.5 מיליארד ש"ח על שורה עם נוציונל אמיתי
            # ~100 מיליון - פי ~15,000).
            leg1_live = None
            if used_priced:
                current_price, _index_id = resolve_current_price(row.get(SWAP_TICKER_COL), report_date)
                leg1_live = (abs(units1 * fx1 * current_price) / 1000
                             if units1 is not None and fx1 is not None and current_price is not None else None)

            if leg1_live is not None:
                candidates = [leg1_live]  # לא ממוצעים עם leg2 - ר' הערת הפונקציה
            else:
                candidates = [v for v in (leg1_val, leg2_val) if v is not None]

            line_ratio = None
            if candidates:
                notional_thousands = sum(candidates) / len(candidates)
                line_ratio = notional_thousands / total

                # LEVERAGE_CAP (יחס נוציונל/שווי-הוגן-נטו) רלוונטי *רק*
                # כש-used_priced: זו הדרך היחידה שבה "שער נכס הבסיס" (מחיר
                # מדד גולמי, קנה-מידה שרירותי לגמרי ביחס ל-fv) נכנס בכלל
                # לחישוב הנוציונל, ולכן היחידה שבה טעות-קנה-מידה בשדה הזה
                # עלולה להתגלגל לתוצאה. כש-used_priced=False, הנוציונל כבר
                # אומת ישירות מול רגל 2 (ההשוואה למעלה) - וגם נמצא בפועל
                # (513173393) ששורות used_priced=False יכולות לגיטימית
                # להגיע ליחס נוציונל/fv עצום (עד פי ~1900) כש-fv נמצא במקרה
                # קרוב לאפס (סוואפ Unfunded בלי Reset תקופתי - fv יכול לנוע
                # דרך אפס בלי קשר לקנה-מידה) - לא סימן לתקלה שם.
                if used_priced:
                    fv = _num(row.get(SWAP_NET_FAIR_VALUE_COL))
                    fv_ratio = (fv / total) if fv is not None else None
                    if fv_ratio is not None and abs(line_ratio) > LEVERAGE_CAP * abs(fv_ratio):
                        line_ratio = None  # קנה מידה לא סביר ביחס לשווי ההוגן של השורה עצמה
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                line_ratio = row_pct
            notional_sums[key] = notional_sums.get(key, 0.0) + line_ratio
            if is_funded:
                funded_sums[key] = funded_sums.get(key, 0.0) + line_ratio
            else:
                unfunded_sums[key] = unfunded_sums.get(key, 0.0) + line_ratio
            if is_equity and label:
                d = equity_by_label.setdefault(key, {})
                d[label] = d.get(label, 0.0) + line_ratio

    capped = {
        key: val if abs(val) <= SANITY_CAP else fv_sums.get(key, 0.0)
        for key, val in notional_sums.items()
    }
    equity_swaps = {
        key: {
            label: val if abs(val) <= SANITY_CAP else equity_fv_by_label.get(key, {}).get(label, 0.0)
            for label, val in by_label.items()
        }
        for key, by_label in equity_by_label.items()
    }
    return capped, funded_sums, unfunded_sums, equity_swaps


def collect_unresolved_swap_tickers(source: list[dict]) -> dict[str, set[str]]:
    """מפתח -> סט טיקרים של סוואפ-מדד (סוג הנכס == מניות לרבות מדדי מניות)
    שלא נמצא להם מיפוי ב-swap_ticker_map.csv (revach123/INDICES) - בין אם
    כי אין להם מקור נתונים ציבורי (סלים קנייניים בנקאיים, ר' swap_ticker_map.csv
    לסיבה המדויקת לכל טיקר) ובין אם כי טיקר חדש שלא נראה עדיין בסריקה שבנתה
    את המיפוי. מיועד לדגל "לטיפול" בדשבורד - לא משפיע על חישוב החשיפה עצמו."""
    from .swap_index_pricing import _load_ticker_map, normalize_ticker

    try:
        ticker_map = _load_ticker_map()
    except Exception:
        return {}

    out: dict[str, set[str]] = {}
    for rec in source:
        if rec["Category"] != SWAP_CATEGORY or rec["מידע"] != "מידע":
            continue
        for row in rec["Clean"]:
            if row.get(SWAP_ASSET_TYPE_COL) != SWAP_EQUITY_ASSET_TYPE:
                continue
            key = row.get("מפתח")
            raw_ticker = row.get(SWAP_TICKER_COL)
            norm = normalize_ticker(raw_ticker)
            if key is None or not norm or norm in ticker_map:
                continue
            out.setdefault(key, set()).add(str(raw_ticker).strip())
    return out


def _options_exposure(
    source: list[dict], total_assets: dict[str, float], category: str
) -> tuple[dict[str, float], dict[str, float]]:
    """דלתא×נוציונל לקטגוריית אופציה אחת (listed/OTC בנפרד - שם השדה
    ה"מפתח" תמיד "Category" של הגיליון, לא משנה איזה). רק שורות נכס-בסיס
    מניות (OPT_EQUITY_UNDERLYING) - מט"ח/ריבית/אחר נשארים בשיטה הישנה,
    מחוץ להיקף (לא אופציות על מניות, לא חלק מהתיקון הזה). מחזיר גם
    equity_sums - תת-קבוצה של sums, רק שורות מניות - לאזור החשיפה למניות
    בדשבורד (ר' main.py)."""
    sums: dict[str, float] = {}
    equity_sums: dict[str, float] = {}
    for rec in source:
        if rec["Category"] != category or rec["מידע"] != "מידע":
            continue
        report_date = rec.get("ReportMonth")
        for row in rec["Clean"]:
            key = row.get("מפתח")
            total = total_assets.get(key) if key is not None else None
            if not total:
                continue
            row_pct = to_ratio(row.get(PCT_COL)) or 0.0

            if row.get(OPT_UNDERLYING_COL) != OPT_EQUITY_UNDERLYING:
                sums[key] = sums.get(key, 0.0) + row_pct
                continue

            name = row.get(OPT_NAME_COL)
            ticker, _pattern = parse_underlying(str(name)) if name else (None, None)
            is_call = is_call_option(str(name)) if name else None
            strike = _num(row.get(OPT_STRIKE_COL))
            expiry_raw = row.get(OPT_EXPIRY_COL)
            expiry = expiry_raw.date() if hasattr(expiry_raw, "date") else None
            units = _num(row.get(OPT_UNITS_COL))
            fx = _normalize_fx(row.get(OPT_CURRENCY_COL), _num(row.get(OPT_FX_COL)))

            line_ratio = None
            if ticker is not None and is_call is not None and units is not None and fx is not None:
                delta, spot = resolve_option_delta(ticker, strike, expiry, report_date, is_call)
                if delta is not None and spot is not None:
                    notional_thousands = units * delta * spot * fx / 1000
                    line_ratio = notional_thousands / total
                    fv = _num(row.get(FAIR_VALUE_COL))
                    fv_ratio = (fv / total) if fv is not None else None
                    if fv_ratio is not None and abs(line_ratio) > LEVERAGE_CAP * abs(fv_ratio):
                        line_ratio = None
            if line_ratio is None or abs(line_ratio) > SANITY_CAP:
                line_ratio = row_pct
            sums[key] = sums.get(key, 0.0) + line_ratio
            equity_sums[key] = equity_sums.get(key, 0.0) + line_ratio
    return sums, equity_sums


def build_derivatives_exposure(source: list[dict]) -> dict[str, dict[str, float]]:
    """מפתח -> {קטגוריה: שיעור חשיפה אמיתי}, לארבע הקטגוריות (חוזים עתידיים,
    לא סחיר נגזרים אחרים, אופציות, לא סחיר אופציות) - מיועד להחליף את
    הערכים המבוססי-שווי-הוגן שמחשב category_pct.build_category_pct לאותן
    קטגוריות בדיוק - ולא לגעת בשאר הקטגוריות.

    בנוסף (לא מחליף כלום, רק מצטרף): שתי קטגוריות דיאגנוסטיות (FUNDED_
    SWAP_CATEGORY/UNFUNDED_SWAP_CATEGORY) - פילוח שקוף של SWAP_CATEGORY בין
    שני מבני הסוואפ (ר' הערת _swap_exposure); ועמודות "אזור חשיפה למניות" -
    נכס-בסיס=מניות בלבד לחוזים/אופציות (FUTURES_EQUITY_COLUMN/
    OPTIONS_EQUITY_COLUMN), ופיצול Funded/Unfunded לסוואפים-על-מניות (לפי
    SWAP_MAIN_TYPE_COL בפועל בדוח) - עמודות "לא סחיר נגזרים אחרים - מניות
    (<תווית>)"."""
    total_assets = total_assets_by_key(source)
    futures, futures_equity = _futures_exposure(source, total_assets)
    swaps, funded_swaps, unfunded_swaps, swaps_equity_by_label = _swap_exposure(source, total_assets)
    options_listed, options_listed_equity = _options_exposure(source, total_assets, OPTIONS_LISTED_CATEGORY)
    options_otc, options_otc_equity = _options_exposure(source, total_assets, OPTIONS_OTC_CATEGORY)

    out: dict[str, dict[str, float]] = {}
    for key, val in futures.items():
        out.setdefault(key, {})[FUTURES_CATEGORY] = val
    for key, val in swaps.items():
        out.setdefault(key, {})[SWAP_CATEGORY] = val
    for key, val in funded_swaps.items():
        out.setdefault(key, {})[FUNDED_SWAP_CATEGORY] = val
    for key, val in unfunded_swaps.items():
        out.setdefault(key, {})[UNFUNDED_SWAP_CATEGORY] = val
    for key, val in options_listed.items():
        out.setdefault(key, {})[OPTIONS_LISTED_CATEGORY] = val
    for key, val in options_otc.items():
        out.setdefault(key, {})[OPTIONS_OTC_CATEGORY] = val

    for key, val in futures_equity.items():
        out.setdefault(key, {})[FUTURES_EQUITY_COLUMN] = val
    for key, by_label in swaps_equity_by_label.items():
        d = out.setdefault(key, {})
        for label, val in by_label.items():
            d[f"{SWAP_CATEGORY} - מניות ({label})"] = val
    for key, val in options_listed_equity.items():
        out.setdefault(key, {})[OPTIONS_EQUITY_COLUMN] = out.setdefault(key, {}).get(OPTIONS_EQUITY_COLUMN, 0.0) + val
    for key, val in options_otc_equity.items():
        out.setdefault(key, {})[OPTIONS_EQUITY_COLUMN] = out.setdefault(key, {}).get(OPTIONS_EQUITY_COLUMN, 0.0) + val
    return out
