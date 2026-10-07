"""סריקת אתרי החברות לאיתור והורדה של דוחות "מרכיבי תשואה" (פירוט תרומת אפיקי ההשקעה לתשואה), לכל ההיסטוריה.

הרצה: python -m scripts.returns.crawl --only <LegalId> [--no-browser] [--no-search]
פלט (RETURNS_OUT, ברירת מחדל returns/companies/<LegalId>): docs_index.json (url -> sha, קובץ, תאריכים - אותו מבנה
כמו במדיניות), raw/<sha12>_<name>, site_snapshot.json, discovered.json (עמודים שנמצאו), crawl_report.json.

אותם רכיבים כמו סריקת המדיניות (scripts/policy): רינדור בדפדפן, פתיחת אקורדיונים/לשוניות/iframes, לכידת הורדות
בלחיצה, הורדה דרך הדפדפן כשנחסם - רק ציון העמודים והקישורים מכוון ל"מרכיבי תשואה" במקום "מדיניות השקעה".
מקורות לעמודים, לפי הסדר:
  1. returns_pages בהגדרות האתר (scripts/policy/sites/<LegalId>.json) - {url, product}; {year} מורחב לכל שנה
  2. עמודים שנמצאו בריצות קודמות (discovered.json)
  3. קישורים לעמודי/קבצי מרכיבי תשואה בתמונת המצב של סריקת המדיניות (policy/companies/<id>/site_snapshot)
  4. מפת האתר (sitemap) + חיפוש "<שם החברה> מרכיבי תשואה" (DuckDuckGo) + דף הבית בעומק 2
בנוסף: קבצי מרכיבי תשואה שסריקת המדיניות כבר הורידה (policy/companies/<id>/raw) נקלטים בלי הורדה מחדש.
"""
import argparse, hashlib, json, os, re, shutil, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

import scripts.policy.crawl as pc
import scripts.policy.snapshot as ps
from scripts.policy.urlkey import find_key

ROOT = Path(__file__).resolve().parents[2]
SITES = ROOT / "scripts" / "policy" / "sites"
RET_ROOT = ROOT / "returns"

# דוח מרכיבי תשואה: בטקסט הקישור, בשם הקובץ או בכתובת העמוד
RETURNS_RX = re.compile(r"מרכיבי[-_ ]*(ה)?תשוא|תרומ(ת|ה)[-_ ]*(ה)?(אפיקי|לתשואה)|פירוט[-_ ]*תרומת|"
                        r"yield_?\d|yield[-_]?(elements|components)|return[-_]?(elements|components)|merkivei|mrkivei|"
                        r"nostro[-_ ]*yield|תשוא(ה|ות)[-_ ]*לפי[-_ ]*אפיק|tesuah[-_ ]*lefi[-_ ]*afikim|tsua[-_ ]*lefi", re.I)
# ("yield" לבד - כתבות "תשואות אג"ח" במיטב; "tsua" לבד - כל עמוד תשואות)
# עמוד ניווט סביר בדרך לדוחות (ציון נמוך)
WEAK = ["תשואות", "תשואה", "דוחות", "דיווחים", "השקעות", "נכסי הקופה", "נכסי הקרן", "מידע לעמיתים", "מידע לחוסכים",
        "מידע פיננסי", "פרסומים", "גילוי", "investments", "reports", "returns", "yields"]
# קבצים שאינם מרכיבי תשואה גם כשהם באותו עמוד (רשימות נכסים, מדיניות, דמי ניהול...)
OTHER = re.compile(r"רשימ(ת|ות)[-_ ]*(ה)?נכסים|נכסים[-_ ]*ברמת|מדיניו?ת[-_ ]*(ה)?השקע|דמי[-_ ]*ניהול|תקנון|דו\"?ח(ות)?[-_ ]*(ה)?(כספי|שנתי|תקופתי|רבעוני)|"
                   r"מצגת|esg|כתב[-_ ]*שירות|גילוי[-_ ]*נאות|הוצאות[-_ ]*ישירות|עמלות|ניהול[-_ ]*חיצוני|אשראי[-_ ]*לא[-_ ]*סחיר|"
                   r"חוב(ות)?[-_ ]*בעייתי|השקעות[-_ ]*מהותיות|הצבעות|אסיפות|מוטב|investment[-_ ]*polic|holdings|portfolio[-_ ]*list|"
                   r"policy|תשואות[-_ ]*אקטואריות|איזון[-_ ]*אקטוארי|מאזן[-_ ]*אקטוארי", re.I)
DOC_EXTS = ("xlsx", "xls", "pdf", "xlsm", "csv", "htm", "html")


