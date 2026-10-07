# מרכיבי תשואה לפי מסלול

דוחות "פירוט תרומת אפיקי ההשקעה לתשואה הכוללת" (מרכיבי תשואה) שכל גוף מוסדי מפרסם באתר שלו לכל מסלול, רבעוני,
בתבנית אחידה של רשות שוק ההון: לכל חודש - התרומה לתשואה ושיעור מסך הנכסים של כל אפיק, סך התשואה החודשית,
פיצול ארץ/חו"ל וסחיר/לא סחיר, ומצטבר מתחילת השנה. חברות ביטוח מפרסמות גם דוח נוסטרו (רבעוני, באלפי ש"ח).

## מבנה
- `returns/companies/<LegalId>/` - כל המצב של חברה: `docs_index.json` (url -> sha, קובץ, תאריכים), `raw/`, `parsed/<sha12>.json`
  (מטמון פרסור), `tracks.json` (סדרה לכל מסלול), `nostro.json`, `site_snapshot.json`, `discovered.json`, `crawl_report.json`.
- `returns/*.csv` - טבלאות מאוחדות, נבנות מחדש בכל ריצה (`combine.py`):
  `tracks.csv` (שורה למסלול), `monthly_totals.csv` (מסלול×חודש: תשואה + תרומת המניות), `coverage.csv` (שורה לחברה: מה נסרק,
  כמה מסלולים נמצאו מול הרישום הרשמי), `nostro.csv`, `verify_tracks.csv` + `verify_gaps.csv` (מול data.gov), `index.json` (לאתר).
- `tracks.json`: `assets` = סדר האפיקים; לכל מסלול `m["YYYY-MM"] = {"c": [תרומה % לפי assets], "w": [משקל %], "d": sha12 של הדוח}`,
  `ytd` באותו מבנה (מצטבר מתחילת השנה עד החודש), `track_no` + `track_no_src`, `revisions` (ערכים שהשתנו בין דוחות).

## שלבים
1. `crawl.py` - איתור עמודים והורדה. אותם רכיבים כמו במדיניות (`scripts/policy/crawl.py`, `snapshot.py`: דפדפן, אקורדיונים,
   iframes, לכידת הורדות, הורדה דרך הדפדפן) עם ציון שמכוון ל"מרכיבי תשואה". מקורות עמודים: `returns_pages` בהגדרות האתר
   (`scripts/policy/sites/<LegalId>.json`), `discovered.json`, קישורים מתמונת המצב של המדיניות, sitemap, חיפוש, דף הבית.
   קבצי מרכיבי תשואה שסריקת המדיניות הורידה בעבר נקלטים בלי הורדה (וסריקת המדיניות כבר לא בוחרת אותם - `RETURNS_DOC`).
   הגדרות אתר אופציונליות: `returns_pages` [{url, product}] (`{year}` מורחב), `returns_docs`, `returns_exclude`, `returns_follow`,
   `returns_click_texts`, `returns_budget` [שניות לעמוד, שניות ללחיצות הורדה], `returns_max_pages`, `returns_cloud` (לסרוק מהענן
   גם אתר via=extension).
2. `extract.py` + `parse.py` - פרסור לפי מבנה הגיליון (לא לפי חברה): שורת "אפיקי השקעה" עם עמודות "התרומה לתשואה <חודש>" /
   "שיעור מסך הנכסים <חודש>" (חודש בשם, כתאריך או כתאריך אקסל בשורה מעל), אפיקים מנורמלים למפתחות קבועים, שברים/אחוזים לפי שורת
   הסה"כ. PDF דרך pdfplumber. קובץ שאינו מרכיבי תשואה מסומן `not_returns` והקובץ נמחק (לא יורד שוב).
3. בחירת ערך לכל חודש: הדוח העדכני ביותר (מכסה הכי הרבה חודשים בשנה). מה שכתוב בקובץ קובע את החודש והשנה.
4. מספר מסלול: מהקובץ (תווית "מס מסלול"/"מס' אוצר", סוגריים בשם, שם הגיליון, שם הקובץ `<ח.פ.>_<g|p|i><מספר>_Yield<רבעון><שנה>`)
   ונבדק מול `policy/fund_registry.csv` / `fund_names.csv`; אחרת התאמת שם מול הרישום; אחרת התאמת סדרת התשואות מול data.gov.
5. `verify.py` - סך התרומות לחודש מול `MONTHLY_YIELD` בגמל-נט/פנסיה-נט/ביטוח-נט. ok = פער חציוני עד 0.06 נק'.

## ריצה
- `.github/workflows/returns_sites.yml` - ג'וב לכל חברה; יומי 05:37 (אחרי המדיניות), ידני (`only`, `mode`=crawl/parse),
  ו-push לענף `claude/**` שמשנה את `returns/run.json` (`{"only": [...]|"all", "mode": "crawl"|"parse", "force_cloud": bool}`).
- `.github/workflows/returns_verify.yml` - יומי, ידני, או push של `returns/verify_run.json`.
- אתרים שחוסמים שרתי ענן: `home.py` על ה-runner הביתי (Revach `policy-home.yml`) -> `policy/inbox/<id>/returns/` ->
  `ingest.py` ב-`policy_inbox.yml`.
- האתר: Revach `returns.html` (נתונים: `returns_view/`, נבנים ב-Revach `returns-view.yml` מהקבצים כאן).
