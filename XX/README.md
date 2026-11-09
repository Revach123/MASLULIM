# XX - חיפוש תמונות לגרפיקה והעלאה ל-Drive

כלי שורת פקודה: מחפש תמונות ברשת (Openverse - רישיונות פתוחים, ברירת מחדל: מותר שימוש מסחרי ועריכה),
מוריד ברזולוציה גבוהה, יוצר `credits.csv` עם ייחוס ליוצר, ומעלה לתיקייה ב-Google Drive.

## התקנה
```bash
pip install -r requirements.txt
```

## שימוש
```bash
python -m xx.cli "mountain landscape" -n 10 --list-only      # רק תצוגת תוצאות
python -m xx.cli "mountain landscape" -n 10                  # הורדה מקומית
python -m xx.cli "mountain landscape" -n 10 --drive          # הורדה + העלאה ל-Drive
```
אפשרויות: `--min-width`, `--any-license`, `--folder-id`, `--folder-name`, `-o`.

## הגדרת Google Drive (פעם אחת)
1. ב-Google Cloud Console: צור פרויקט, הפעל **Google Drive API**.
2. צור **OAuth client ID** מסוג Desktop והורד כ-`credentials.json` לתיקייה זו
   (או מפתח חשבון שירות - אז שתף איתו את תיקיית היעד ב-Drive והעבר `--folder-id`).
3. בהרצה הראשונה ייפתח דפדפן לאישור; נשמר `token.json`.

## הערות
- בדוק את רישיון כל תמונה ב-`credits.csv` לפני שימוש; רישיונות CC דורשים בדרך כלל ייחוס.
- הסקריפט מעלה רק קבצים שהוא עצמו יצר (scope: `drive.file`).
- `credentials.json` ו-`token.json` ב-.gitignore - לא להעלות לגיט.

## בדיקות
```bash
python -m pytest
```