def rscore(text: str) -> int:
    t = (text or "").lower()
    return 10 * bool(RETURNS_RX.search(t)) + sum(k.lower() in t for k in WEAK)


def retarget():
    """מכוונים את סורק המדיניות למרכיבי תשואה (תהליך נפרד - לא נוגע בריצת המדיניות)."""
    ps.score = rscore
    pc.score = rscore
    pc.POLICY = RETURNS_RX   # עדיפות בתור הסריקה (snapshot._prio) ועמודים ממפת האתר (sitemap_policy_pages)
    pc.NOISE = re.compile(r"esg|פרטיות|privacy|מבצע|careers?|jobs|magazine|blog|news|press", re.I)


def load_cfg(lid: str) -> dict:
    p = SITES / f"{lid}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def snapshot_seeds(lid: str):
    """עמודים וקבצים של מרכיבי תשואה שסריקת המדיניות כבר ראתה (קישורים בתפריט/בעמודי המדיניות)."""
    p = ROOT / "policy" / "companies" / lid / "site_snapshot" / f"{lid}.json"
    pages, docs = [], []
    if not p.exists():
        return pages, docs
    snap = json.loads(p.read_text("utf-8"))
    for page_url, pg in snap.get("pages", {}).items():
        if RETURNS_RX.search(unquote(page_url)):
            pages.append(page_url)
        for it in pg.get("items", []):
            blob = (it.get("text") or "") + " " + unquote(it.get("href") or "")
            if not RETURNS_RX.search(blob) or it.get("local"):
                continue
            (docs if it.get("doc") else pages).append(it["href"] if not it.get("doc") else {**it, "page": page_url})
    return list(dict.fromkeys(pages)), docs


def import_from_policy(lid: str, index: dict, out: Path, now: str):
    """קבצי מרכיבי תשואה שנאספו בטעות כמסמכי מדיניות - מועתקים לכאן (בלי הורדה)."""
    p = ROOT / "policy" / "companies" / lid / "docs_index.json"
    if not p.exists():
        return 0
    n = 0
    known = {e.get("sha256") for e in index.values()}
    for url, e in json.loads(p.read_text("utf-8")).items():
        blob = unquote(url) + " " + (e.get("link_text") or "")
        f = ROOT / (e.get("file") or "")
        if not RETURNS_RX.search(blob) or not e.get("file") or not f.exists() or e.get("sha256") in known:
            continue
        if OTHER.search(blob) and not re.search(r"מרכיבי|תרומת", blob):
            continue
        dst = out / "raw" / f.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst)
        index[url] = {"legal_id": lid, "first_seen": e.get("first_seen") or now, "last_seen": e.get("last_seen") or now,
                      "file": os.path.relpath(dst, ROOT), "sha256": e["sha256"], "size": e.get("size"),
                      "link_text": e.get("link_text"), "source_page": e.get("source_page"), "product": e.get("product"),
                      "last_modified": e.get("last_modified"), "via": "policy_index", "parsed_sha": None}
        known.add(e["sha256"])
        n += 1
    return n


def select_docs(pages: dict):
    """-> {url: item}: קבצים שהם מרכיבי תשואה לפי הטקסט/השם, או כל גיליון/PDF בעמוד של מרכיבי תשואה (בלי קבצים אחרים)."""
    out = {}
    for page_url, p in pages.items():
        ctx = bool(RETURNS_RX.search(unquote(page_url)))  # לא לפי טקסט העמוד: התפריט ("מרכיבי תשואה") מופיע בכל עמוד
        for i in p.get("items", []):
            if not i.get("doc") and "network" not in (i.get("text") or "") and "xhr" not in (i.get("text") or ""):
                continue
            href, text = i["href"], i.get("text") or ""
            blob = unquote(href) + " " + text
            ext = urlparse(href).path.lower().rsplit(".", 1)[-1] if "." in urlparse(href).path else ""
            strong = bool(RETURNS_RX.search(blob))
            if OTHER.search(blob) and not re.search(r"מרכיבי|תרומת|yield", blob, re.I):
                continue
            if strong or (ctx and (ext in DOC_EXTS or i.get("local"))):
                out.setdefault(unquote(href) if not i.get("local") else href, {**i, "page": page_url})
    return out


