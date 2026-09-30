"""סריקת אתרי החברות (גמל/פנסיה/ביטוח ממניפסט הדוחות) ואיתור מסמכי מדיניות השקעות.

הרצה: python -m scripts.policy.crawl [--only LEGAL_ID ...] [--max-pages 60]
פלט (תיקיית policy/): docs_index.json (מקור אמת: url -> sha, תאריכי ראייה),
raw/<LegalId>/..., crawl_report.csv (מה נמצא/נכשל לכל חברה), new_docs.json (חדשים בריצה זו).

חייב לרוץ מחוץ ל-sandbox של הסשן (חסום) - ר' .github/workflows/policy_daily.yml.
חברות בלי seed ב-seeds.csv: ניחוש אתר בחיפוש (מסומן guessed בדוח - לאמת ידנית).
"""
import argparse, csv, hashlib, json, os, re, sys, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag, unquote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / (__import__("os").environ.get("POLICY_OUT") or "policy")  # ריצה לחברה: policy/companies/<LegalId>
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
DOC_EXT = (".pdf", ".xlsx", ".xls", ".docx", ".doc")
# משקל מילות מפתח: מסמך מדיניות (גבוה) מול דפי ניווט סבירים (נמוך)
STRONG = ["מדיניות השקעות", "מדיניות ההשקעות", "מדיניות השקעה", "מדיניות ההשקעה",
          "investment policy", "investment_policy", "investmentpolicy", "מדיניות_השקעות"]
WEAK = ["מדיניות", "מסמכי מדיניות", "מידע לחוסכים", "מידע לעמיתים", "דוחות ותקנונים",
        "תקנון", "גילוי נאות", "השקעות", "מסלולי השקעה", "investor", "policy", "reports"]


def score(text: str) -> int:
    t = text.lower()
    return 10 * sum(k.lower() in t for k in STRONG) + sum(k.lower() in t for k in WEAK)


