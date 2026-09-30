"""תמונת מצב של מבנה עמודי המדיניות באתרי החברות + זיהוי עדכונים, בלי להוריד את המסמכים.

הרצה: python -m scripts.policy.snapshot [--only LEGAL_ID ...] [--no-browser]
לכל חברה: סורק את עמודי ה-seed (+extra_urls) ועמודים קשורים למדיניות (עומק 2), ושומר לכל עמוד את
רשימת הפריטים הרלוונטיים (טקסט קישור, href, שנה, האם מסמך) ואת האש טקסט העמוד.
עמוד שנראה דינמי (אקורדיון/לשוניות, מעט קישורים) מרונדר בדפדפן (playwright): פותח אקורדיונים
ולשוניות ואוסף שוב. השוואה מול הריצה הקודמת -> policy/site_changes.json + policy/site_changes_log.csv.

פלט: policy/site_snapshot/<LegalId>.json, site_changes.json, site_changes_log.csv, site_report.csv
"""
import argparse, csv, hashlib, json, os, re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urldefrag, unquote

from bs4 import BeautifulSoup

from .crawl import DOC_EXT, UA, base_domain, get, load_companies, load_seeds, score

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / (__import__("os").environ.get("POLICY_OUT") or "policy")  # ריצה לחברה: policy/companies/<LegalId>
DL_HINT = re.compile(r"download|הורד|אקסל|excel|xls|getfile|attachment")
MIN_LINKS_STATIC = 3  # פחות מזה קישורי מדיניות ב-HTML הגולמי -> מנסים דפדפן


def year_of(text: str):
    m = re.search(r"(20[12]\d)", text)
    return m.group(1) if m else None


def keep_item(text: str, href: str) -> bool:
    low = (text + " " + unquote(href)).lower()
    return (score(text) + score(unquote(href)) > 0 or href.lower().split("?")[0].endswith(DOC_EXT)
            or bool(DL_HINT.search(low)))


def items_from_anchors(anchors, page_url, dom):
    out = {}
    for a in anchors:
        href = urldefrag(urljoin(page_url, a["href"]))[0]
        text = re.sub(r"\s+", " ", a["text"]).strip()
        is_iframe = text == "(iframe)"
        if not href.startswith("http") or not (is_iframe or keep_item(text, href)):
            continue
        out[href] = {"text": text, "href": href, "year": year_of(text + " " + unquote(href)), "iframe": is_iframe,
                     "doc": href.lower().split("?")[0].endswith(DOC_EXT) or bool(DL_HINT.search(text.lower())),
                     "internal": base_domain(href) == dom}
    return out


def fetch_static(s, url):
    r = get(s, url)
    if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return None, getattr(r, "status_code", "ERR"), ""
    soup = BeautifulSoup(r.content, "html.parser")  # bytes: הקידוד נקבע מה-meta/כותרות, לא ניחוש requests
    anchors = [{"href": a["href"], "text": a.get_text(" ", strip=True)} for a in soup.find_all("a", href=True)]
    return anchors, 200, soup.get_text(" ", strip=True)


FILE_RX = re.compile(r"""["'(=\s]((?:https?:)?[\w\-./%:?=&~א-ת]+?\.(?:xlsx|xls|pdf|docx))(?=["')\s&<,]|$)""", re.I)


