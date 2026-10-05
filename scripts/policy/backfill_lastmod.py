"""השלמת מועד הפרסום באתר (Last-Modified) למסמכים שנאספו בלעדיו - בלי להוריד שוב (HEAD בלבד).

כ-60% מהמסמכים נאספו לפני שהתחלנו לרשום Last-Modified (או דרך התוסף). מועד הפרסום הוא המקור המועדף לתאריך
המסמך (timeline.version_date) ולבדיקת שנת המדיניות (pubdate.fits), ולכן משלימים אותו לכל המסמכים.

הפלט עובר דרך ה-inbox (כמו קבצים): policy/inbox/<LegalId>/_lastmod.json = {url: "Last-Modified" | null}.
ingest_inbox ממזג לאינדקס (null = נבדק ואין - כדי לא לבדוק שוב בכל ריצה). כך אותו מנגנון משמש בענן ובבית.

הרצה: python -m scripts.policy.backfill_lastmod [--via cloud|extension|all] [--only LEGAL_ID ...] [--limit N]
"""
import argparse, json, os, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

POL = Path(__file__).resolve().parents[2] / "policy"
SITES = Path(__file__).with_name("sites")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def lastmod(url):
    """Last-Modified של הכתובת, או None. HEAD; שרתים שלא תומכים -> GET עם Range קטן (בלי להוריד את הקובץ)."""
    if not url.lower().startswith("http") or "#upload/" in url:
        return None
    for method, kw in (("head", {}), ("get", {"headers": {**UA, "Range": "bytes=0-0"}, "stream": True})):
        try:
            r = getattr(requests, method)(url, headers=kw.get("headers", UA), timeout=20, allow_redirects=True,
                                          stream=kw.get("stream", False))
            lm = r.headers.get("Last-Modified")
            r.close()
            if r.status_code < 400 and lm:
                return lm
            if r.status_code < 400 and method == "get":
                return None
        except requests.RequestException:
            continue
    return None


def site_via(lid):
    f = SITES / f"{lid}.json"
    return json.loads(f.read_text("utf-8")).get("via", "cloud") if f.exists() else "cloud"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--via", default="cloud", choices=["cloud", "extension", "all"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    total = found = 0
    for idx in sorted((POL / "companies").glob("*/docs_index.json")):
        lid = idx.parent.name
        v = site_via(lid)
        if a.only and lid not in a.only:
            continue
        if not a.only and a.via != "all" and (v == "extension") != (a.via == "extension"):
            continue
        index = json.loads(idx.read_text("utf-8"))
        todo = [u for u, e in index.items() if not e.get("last_modified") and "last_modified_checked" not in e]
        if a.limit:
            todo = todo[:a.limit]
        if not todo:
            continue
        with ThreadPoolExecutor(8) as ex:
            res = dict(zip(todo, ex.map(lastmod, todo)))
        out = POL / "inbox" / lid / "_lastmod.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        prev = json.loads(out.read_text("utf-8")) if out.exists() else {}
        out.write_text(json.dumps({**prev, **res}, ensure_ascii=False, indent=1), "utf-8")
        n = sum(1 for x in res.values() if x)
        total += len(res); found += n
        print(f"[{lid}] checked={len(res)} last_modified={n}", flush=True)
    print(f"checked={total} found={found}")


if __name__ == "__main__":
    main()
