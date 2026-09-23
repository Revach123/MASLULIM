"""חד-פעמי: איתור ח.פ. לכל בנק ב-bank_reference.csv, דרך revach /api/search.

לא כותב אוטומטית ל-CSV - רק מדפיס מועמדים, לאישור ידני לפני שמכניסים
לטבלה הקבועה (בנקים זרים כנראה לא ימצאו כלל - אין להם ח.פ. ישראלי,
וזה תקין: היתר עסקה רלוונטי רק לבנקים ישראליים).
"""
import csv
import os
import sys
import time

import requests

SEARCH_URL = "https://revach.pages.dev/api/search"
MATCH_KEY_ENV = "REVACH_MATCH_KEY"
CSV_PATH = os.path.join(os.path.dirname(__file__), "bank_reference.csv")


def search(session, key, q):
    r = session.get(SEARCH_URL, params={"q": q}, headers={"X-Match-Key": key, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    key = os.environ.get(MATCH_KEY_ENV)
    if not key:
        sys.exit(f"[lookup_bank_ids] משתנה הסביבה {MATCH_KEY_ENV} לא מוגדר")

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    s = requests.Session()
    for row in rows:
        name = row["שם_בנק"]
        try:
            data = search(s, key, name)
        except Exception as e:
            print(f"{row['מספר_מזהה']:>3} | {name:<55} | שגיאה: {e!r}")
            time.sleep(0.3)
            continue
        results = data.get("results", [])
        companies = [r for r in results if r.get("kind") == "company"][:5]
        print(f"{row['מספר_מזהה']:>3} | {name:<55} | {len(companies)} מועמדים (מתוך {data.get('total', 0)} סה\"כ)")
        for c in companies:
            print(f"      -> id={c.get('id'):<12} name={c.get('name')!r:<50} status={c.get('status')!r}")
        time.sleep(0.3)


if __name__ == "__main__":
    main()