def fetch_browser(pw, url):
    """רינדור: רשת שקטה, פתיחת אקורדיונים/לשוניות, ולכידת בקשות רשת (JSON עם נתיבי קבצים, קבצים ישירים, iframes).
    -> (anchors, status, body_text)"""
    b = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None, headless=os.environ.get("POLICY_HEADED") != "1",
                           args=["--disable-blink-features=AutomationControlled"])
    try:
        ctx = b.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1400, "height": 1000})
        pg = ctx.new_page()
        net = []

        def on_response(r):
            try:
                ct = r.headers.get("content-type", "")
                u = r.url
                if re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", u, re.I) or re.search(r"spreadsheet|pdf|msword|excel", ct):
                    net.append({"href": u, "text": "(network file)"})
                elif "json" in ct or "javascript" not in ct and "text/html" not in ct and "xml" in ct:
                    body = r.text()
                    if len(body) < 3_000_000:
                        for m in FILE_RX.findall(body):
                            net.append({"href": urljoin(u, m.replace("\\/", "/")), "text": "(xhr)"})
            except Exception:
                pass

        pg.on("response", on_response)
        resp = pg.goto(url, wait_until="networkidle", timeout=60000)
        status = resp.status if resp else 200
        seen, anchors = set(), []

        def collect():
            for a in pg.eval_on_selector_all("a[href]", "els=>els.map(e=>({href:e.href,text:e.innerText||e.textContent||''}))"):
                if (a["href"], a["text"].strip()) not in seen:
                    seen.add((a["href"], a["text"].strip())); anchors.append(a)
            for f in pg.eval_on_selector_all("iframe[src]", "els=>els.map(e=>e.src)"):
                if (f, "iframe") not in seen:
                    seen.add((f, "iframe")); anchors.append({"href": f, "text": "(iframe)"})

        collect()
        for sel in ('[aria-expanded="false"]:not(a)', "details:not([open]) > summary", '[role="tab"]',
                    "button:has-text('הצג עוד')", "button:has-text('עוד')", "[class*=accordion] [class*=header]",
                    "[class*=year]:not(a)"):
            for el in pg.query_selector_all(sel)[:120]:
                try:
                    el.click(timeout=800); pg.wait_for_timeout(150)
                except Exception:
                    pass
            collect()
        pg.wait_for_timeout(1500)
        collect()
        anchors += [x for x in net if (x["href"], x["text"]) not in seen]
        text = pg.inner_text("body")
        return anchors, (200 if status < 400 else status), text
    except Exception as e:
        return None, f"browser:{type(e).__name__}", ""
    finally:
        b.close()


def product_of(url: str, text: str, hint: str | None):
    """גמל / פנסיה / ביטוח: לפי תווית ב-seed, ואחרת לפי כתובת/טקסט העמוד."""
    if hint:
        return hint
    t = unquote(url) + " " + text[:300]
    hits = [p for p, pat in (("פנסיה", r"פנסי|pension"), ("גמל", r"גמל|gemel|השתלמות"), ("ביטוח", r"ביטוח|insurance")) if re.search(pat, t, re.I)]
    return "+".join(hits) or None


def snapshot_company(s, pw, home, extra, products=None, max_pages=15, depth_max=2):
    products = products or {}
    dom = base_domain(home)
    pages, seen = {}, set()
    q = deque([(u, 0) for u in [home] + extra])
    while q and len(pages) < max_pages:
        url, d = q.popleft()
        url = urldefrag(url)[0]
        if url in seen:
            continue
        seen.add(url)
        anchors, status, text = fetch_static(s, url)
        items = items_from_anchors(anchors or [], url, dom)
        method = "requests"
        policy_like = sum(score(i["text"]) >= 1 or i["doc"] for i in items.values())
        if pw and (anchors is None or (d == 0 and url in extra) or policy_like < MIN_LINKS_STATIC) and (url in extra or score(url) > 0 or d == 0):
            b_anchors, b_status, b_text = fetch_browser(pw, url)
            if b_anchors is not None:
                items.update(items_from_anchors(b_anchors, url, dom)); text, method, status = b_text, "browser", b_status
            elif anchors is None:
                status = b_status
        pages[url] = {"product": product_of(url, text, products.get(url)), "status": status, "method": method, "text_hash": hashlib.sha1(text.encode()).hexdigest() if text else None, "text_head": re.sub(r"\s+", " ", text)[:600],
                      "items": sorted(items.values(), key=lambda i: (i["year"] or "", i["text"]), reverse=True)}
        if d < depth_max:
            for i in items.values():
                if i["href"] in seen or i["doc"]:
                    continue
                if i.get("iframe") or (i["internal"] and score(i["text"] + unquote(i["href"])) > 0):
                    q.append((i["href"], d + 1))
    return pages


