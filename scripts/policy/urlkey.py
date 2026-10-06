"""מפתח קבוע לקובץ באינדקס (crawl, ingest_inbox, normalize_index). בלי תלויות - ה-workflow של ה-inbox רץ בלי requests."""
import re
from urllib.parse import unquote


def doc_key(url):
    """הכתובת בצורה קריאה (התוסף שולח מקודד %D7%9E..., הסריקה בענן קריא), ובכתובת הורדה חתומה (מגדל/Wix:
    download-files.wixmp.com/...?token=<JWT>, token חדש בכל סריקה) - בלי ה-token. אחרת כל סריקה רושמת את אותו קובץ
    מחדש (עד 24 רשומות לקובץ)."""
    u = unquote(url)
    if re.search(r"[?&]token=", u) and "wixmp.com" in u:
        u = u.split("?")[0]
    return u


def wix_id(url):
    """מזהה קובץ ב-Wix ("ugd/571a7f_6ca15...xlsx") - אותו קובץ בכתובת הציבורית (<site>/_files/ugd/...) ובכתובת ההורדה
    (download-files.wixmp.com/ugd/...?token=); None לכל כתובת אחרת."""
    m = re.search(r"/ugd/([0-9a-f]{6}_[0-9a-f]{32}\.\w+)", unquote(url))
    return f"ugd/{m.group(1)}" if m else None


def find_key(index, url):
    """המפתח הקיים באינדקס לאותו קובץ (doc_key, ואז מזהה Wix - עדיפות לכתובת הציבורית), או doc_key לקובץ חדש."""
    k = doc_key(url)
    if k in index or not wix_id(url):
        return k
    alias = {}
    for key in index:
        w = wix_id(key)
        if w and (w not in alias or "/_files/" in key):
            alias[w] = key
    return alias.get(wix_id(url), k)
