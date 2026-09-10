# מעקב דוחות רבעוניים - רשות שוק ההון

ארכיון אוטומטי של **קבצי הדוחות הרבעוניים הגולמיים** מאתר רשות שוק ההון
(cmainfo.cma.gov.il), מסודרים לפי רבעון, עם manifest ל-Power Query.

## למה הארכיטקטורה הזאת

האתר של רשות שוק ההון חוסם (403 / AWS WAF) כל גישה שאינה מ-IP ישראלי ביתי -
כולל כל שרת ענן (GitHub Actions, AWS, וכו'). לכן **המשיכה חייבת לקרות
מהדפדפן שלך, על החיבור הביתי שלך** (בדיוק כמו שה-bookmarklet עבד).

הפתרון (היברידי):
1. **תוסף Chrome** (`extension/`) רץ בדפדפן שלך, מושך מהאתר אחת ליום את
   הדוחות החדשים, ו**דוחף אותם אוטומטית ל-GitHub** דרך ה-API.
2. **GitHub** מחזיק את הארכיון (הקבצים + `manifest.csv`) - זמין 24/7 בלי
   קשר אם המחשב שלך דלוק.
3. **Power Query** קורא מ-GitHub. Refresh מושך את המצב העדכני.

הנקודה: ה"תמיד-זמין" נחוץ רק לקריאה (Power Query) וזה תמיד קיים ב-GitHub.
האיסוף צריך לקרות רק מדי פעם, וכשמדובר בדוחות רבעוניים - כל פעם שהדפדפן
שלך פתוח (התוסף בודק אחת ליום ברקע) תופס כל דוח חדש.

## מבנה הארכיון

```
reports/<year>Q<quarter>/<LegalId>_<in|gm|pn>.xlsx
manifest.json   מקור האמת: אילו DocumentId כבר נמשכו
manifest.csv    אותו מידע כטבלה + content_api_url לכל קובץ (זה מה שמתחברים אליו)
extension/      קוד התוסף
```

## התקנת התוסף

1. הורד/שכפל את התיקייה `extension/`.
2. פתח `chrome://extensions` → הפעל "מצב מפתחים" → "טען פריט שלא נארז" →
   בחר את תיקיית `extension`.
3. פתח את הגדרות התוסף (כפתור "הגדרות" בפופאפ) והזן:
   - owner: `Revach123`, repo: `MASLULIM`, branch: `main`
   - GitHub Token (Fine-grained PAT, ראה למטה)
4. לחץ "שמור ובדוק חיבור" - צריך להופיע ✓.

### הפקת טוקן GitHub

GitHub → Settings → Developer settings → Fine-grained personal access tokens
→ Generate new token → Repository access: only this repo → Permissions →
Repository permissions → **Contents: Read and write** → Generate → העתק
(`github_pat_...`).

## איפה נשמרים הקבצים

- **מקומית במחשב**: הכל בתיקייה **אחת שטוחה** בתיקיית ההורדות -
  `Downloads/דוחות רבעוניים - רשות שוק ההון/` - עם שם הקובץ הזהה ל-bookmarklet
  (`{LegalId}_{sys}_{QQ}{YY}.xlsx`).
- **ב-GitHub**: אותם קבצים, אבל **מחולקים לתיקייה לכל רבעון**
  (`reports/2026Q2/…`), עם manifest ל-Power Query.

## שימוש

- **פעם ראשונה**: לחץ "משיכת כל ההיסטוריה" (רץ פעם אחת, יכול לקחת כמה דקות -
  אל תסגור את הדפדפן באמצע). זה גם דוחף ל-git וגם שומר מקומית.
- **שוטף**: התוסף בודק אוטומטית אחת ליום (כשהדפדפן פתוח), מושך רק חדשים,
  שומר אותם מקומית ודוחף ל-git. אפשר גם "בדוק ומשוך עכשיו" ידנית.
- **סנכרן עותק מקומי (מ-git)**: שומר לתיקייה המקומית את כל מה שכבר קיים
  בארכיון ה-git, בלי למשוך שוב מהאתר - שימושי כדי למלא את התיקייה המקומית
  (למשל במחשב חדש, או להשלים קבצים שכבר עלו ל-git לפני ההתקנה).
- כשיש חדשים - התראה + תג על האייקון.

## חיבור מ-Power Query (repo פרטי)

לקריאת טבלת האינדקס `manifest.csv` מרפו פרטי, דרך ה-API עם הטוקן:

```powerquery
let
    Token = "PASTE_YOUR_TOKEN_HERE",
    Url = "https://api.github.com/repos/Revach123/MASLULIM/contents/manifest.csv?ref=main",
    Source = Csv.Document(
        Web.Contents(Url, [Headers=[
            Authorization = "Bearer " & Token,
            Accept = "application/vnd.github.raw"
        ]]),
        [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true])
in
    Promoted
```

בטבלה יש עמודת `content_api_url` לכל קובץ דוח. כדי למשוך קובץ xlsx ספציפי
(למשל בשאילתה שמבוססת על אותה עמודה):

```powerquery
let
    Token = "PASTE_YOUR_TOKEN_HERE",
    Bytes = Web.Contents(ThatContentApiUrl, [Headers=[
        Authorization = "Bearer " & Token,
        Accept = "application/vnd.github.raw"
    ]]),
    Book = Excel.Workbook(Bytes)
in
    Book
```

> אם תהפוך את הרפו ל-Public בעתיד, אפשר לוותר על ה-Token וה-Headers ולקרוא
> ישירות מ-`https://raw.githubusercontent.com/Revach123/MASLULIM/main/manifest.csv`.
