"""אבחון עמוד שלא החזיר מסמכים: רינדור בדפדפן ורישום כל בקשות הרשת (XHR/fetch/מסמכים) + קישורים + טקסט.

הרצה: python -m scripts.policy.probe_page URL [URL ...]   (רץ ב-Actions - policy_probe.yml; פלט ל-log)
"""
import os, re, sys

from playwright.sync_api import sync_playwright

from .crawl import UA


def probe(pw, url):
    print(f"\n######## {url}")
    b = pw.chromium.launch(headless=os.environ.get("POLICY_HEADED") != "1",
                           args=["--disable-blink-features=AutomationControlled", "--disable-http2"])
    try:
        pg = b.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1400, "height": 1000}).new_page()
        net = []

        def on_response(r):
            try:
                rt = r.request.resource_type
                if rt in ("image", "font", "stylesheet", "media") or re.search(r"google|facebook|doubleclick|hotjar|clarity|glassbox|analytics|gtm", r.url):
                    return
                ct = r.headers.get("content-type", "")
                head = ""
                if rt in ("xhr", "fetch") or "json" in ct:
                    try:
                        head = re.sub(r"\s+", " ", r.text())[:700]
                    except Exception:
                        pass
                net.append(f"  NET {r.status} {rt} {ct[:40]} {r.url[:300]}" + (f"\n      BODY {head}" if head else ""))
            except Exception:
                pass

        pg.on("response", on_response)
        try:
            resp = pg.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print("  networkidle failed:", str(e).splitlines()[0][:150])
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(6000)
        print("  STATUS", resp.status if resp else None, "FINAL", pg.url)
        pg.mouse.wheel(0, 4000); pg.wait_for_timeout(2500)
        print("\n".join(net[:250]))
        links = pg.eval_on_selector_all("a[href]", "els=>els.map(e=>(e.innerText||'').trim().slice(0,70)+' -> '+e.href)")
        print(f"  LINKS {len(links)}")
        for l in links:
            if re.search(r"מדיניות|הצהר|policy|xls|pdf|download|הורד|השקע|invest|file|media|upload", l, re.I):
                print("   ", l[:300])
        for f in pg.eval_on_selector_all("iframe", "els=>els.map(e=>e.src)"):
            print("  IFRAME", f)
        btns = pg.eval_on_selector_all("button,[role=tab],[role=button],select,[aria-expanded]",
                                       "els=>els.filter(e=>e.offsetParent).map(e=>e.tagName+':'+(e.innerText||e.value||'').trim().slice(0,50))")
        print("  CONTROLS", [x for x in btns if len(x) > 4][:120])
        body = re.sub(r"\s+", " ", pg.inner_text("body"))
        i = max(0, body.find("מדיניות"))
        print("  TEXT", body[i:i + 2500])
    except Exception as e:
        print("  ERROR", type(e).__name__, str(e)[:300])
    finally:
        b.close()
    # מה ה-crawler עצמו מוצא בעמוד (אחרי לחיצות/אקורדיונים/לכידות)
    from .snapshot import fetch_browser
    anchors, status, _ = fetch_browser(pw, url)
    docs = [a for a in (anchors or []) if re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", a["href"], re.I) or a.get("local")]
    print(f"  CRAWLER status={status} anchors={len(anchors or [])} docs={len(docs)}")
    for a in docs[:80]:
        print("   DOC", re.sub(r"\s+", " ", a["text"])[:80], "->", a["href"][:200])


if __name__ == "__main__":
    with sync_playwright() as pw:
        for u in sys.argv[1:]:
            probe(pw, u)