def year_pages(urls):
    return pc.expand_templates(urls, first_year=2015)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", required=True)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-search", action="store_true")
    a = ap.parse_args()
    retarget()
    cos = pc.load_companies()
    s = requests.Session()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pw_cm = pw = None
    if not a.no_browser:
        try:
            from playwright.sync_api import sync_playwright
            pw_cm = sync_playwright(); pw = pw_cm.start()
        except Exception as e:
            print(f"[returns] playwright לא זמין: {e!r}")
    for lid in a.only:
        out = Path(os.environ.get("RETURNS_OUT") or (RET_ROOT / "companies" / lid))
        if not out.is_absolute():
            out = ROOT / out
        out.mkdir(parents=True, exist_ok=True)
        crawl_company(s, pw, lid, cos.get(lid, {}).get("name") or load_cfg(lid).get("name") or lid, out, now, a)
    if pw_cm:
        pc.close_browser()
        pw.stop()


def crawl_company(s, pw, lid, name, out, now, a):
    t0 = time.monotonic()
    cfg = load_cfg(lid)
    idx_path = out / "docs_index.json"
    index = json.loads(idx_path.read_text("utf-8")) if idx_path.exists() else {}
    report = {"legal_id": lid, "company": name, "run": now, "errors": [], "seeds": {}}
    report["imported_from_policy"] = import_from_policy(lid, index, out, now)

    disc_path = out / "discovered.json"
    disc = json.loads(disc_path.read_text("utf-8")) if disc_path.exists() else {}
    cfg_pages = [p["url"] if isinstance(p, dict) else p for p in cfg.get("returns_pages", [])]
    products = {(p["url"] if isinstance(p, dict) else p): (p.get("product") if isinstance(p, dict) else None)
                for p in cfg.get("returns_pages", [])}
    snap_pages, snap_docs = snapshot_seeds(lid)
    # עמודי המדיניות של החברה ועמוד האב שלהם - דוחות מרכיבי התשואה לרוב באותו אזור באתר (עמוד המסלול / "מידע לעמיתים")
    pol_pages = []
    for u in [x["url"] for x in cfg.get("pages", []) if "{year}" not in x.get("url", "")] if not cfg.get("returns_pages") else []:
        pol_pages.append(u)
        pr = urlparse(u)
        parent = pr.path.rstrip("/").rsplit("/", 1)[0]
        if parent and parent.count("/") >= 1:
            pol_pages.append(f"{pr.scheme}://{pr.netloc}{parent}/")
    snap_pages = snap_pages + [u for u in dict.fromkeys(pol_pages) if u not in snap_pages]
    home = cfg.get("home") or disc.get("home") or ""
    pdisc = ROOT / "policy" / "companies" / lid / "discovered.json"
    if not home and pdisc.exists():
        home = json.loads(pdisc.read_text("utf-8")).get("home") or ""
    seeds = year_pages(cfg_pages) + [u for u in disc.get("pages", []) if u not in cfg_pages] + snap_pages
    report["seeds"] = {"config": len(cfg_pages), "discovered": len(disc.get("pages", [])), "policy_snapshot": len(snap_pages),
                       "policy_snapshot_docs": len(snap_docs)}
    if not home:
        report["errors"].append("no_home")
    elif cfg.get("via") == "extension" and os.environ.get("RETURNS_FORCE_CLOUD") != "1" and not cfg.get("returns_cloud"):
        report["errors"].append("via_extension (נסרק מהמחשב הביתי)")
        home = ""
    pages = {}
    if home:
        home = pc.resolve_home(s, home)
        searched = []
        if not a.no_search and not cfg_pages and not disc.get("pages"):
            q = f"{pc._short_name(name)} מרכיבי תשואה"
            searched = [u for u in pc.web_search(s, q) if pc.base_domain(u) == pc.base_domain(home)]
            report["seeds"]["search"] = len(searched)
        sitemap = pc.sitemap_policy_pages(s, home) if not cfg_pages else []
        report["seeds"]["sitemap"] = len(sitemap)
        extra = list(dict.fromkeys(seeds + searched + sitemap))
        os.environ["POLICY_CRAWL_BUDGET"] = str(cfg.get("returns_crawl_budget") or 1500)
        os.environ["POLICY_PAGE_BUDGET"], os.environ["POLICY_DL_BUDGET"] = (str(x) for x in (cfg.get("returns_budget") or [90, 240]))
        pages = ps.snapshot_company(s, pw, home, extra, products, max_pages=max(int(cfg.get("returns_max_pages") or 45), len(extra) + 15),
                                    follow=cfg.get("returns_follow"), click_texts=cfg.get("returns_click_texts"))
        # עמודים שנמצאו ובהם קבצי מרכיבי תשואה - נשמרים כנקודת פתיחה לריצות הבאות (החיפוש לא תמיד זמין)
        good = [u for u, p in pages.items() if p.get("status") == 200 and any(
            i.get("doc") and RETURNS_RX.search((i.get("text") or "") + " " + unquote(i["href"])) for i in p.get("items", []))
            or (p.get("status") == 200 and RETURNS_RX.search(unquote(u)))]
        disc = {"home": home, "pages": list(dict.fromkeys(disc.get("pages", []) + good))[:60]}
        disc_path.write_text(json.dumps(disc, ensure_ascii=False, indent=1), "utf-8")
        (out / "site_snapshot.json").write_text(json.dumps({"legal_id": lid, "taken": now, "pages": pages},
                                                           ensure_ascii=False, indent=1), "utf-8")
    docs = select_docs(pages)
    for d in snap_docs:  # קבצים שנראו בסריקת המדיניות
        docs.setdefault(unquote(d["href"]), d)
    for du in cfg.get("returns_docs", []):
        docs.setdefault(unquote(du), {"href": du, "text": "(config docs)", "doc": True, "page": cfg_pages[0] if cfg_pages else home})
    if cfg.get("returns_exclude"):
        ex = re.compile(cfg["returns_exclude"])
        docs = {k: d for k, d in docs.items() if not ex.search(unquote(k) + " " + unquote(d.get("page") or ""))}
    report["pages"] = len(pages)
    report["pages_failed"] = [f"{u}: {p['status']}" for u, p in pages.items() if p.get("status") != 200][:8]
    report["candidates"] = len(docs)
    new = got = 0
    for key, d in docs.items():
        if time.monotonic() - t0 > float(os.environ.get("RETURNS_DL_BUDGET", "2100")):
            report["errors"].append("download budget reached - ממשיכים בריצה הבאה"); break
        url = d["href"]
        old = index.get(find_key(index, url))
        lost = bool(old) and old.get("not_returns") and not (ROOT / (old.get("file") or "-")).exists() \
            and RETURNS_RX.search(unquote(url) + " " + (d.get("text") or ""))  # נמחק בטעות (PDF שלא פוענח) - מורידים שוב
        if old and old.get("sha256") and pc.DOC_PATH.search(urlparse(url).path) and not lost:
            old["last_seen"] = now  # קובץ קבוע שכבר נאסף (או נבדק ונפסל) - לא מורידים שוב
            if pc.visible_text_better(old.get("link_text"), d.get("text")):
                old["link_text"] = d.get("text")
            got += 1
            continue
        lm = d.get("last_modified")
        if d.get("local"):
            content, code = (Path(d["local"]).read_bytes() if Path(d["local"]).exists() else None), 200
        else:
            r, code = pc.download(s, url)
            content = r.content if r is not None else None
            lm = (r.headers.get("Last-Modified") if r is not None else None) or lm
        if content is None and pw and code not in (404, 410, "not_a_document") and not d.get("local"):
            content = pc.download_browser(pw, url, d.get("page"))
            code = 200 if content else code
            lm = pc._BROWSER.get("last_modified") or lm
        ext = pc.sniff_ext(content, url) if content else None
        if content is None or ext is None:
            report["errors"].append(f"{unquote(url)[-90:]} -> {code}")
            continue
        sha = hashlib.sha256(content).hexdigest()
        ukey = find_key(index, url)
        ent = index.get(ukey)
        if ent is None or ent.get("sha256") != sha or not (ROOT / (ent.get("file") or "-")).exists():
            fname = re.sub(r"[^\w.\-]", "_", unquote(url.split("#download=")[-1] if "#download=" in url
                                                       else urlparse(url).path.rsplit("/", 1)[-1]))[:80]
            if not fname.lower().endswith(ext):
                fname += ext
            p = out / "raw" / f"{sha[:12]}_{fname}"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            prev = ent or {}
            ent = {"legal_id": lid, "first_seen": prev.get("first_seen", now), "file": os.path.relpath(p, ROOT),
                   "parsed_sha": None, "history": prev.get("history", [])}
            if prev.get("sha256"):
                ent["history"].append({"sha256": prev["sha256"], "file": prev.get("file"), "last_seen": prev.get("last_seen")})
            new += 1
        if lm:
            ent["last_modified"] = lm
        ent.update({"sha256": sha, "size": len(content), "last_seen": now, "link_text": d.get("text"),
                    "source_page": d.get("page"), "product": (pages.get(d.get("page")) or {}).get("product"), "via": "cloud"})
        index[ukey] = ent
        got += 1
    report.update(docs=got, new_docs=new, index_size=len(index), seconds=round(time.monotonic() - t0))
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    (out / "crawl_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    print(f"[returns] {lid} {name}: pages={len(pages)} candidates={len(docs)} docs={got} new={new} "
          f"imported={report['imported_from_policy']} errors={len(report['errors'])}", flush=True)


if __name__ == "__main__":
    main()