def diff(old: dict, new: dict):
    """-> [{kind, page, text, href}] ; kind: new_page / new_item / removed_item / text_changed / page_changed / fetch_failed"""
    ch = []
    for url, p in new.items():
        o = old.get(url)
        if p["status"] != 200:
            if o and o["status"] == 200:
                ch.append({"kind": "fetch_failed", "page": url, "text": str(p["status"]), "href": url})
            continue
        if o is None:
            ch.append({"kind": "new_page", "page": url, "text": f"{len(p['items'])} items", "href": url}); continue
        oi, ni = {i["href"]: i for i in o["items"]}, {i["href"]: i for i in p["items"]}
        for h, i in ni.items():
            if h not in oi:
                ch.append({"kind": "new_item", "page": url, "text": i["text"], "href": h})
            elif oi[h]["text"] != i["text"]:
                ch.append({"kind": "text_changed", "page": url, "text": f"{oi[h]['text']} -> {i['text']}", "href": h})
        for h, i in oi.items():
            if h not in ni:
                ch.append({"kind": "removed_item", "page": url, "text": i["text"], "href": h})
        if not ch or all(c["page"] != url for c in ch):
            if o["text_hash"] and p["text_hash"] and o["text_hash"] != p["text_hash"]:
                ch.append({"kind": "page_changed", "page": url, "text": "טקסט העמוד השתנה (אותם קישורים)", "href": url})
    return ch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    (OUT / "site_snapshot").mkdir(parents=True, exist_ok=True)
    cos, seeds = load_companies(), load_seeds()
    s, now = requests.Session(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    pw_cm = pw = None
    if not a.no_browser:
        try:
            from playwright.sync_api import sync_playwright
            pw_cm = sync_playwright(); pw = pw_cm.start()
        except Exception as e:
            print(f"[snapshot] playwright לא זמין: {e!r} - רק requests")
    changes, report = [], []
    for legal_id, c in sorted(cos.items()):
        seed = seeds.get(legal_id)
        if (a.only and legal_id not in a.only) or not seed:
            continue
        path = OUT / "site_snapshot" / f"{legal_id}.json"
        old = json.loads(path.read_text("utf-8")) if path.exists() else None
        pages = snapshot_company(s, pw, seed["home"], seed["extra"], seed.get("products"))
        ch = diff(old["pages"], pages) if old else []
        for x in ch:
            x.update(legal_id=legal_id, company=c["name"], detected=now)
        changes += ch
        path.write_text(json.dumps({"legal_id": legal_id, "company": c["name"], "taken": now, "pages": pages},
                                   ensure_ascii=False, indent=1), "utf-8")
        n_items = sum(len(p["items"]) for p in pages.values())
        report.append([legal_id, c["name"], len(pages), n_items, sum(i["doc"] for p in pages.values() for i in p["items"]),
                       "first" if old is None else len(ch), "; ".join(f"{p.get('product') or '?'}|{u}:{p['status']}" for u, p in pages.items() if p["status"] != 200)[:200]])
        print(f"[snapshot] {legal_id} {c['name']}: pages={len(pages)} items={n_items} changes={'first' if old is None else len(ch)}", flush=True)
    if pw_cm:
        pw_cm.stop()
    (OUT / "site_changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1), "utf-8")
    log = OUT / "site_changes_log.csv"
    new_file = not log.exists()
    with open(log, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, ["detected", "legal_id", "company", "kind", "page", "text", "href"], extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerows(changes)
    with open(OUT / "site_report.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["legal_id", "company", "pages", "items", "doc_items", "changes", "failed_pages"])
        w.writerows(report)
    print(f"[snapshot] changes this run: {len(changes)}")


if __name__ == "__main__":
    main()
