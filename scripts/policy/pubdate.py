"""מועד פרסום המסמך באתר - העוגן לתאריך הגרסה ולשנת המדיניות.

מקורות, לפי אמינות:
1. Last-Modified של השרת (נשמר ב-docs_index בכל הורדה - crawl.py / התוסף).
2. תיקיית ההעלאה בכתובת: "/20260126/" (cdn מנורה), "/uploads/2026/01/" (וורדפרס), "/2026/01/".
הצהרה לשנה Y מתפרסמת בין אוקטובר של Y-1 לסוף Y, ולכן מועד הפרסום מכריע כשהשנה בשם הקובץ ובתוכן סותרות.
"""
import re
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import unquote


def from_header(value):
    try:
        d = parsedate_to_datetime(value).date() if value else None
    except (TypeError, ValueError, IndexError):
        return None
    return d if d and date(2005, 1, 1) <= d <= date.today() else None


def from_url(url):
    u = unquote(url or "")
    m = re.search(r"/(20\d\d)(\d\d)(\d\d)/", u)                     # cdn.menoramivt.co.il/public/docs/20260126/
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"/uploads/(20\d\d)/(\d\d)/", u) or re.search(r"/(20\d\d)/(\d\d)/", u)  # wp-content/uploads/2026/01/
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), 1
    try:
        dt = date(y, mo, d)
    except ValueError:
        return None
    return dt if date(2005, 1, 1) <= dt <= date.today() else None


def published(url, ent):
    """(date, source) - מועד הפרסום, או (None, None)."""
    d = from_header((ent or {}).get("last_modified"))
    if d:
        return d, "last_modified"
    d = from_url(url)
    return (d, "url_folder") if d else (None, None)


def fits(year, pub):
    """שנת מדיניות year סבירה למסמך שפורסם ב-pub: מאוקטובר של year-1 ועד סוף year."""
    try:
        y = int(year)
    except (TypeError, ValueError):
        return False
    return (pub.year == y) or (pub.year == y - 1 and pub.month >= 10)
