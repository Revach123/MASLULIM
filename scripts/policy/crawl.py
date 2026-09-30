"""סריקת אתרי החברות (גמל/פנסיה/ביטוח ממניפסט הדוחות) ואיתור מסמכי מדיניות השקעות.

הרצה: python -m scripts.policy.crawl [--only LEGAL_ID ...] [--max-pages 60]
פלט (תיקיית policy/): docs_index.json (מקור אמת: url -> sha, תאריכי ראייה),
raw/<LegalId>/..., crawl_report.csv (מה נמצא/נכשל לכל חברה), new_docs.json (חדשים בריצה זו).

חייב לרוץ מחוץ ל-sandbox של הסשן (חסום) - ר' .github/workflows/policy_daily.yml.
חברות בלי seed ב-seeds.csv: ניחוש אתר בחיפוש (מסומן guessed בדוח - לאמת ידנית).
"""
import argparse, csv, hashlib, json, re, sys, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag, unquote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "policy"
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
    p = Path(__file__).with_name("seeds.csv")
    out = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["legal_id"]] = {"home": r["homepage"].strip(),
                                      "extra": [u for u in (r.get("extra_urls") or "").split("|") if u]}
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


def crawl_company(s, legal_id, home, extra, max_pages, depth_max=3):
    """מחזיר (docs, pages_visited, errors). docs = [{url, text, page}]"""
    dom = base_domain(home)
    seen, docs, errors = set(), {}, []
    q = deque([(home, 0)] + [(u, 1) for u in extra])
    visited = 0
    while q and visited < max_pages:
        url, d = q.popleft()
        url = urldefrag(url)[0]
        if url in seen:
            continue
        seen.add(url)
        if url.lower().split("?")[0].endswith(DOC_EXT):
            continue
        r = get(s, url)
        visited += 1
        if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
            errors.append(f"{url} -> {getattr(r, 'status_code', 'ERR')}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        page_ctx = score(soup.title.get_text(" ") if soup.title else "") + score(url)
        for a in soup.find_all("a", href=True):
            link = urldefrag(urljoin(url, a["href"]))[0]
            if not link.startswith("http"):
                continue
            text = a.get_text(" ", strip=True)
            sc = score(text) + score(unquote(link))
            path = link.lower().split("?")[0]
            dl_hint = re.search(r"download|הורד|אקסל|excel|xls|getfile|attachment", (text + " " + link).lower())
            if path.endswith(DOC_EXT) or (dl_hint and (sc > 0 or page_ctx >= 10)):
                # מסמך נחשב מדיניות אם הקישור/הטקסט מרמזים, או שהדף עצמו עוסק במדיניות
                if sc > 0 or page_ctx >= 10:
                    docs.setdefault(link, {"url": link, "text": text, "page": url})
            elif base_domain(link) == dom and d < depth_max and link not in seen and sc > 0:
                (q.appendleft if sc >= 10 else q.append)((link, d + 1))
        time.sleep(0.5)
    return docs, visited, errors


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--max-pages", type=int, default=60)
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    idx_path = OUT / "docs_index.json"
    index = json.loads(idx_path.read_text("utf-8")) if idx_path.exists() else {}
    cos, seeds = load_companies(), load_seeds()
    s = requests.Session()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report, new_docs = [], []

    for legal_id, c in sorted(cos.items()):
        if a.only and legal_id not in a.only:
            continue
        seed, status = seeds.get(legal_id), "seed"
        if not seed:
            g = guess_homepage(c["name"], s)
            seed, status = ({"home": g, "extra": []} if g else None), "guessed"
        if not seed:
            report.append([legal_id, c["name"], "", "no_site", 0, 0, ""]); continue
        docs, pages, errs = crawl_company(s, legal_id, seed["home"], seed["extra"], a.max_pages)
        got = 0
        for url, d in docs.items():
            r, code = download(s, url)
            if r is None:
                errs.append(f"{url} -> {code}"); continue
            sha = hashlib.sha256(r.content).hexdigest()
            ent = index.get(url)
            kind = "new" if ent is None else ("changed" if ent["sha256"] != sha else "unchanged")
            if kind != "unchanged":
                name = re.sub(r"[^\w.\-]", "_", unquote(urlparse(url).path.rsplit("/", 1)[-1]))[:80]
                ext = sniff_ext(r.content)
                if not name.lower().endswith(ext):
                    name += ext
                p = OUT / "raw" / legal_id / f"{sha[:12]}_{name}"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
                new_docs.append({"legal_id": legal_id, "url": url, "kind": kind, "file": str(p.relative_to(ROOT))})
                ent = {"legal_id": legal_id, "first_seen": now if ent is None else ent["first_seen"],
                       "file": str(p.relative_to(ROOT)), "parsed_sha": None}
            ent.update({"sha256": sha, "size": len(r.content), "last_seen": now,
                        "last_modified": r.headers.get("last-modified"), "link_text": d["text"],
                        "source_page": d["page"]})
            index[url] = ent
            got += 1
        report.append([legal_id, c["name"], seed["home"], status, pages, got, " | ".join(errs[:5])])
        print(f"[{legal_id}] {c['name']}: pages={pages} docs={got} errs={len(errs)}", flush=True)

    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "new_docs.json").write_text(json.dumps(new_docs, ensure_ascii=False, indent=1), "utf-8")
    with open(OUT / "crawl_report.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["legal_id", "company", "homepage", "site_source", "pages", "docs", "errors"])
        w.writerows(report)
    print(f"[crawl] new/changed docs this run: {len(new_docs)}")


if __name__ == "__main__":
    main()
