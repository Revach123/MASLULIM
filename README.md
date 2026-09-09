# מעקב דוחות - רשות שוק ההון

מריץ אוטומטית, בענן (GitHub Actions, בלי תלות במחשב אישי), בדיקה של דוחות
ציבוריים חדשים באתר [cmainfo.cma.gov.il](https://cmainfo.cma.gov.il/publicreports),
מוריד קבצים חדשים לתיקייה לפי רבעון, ושומר `manifest.csv`/`manifest.json`
כאינדקס מלא של כל הקבצים - כדי שאפשר יהיה להתחבר אליו מ-Power Query.

## מבנה

```
reports/
  2024Q1/
    <LegalId>_<in|gm|pn>.xlsx
  2024Q2/
  ...
manifest.json   - יומן מלא (מקור האמת: אילו DocumentId כבר ירדו)
manifest.csv    - אותו מידע כ-CSV, כולל raw_url לכל קובץ - זה מה שמתחברים אליו מ-Power Query
scripts/
  lib.mjs       - הלוגיקה המשותפת (שליפה/הורדה מהאתר)
  run.mjs       - הסקריפט הראשי (מצב incremental או backfill)
.github/workflows/
  check-reports.yml  - רץ כל שעה, בודק את 4 הרבעונים האחרונים (תופס הגשות מאוחרות)
  backfill.yml       - רץ ידנית (Actions -> Run workflow), מושך היסטוריה אחורה
                       עד שנתקל ב-6 רבעונים ריקים ברצף
```

## איך זה עובד מאחורי הקלעים

הבדיקה רצה בתוך דפדפן headless אמיתי (Playwright/Chromium) שטוען את דף
"publicreports" בפועל ואז קורא לאותם API endpoints שהאתר עצמו קורא להם -
בדיוק כמו bookmarklet שרץ בדפדפן. זה חשוב כי לאתר יש הגנת בוט/WAF שחוסמת
בקשות HTTP גולמיות (משרת/פונקציה בענן) שלא הגיעו מטעינה אמיתית של הדף.

כל קובץ מזוהה לפי `DocumentId` הייחודי שלו - קובץ שכבר ירד לא יורד שוב.

## הפעלה ראשונה

1. **Backfill (חד פעמי)**: בטאב Actions ברפו - תבחר workflow
   "Backfill CMA Reports History" - Run workflow. זה ימשוך את כל ההיסטוריה
   הזמינה (אחורה עד שיתקל ב-6 רבעונים ריקים ברצף, עד תקרה של 20 שנה) ויכניס
   הכל לתיקיות `reports/<year>Q<quarter>/`. יכול לקחת זמן (תלוי בכמות
   הדוחות) - יש timeout של 5 שעות.
2. **מעקב שוטף**: workflow "Check CMA Reports" רץ אוטומטית כל שעה (UTC),
   בודק את 4 הרבעונים האחרונים (לתפוס הגשות מאוחרות/תיקונים) ומוריד רק מה
   שעדיין לא היה ביומן.
3. אפשר גם להריץ את שניהם ידנית בכל רגע דרך "Run workflow".

## חיבור מ-Power Query (הרפו פרטי)

צריך Personal Access Token של GitHub עם הרשאת `repo` (read בלבד מספיק) כדי
לקרוא מרפו פרטי:

1. GitHub -> Settings -> Developer settings -> Personal access tokens ->
   Fine-grained tokens -> Generate new token. הרשאה: Repository access רק
   לרפו הזה, Contents: Read-only.
2. ב-Power Query (Excel/Power BI) -> Get Data -> Blank Query -> Advanced
   Editor, ותדביק:

```powerquery
let
    Token = "PASTE_YOUR_TOKEN_HERE",
    Url = "https://raw.githubusercontent.com/Revach123/maslulim/main/manifest.csv",
    Source = Csv.Document(
        Web.Contents(Url, [Headers=[Authorization="token " & Token]]),
        [Delimiter=",", Columns=10, Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true])
in
    PromotedHeaders
```

זה נותן טבלה עם שורה לכל קובץ, כולל עמודת `raw_url` שאפשר להשתמש בה כדי
למשוך קובץ ספציפי (אותה טכניקה - `Web.Contents` עם אותו header של
Authorization).

כדי למשוך קובץ xlsx ספציפי בעצמו (למשל בתוך שאילתה נוספת שמבוססת על
`raw_url` מהטבלה למעלה):

```powerquery
let
    Token = "PASTE_YOUR_TOKEN_HERE",
    Bytes = Web.Contents(SomeRawUrl, [Headers=[Authorization="token " & Token]]),
    Workbook = Excel.Workbook(Bytes)
in
    Workbook
```

## הערות

- הזמן בעמודת `StatusDate`/שם הריפו ב-`raw_url` מניחים שהברנץ' הראשי נקרא
  `main` ובעלי הרפו זה `Revach123/maslulim` - אם זה משתנה, `raw_url`
  ב-CSV יתעדכן אוטומטית בריצה הבאה (מחושב מ-`GITHUB_REPOSITORY`/`GITHUB_REF_NAME`
  בזמן ריצת ה-workflow).
- אם בעתיד ירצו publish בלי טוקן (רפו ציבורי), אפשר פשוט לשנות את
  הרפו ל-Public ב-Settings, ואז לוותר על ה-header של Authorization
  ב-Power Query.
