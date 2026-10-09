"""אבחון קצר: אילו קריאות XHR/fetch לאותו אתר מחזירות קבצי דוחות (Reports/uploadfiles וכד'). הרצה: returns_probe.yml."""
import os, re, sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def probe(pw, url):
    host = urlparse(url).netloc
    print(f"\n######## {url}", flush=True)
    b = pw.chromium.launch(headless=os.environ.get("POLICY_HEADED") != "1", args=["--disable-http2"])
    pg = b.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1400, "height": 1000}).new_page()

    def on_resp(r):
        try:
            if urlparse(r.url).netloc != host or r.request.resource_type not in ("xhr", "fetch"):
                return
            body = r.text() if len(r.headers.get("content-length", "0")) < 8 else ""
            files = re.findall(r"[\w/\\.%-]*(?:uploadfiles|Reports)[\w/\\.%-]*\.(?:xlsx?|pdf)", body, re.I)
            print(f"  XHR {r.status} {r.request.method} {r.url[:200]} len={len(body)} files={len(files)} {files[:2]}", flush=True)
            if 0 < len(body) < 600:
                print("      BODY", re.sub(r"\s+", " ", body)[:300], flush=True)
        except Exception:
            pass

    pg.on("response", on_resp)
    try:
        pg.goto(url, wait_until="networkidle", timeout=60000)
    except Exception:
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(5000)
    print("  -- after load: text:", re.sub(r"\s+", " ", pg.inner_text("body"))[:500], flush=True)
    for step, sel in (("accordions", '[aria-expanded="false"]'), ("buttons", "button")):
        els = pg.query_selector_all(sel)
        print(f"  -- {step}: {len(els)}", flush=True)
        for el in els[:25]:
            try:
                t = (el.inner_text() or "").strip()[:40].replace("\n", " ")
                if not el.is_visible():
                    continue
                el.click(timeout=800); pg.wait_for_timeout(500)
                print(f"     clicked {t!r}", flush=True)
            except Exception:
                pass
    pg.wait_for_timeout(2000)
    print("  -- after clicks: text:", re.sub(r"\s+", " ", pg.inner_text("body"))[300:1500], flush=True)
    b.close()


if __name__ == "__main__":
    with sync_playwright() as pw:
        for u in sys.argv[1:]:
            probe(pw, u)
