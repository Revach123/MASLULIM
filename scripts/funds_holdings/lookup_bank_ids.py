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

# בירור ממוקד: פירוט מלא לפי ח.פ (למיזוגים), וחיפושים חלופיים למיטב + בנקים
# חדשים שהתגלו מתוך הנתונים האמיתיים (לא מ-Table H, שהתברר לא אמין).
DETAIL_IDS = [
    "520016106", "520004490",  # אוצר החייל, יובנק - "מחוסלת עקב מיזוג"
    "513495796",  # אקסלנס נשואה שירותים בע"מ - האם "purpose" מזכיר שירותי בורסה?
    "512401449", "512401761", "517131009",  # שאר מועמדי "נשואה" הפעילים
]
EXTRA_QUERIES = [
    "מיטב דש", "מיטב טרייד", "מיטב דש טרייד השקעות",
    "בנק ירושלים",
    "גמול פועלים סהר", "פועלים סהר",
    "נשואה", "אקסלנס נשואה",
]


def search(session, key, q):
    r = session.get(SEARCH_URL, params={"q": q}, headers={"X-Match-Key": key, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def detail(session, key, cid):
    r = session.get(SEARCH_URL, params={"id": cid}, headers={"X-Match-Key": key, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def print_candidates(name, data):
    results = data.get("results", [])
    print(f"      | {name:<40} | {len(results)} תוצאות מוצגות (מתוך {data.get('total', 0)} סה\"כ), counts={data.get('counts')}")
    for c in results[:15]:
        print(f"      -> kind={c.get('kind'):<12} id={c.get('id'):<12} name={c.get('name')!r:<50} status={c.get('status')!r}")


def main():
    key = os.environ.get(MATCH_KEY_ENV)
    if not key:
        sys.exit(f"[lookup_bank_ids] משתנה הסביבה {MATCH_KEY_ENV} לא מוגדר")

    s = requests.Session()

    print("=== פירוט מלא לחברות שמוזגו ===")
    for cid in DETAIL_IDS:
        try:
            d = detail(s, key, cid)
        except Exception as e:
            print(f"id={cid} | שגיאה: {e!r}")
            continue
        print(f"id={cid} -> {d.get('item')}")
        time.sleep(0.3)

    print("\n=== שאילתות חלופיות למיטב ===")
    for q in EXTRA_QUERIES:
        try:
            data = search(s, key, q)
        except Exception as e:
            print(f"      | {q:<40} | שגיאה: {e!r}")
            time.sleep(0.3)
            continue
        print_candidates(q, data)
        time.sleep(0.3)

    print("\n=== הרשימה המלאה (bank_reference.csv) ===")
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
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