def base_domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "org", "gov", "ac", "net"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def load_companies() -> dict[str, dict]:
    cos: dict[str, dict] = {}
    with open(ROOT / "manifest.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = cos.setdefault(r["LegalId"], {"name": r["ParentCorpName"].strip(), "systems": set()})
            c["systems"].add(r["SystemName"])
    return cos


def load_seeds() -> dict[str, dict]:
    """scripts/policy/sites/<LegalId>.json: {home, pages:[{product,url}], browser}. url יכול להכיל {year}."""
    out = {}
    for p in sorted(Path(__file__).with_name("sites").glob("*.json")):
        cfg = json.loads(p.read_text("utf-8"))
        pages = cfg.get("pages", [])
        out[cfg["legal_id"]] = {"home": cfg["home"], "extra": [x["url"] for x in pages],
                                "products": {x["url"]: x.get("product") for x in pages}, "browser": cfg.get("browser", "headless")}
    return out


def guess_homepage(name: str, s: requests.Session) -> str | None:
    """fallback בלבד: DuckDuckGo HTML. התוצאה לא מאומתת."""
    try:
        r = s.post("https://html.duckduckgo.com/html/", data={"q": f"{name} אתר רשמי"}, timeout=20)
        for a in BeautifulSoup(r.text, "html.parser").select("a.result__a"):
            href = a.get("href", "")
            m = re.search(r"uddg=([^&]+)", href)
            url = unquote(m.group(1)) if m else href
            if url.startswith("http") and not re.search(r"facebook|linkedin|wikipedia|globes|bizportal|themarker|ctech|maya", url):
                p = urlparse(url)
                return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return None


def get(s: requests.Session, url: str, **kw):
    for i in range(3):
        try:
            r = s.get(url, timeout=30, headers={"User-Agent": UA, "Accept-Language": "he,en;q=0.8"}, **kw)
            if r.status_code in (429, 503):
                time.sleep(2 ** i * 2); continue
            return r
        except requests.RequestException:
            time.sleep(2 ** i)
    return None


def sniff_ext(content: bytes) -> str | None:
    """סוג הקובץ לפי תוכן (קישורי הורדה לרוב בלי סיומת). None = לא מסמך."""
    if content[:4] == b"PK\x03\x04":
        return ".docx" if b"word/" in content[:4000] else ".xlsx"
    if content[:4] == b"\xd0\xcf\x11\xe0":
        return ".xls"
    if content[:5] == b"%PDF-":
        return ".pdf"
    return None


def download(s, url):
    r = get(s, url, stream=False)
    if r is None or r.status_code != 200:
        return None, getattr(r, "status_code", "ERR")
    if sniff_ext(r.content) is None:
        return None, "not_a_document"
    return r, 200


NOISE = re.compile(r"esg|אחראי|תגמול|פרטיות|privacy|תקנון|מבצע|גילוי[-_ ]נאות|דוח(ות)?[-_ ]כספי|מצגת|presentation|"
                   r"investor|equal|שכר[-_ ]שווה|פוליסה|annuity|premi|מנתחים|אמות[-_ ]מידה|ממשל", re.I)
POLICY = re.compile(r"מדיניות[-_ ]*(ה)?השקעה|מדיניות[-_ ]*(ה)?השקעות|מדיניות[-_ ]*מוצהרת|הצהרת[-_ ]*(מדיניות|השקעות)|"
                    r"הצהרה[-_ ]*על[-_ ]*מדיניות|investment[-_ ]*polic|expected[-_ ]*investment|statement[-_ ]*investment", re.I)


def expand_templates(urls, first_year=2019):
    """כתובות עם {year} מורחבות לכל שנה (אתרים שמחזיקים דף/מסנן לכל שנה, למשל כלל/הפניקס)."""
    out = []
    for u in urls:
        if "{year}" in u:
            out += [u.replace("{year}", str(y)) for y in range(datetime.now().year, first_year - 1, -1)]
        else:
            out.append(u)
    return out


def select_docs(pages: dict, extra: list[str]):
    """בוחר מסמכי מדיניות מתוך תמונת המצב: מילות מדיניות בטקסט/שם קובץ (בלי רעש), או גיליון אקסל בעמוד
    מדיניות/seed. -> {decoded_url: item}. כפילויות URL מקודד/לא מקודד מתמזגות."""
    ctx_pages = {u for u in pages if u in extra or POLICY.search(unquote(u))}
    out = {}
    for page_url, p in pages.items():
        for i in p["items"]:
            if not i["doc"] and "network" not in i["text"] and "xhr" not in i["text"]:
                continue
            href, blob = i["href"], unquote(i["href"]) + " " + i["text"]
            ext = href.lower().split("?")[0].rsplit(".", 1)[-1]
            ok = bool(POLICY.search(blob)) and not NOISE.search(blob)
            ok = ok or (page_url in ctx_pages and ext in ("xlsx", "xls") and not NOISE.search(blob))
            if ok:
                out.setdefault(unquote(href), {**i, "page": page_url})
    return out


def download_browser(pw, url):
    """הורדה דרך הדפדפן (קוקיז/Headers אמיתיים) כשבקשת requests נחסמת."""
    b = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None, headless=os.environ.get("POLICY_HEADED") != "1",
                           args=["--disable-blink-features=AutomationControlled"])
    try:
        ctx = b.new_context(user_agent=UA, locale="he-IL")
        r = ctx.request.get(url, timeout=60000)
        return r.body() if r.status == 200 else None
    except Exception:
        return None
    finally:
        b.close()


