"""דיבאג חד-פעמי: לבדוק בפועל (מול ה-API החי) האם המסלולים שנעלמו מהדוח
האחרון (חשיפה רשמית גבוהה, 0% מחושב) באמת מסומנים "מצב"=="פעיל" ברפרנס -
או שההנחה הזו (שהובילה לתיקון ב-track_backfill.py) הייתה שגויה, וזה מה
שמסביר למה ה-CI האמיתי מצא 0 מסלולים לתיקון בזמן שהבדיקה המקומית
(עם tracks מזויפים) מצאה 16.
"""
from .tracks_reference import fetch_tracks, track_key

SUSPECT_KEYS = {
    "514956465_7957", "514956465_8695", "514956465_15259", "514956465_15249",
    "514956465_8701", "514956465_15241", "514956465_9452", "514956465_7958",
    "514956465_13925", "514956465_15273",
    "517085874_15986", "517085874_15960", "517085874_15972",
    "512244146_15679", "520042177_8834",
}


def main():
    tracks = fetch_tracks()
    print(f"[debug] {len(tracks)} מסלולים סה\"כ")

    status_values = {}
    for t in tracks:
        v = t.get("מצב")
        status_values[v] = status_values.get(v, 0) + 1
    print(f"[debug] ערכי 'מצב' ייחודיים: {status_values}")

    by_key = {}
    for t in tracks:
        k = track_key(t)
        if k in SUSPECT_KEYS:
            by_key[k] = t

    for k in sorted(SUSPECT_KEYS):
        t = by_key.get(k)
        if t is None:
            print(f"[debug] {k}: לא נמצא ב-tracks בכלל")
        else:
            print(f"[debug] {k}: מצב={t.get('מצב')!r} חשיפה_למניות={t.get('חשיפה למניות')!r} "
                  f"שם={t.get('שם מסלול קצר')!r}")


if __name__ == "__main__":
    main()
