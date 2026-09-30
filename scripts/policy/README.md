# מדיניות השקעות מוצהרת לפי מסלול

## מבנה
- `sites/<LegalId>.json` - מקור קבוע לכל חברה: `home`, `pages` (עמוד לכל מוצר: גמל/פנסיה/ביטוח; `{year}` מורחב לכל שנה), `browser` (`headless`/`headed`).
- `policy/companies/<LegalId>/` - כל המצב של חברה: `site_snapshot/`, `docs_index.json`, `raw/`, פלטי פרסור, `site_changes_log.csv`.
- `policy/*.csv|json` - טבלאות מאוחדות (`combine.py`), נבנות מחדש בכל ריצה: `tracks_policy_long.csv` (שורה לכל מסלול×אפיק),
  `policy_changes.csv`, `documents.csv`, `crawl_report.csv`, `site_changes_log.csv`, `unparsed_layouts.json`.

## ריצה (`.github/workflows/policy_sites.yml`)
ג'וב נפרד לכל חברה, במקביל. יומי 04:00 לכולן; push שמשנה רק `sites/X.json` מריץ רק את X.
לכל חברה: `crawl.py` (רינדור בדפדפן, פתיחת אקורדיונים/לשוניות/iframes, לכידת JSON ברשת -> תמונת מצב + השוואה לקודמת ->
בחירת מסמכי מדיניות -> הורדה, כולל דרך הדפדפן אם requests נחסם) ואז `extract.py`.

## פרסרים (`extract.py`) - לפי מבנה הגיליון, לא לפי חברה
- `parse_statement_blocks` - "קידוד מסלול"/"שם המסלול" (מיטב).
- `parse_mh_blocks` - `מ"ה: <קוד> - <שם>`, כמה מסלולים לטבלה, בלוקים זה לצד זה (מור).
- `parse_columns_blocks` - בלוק 5 עמודות לכל מסלול, קוד בסוגריים בכותרת (הראל).
- `parse_change_log` - גיליון "מהות שינויים".
מבנה לא מזוהה נשמר ב-`unparsed_layouts.json` (תחילת כל גיליון) להוספת פרסר.

`gap.py --master out/master.json` - טווחי מדיניות מול חשיפה בפועל, התאמה לפי קוד קופה.