def main():
    from .snapshot import snapshot_company, diff as snap_diff  # lazy: snapshot מייבא מכאן
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    idx_path = OUT / "docs_index.json"
    index = json.loads(idx_path.read_text("utf-8")) if idx_path.exists() else {}
    cos, seeds = load_companies(), load_seeds()
    s = requests.Session()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report, new_docs, all_changes = [], [], []
    done: set[str] = set()  # מסמך שכבר עובד בריצה זו (חברות באותו אתר)
    pw_cm = pw = None
    if not a.no_browser:
        try:
            from playwright.sync_api import sync_playwright
            pw_cm = sync_playwright(); pw = pw_cm.start()
        except Exception as e:
            print(f"[crawl] playwright לא זמין: {e!r}")

    for legal_id, c in sorted(cos.items()):
        if a.only and legal_id not in a.only:
            continue
        seed = seeds.get(legal_id)
        if not seed:
            report.append([legal_id, c["name"], "", "no_seed", 0, 0, ""]); continue
        extra = expand_templates(seed["extra"])
        products = {u: seed["products"].get(t) for t in seed["extra"] for u in expand_templates([t])}
        pages = snapshot_company(s, pw, seed["home"], extra, products, max_pages=40)
        # תמונת מצב + שינויים מול הריצה הקודמת (פריט חדש/הוסר/טקסט השתנה) - זה מנגנון זיהוי העדכונים היומי
        snap_path = OUT / "site_snapshot" / f"{legal_id}.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(snap_path.read_text("utf-8")) if snap_path.exists() else None
        changes = snap_diff(old["pages"], pages) if old else []
        for x in changes:
            x.update(legal_id=legal_id, company=c["name"], detected=now)
        # עמוד שנכשל בריצה זו שומר את התמונה הקודמת שלו - אחרת בריצה הבאה כל הפריטים ייראו "חדשים"
        keep = {u: {**old["pages"][u], "status": p["status"]} for u, p in pages.items()
                if p["status"] != 200 and old and u in old["pages"]}
        snap_path.write_text(json.dumps({"legal_id": legal_id, "company": c["name"], "taken": now, "pages": {**pages, **keep}},
                                        ensure_ascii=False, indent=1), "utf-8")
        all_changes += changes
        docs = select_docs(pages, set(extra))
        errs = [f"{u}: {p['status']}" for u, p in pages.items() if p["status"] != 200][:5]
        got = 0
        for key, d in docs.items():
            if key in done:
                continue
            done.add(key)
            url = d["href"]
            r, code = download(s, url)
            content = r.content if r is not None else None
            if content is None and pw and code in (403, "ERR"):
                content = download_browser(pw, url)
                code = 200 if content else code
            if content is None or sniff_ext(content) is None:
                errs.append(f"{url[-80:]} -> {code}"); continue
            sha = hashlib.sha256(content).hexdigest()
            ukey = unquote(url)
            ent = index.get(ukey)
            kind = "new" if ent is None else ("changed" if ent["sha256"] != sha else "unchanged")
            if kind != "unchanged":
                name = re.sub(r"[^\w.\-]", "_", unquote(urlparse(url).path.rsplit("/", 1)[-1]))[:80]
                ext = sniff_ext(content)
                if not name.lower().endswith(ext):
                    name += ext
                p = OUT / "raw" / legal_id / f"{sha[:12]}_{name}"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
                new_docs.append({"legal_id": legal_id, "url": ukey, "kind": kind, "file": str(p.relative_to(ROOT))})
                prev = ent or {}
                ent = {"legal_id": legal_id, "first_seen": prev.get("first_seen", now), "file": str(p.relative_to(ROOT)),
                       "parsed_sha": None, "history": prev.get("history", [])}
                if prev.get("sha256"):
                    ent["history"].append({"sha256": prev["sha256"], "file": prev.get("file"), "last_seen": prev.get("last_seen")})
            ent.update({"sha256": sha, "size": len(content), "last_seen": now, "link_text": d["text"],
                        "source_page": d["page"], "product": pages[d["page"]].get("product")})
            index[ukey] = ent
            got += 1
        report.append([legal_id, c["name"], seed["home"], "seed", len(pages), got, " | ".join(errs)[:400]])
        print(f"[{legal_id}] {c['name']}: pages={len(pages)} docs={got} errs={len(errs)}", flush=True)
    if pw_cm:
        pw.stop()

    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "site_changes.json").write_text(json.dumps(all_changes, ensure_ascii=False, indent=1), "utf-8")
    if all_changes:
        log = OUT / "site_changes_log.csv"
        new_file = not log.exists()
        with open(log, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, ["detected", "legal_id", "company", "kind", "page", "text", "href"], extrasaction="ignore")
            if new_file:
                w.writeheader()
            w.writerows(all_changes)
    (OUT / "new_docs.json").write_text(json.dumps(new_docs, ensure_ascii=False, indent=1), "utf-8")
    with open(OUT / "crawl_report.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["legal_id", "company", "homepage", "site_source", "pages", "docs", "errors"])
        w.writerows(report)
    print(f"[crawl] new/changed docs this run: {len(new_docs)}")


if __name__ == "__main__":
    main()
