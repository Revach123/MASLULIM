"""בדיקת היתכנות: האם אפשר למשוך את דוחות רשות שוק ההון מ-GitHub Actions.

שלושה מבחנים, מהזול ליקר:
  1. requests ישיר (בלי דפדפן) - האם ה-IP בכלל מורשה.
  2. Playwright headless - האם אתגר ה-JS של AWS WAF נפתר בדפדפן אמיתי.
  3. Playwright headful תחת xvfb - אם headless מזוהה כבוט.
בכל מבחן דפדפן: טוענים את publicreports, ואז מריצים בתוך הדף את אותה
בקשה בדיוק שהתוסף מריץ (same-origin), ומורידים קובץ אחד לבדיקה.
הפלט: טבלת סיכום ב-stdout + צילומי מסך/HTML בתיקיית probe_out לארטיפקט.
"""
import json
import sys
from datetime import date
from pathlib import Path

import requests

ORIGIN = "https://cmainfo.cma.gov.il"
PAGE = f"{ORIGIN}/publicreports"
API = f"{ORIGIN}/api/PublicReporting/GetPublicReports"
REPORT_TYPE = "71100184,71100185,71100190"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
OUT = Path("probe_out")
OUT.mkdir(exist_ok=True)


def recent_quarters(n=2):
    y, q = date.today().year, (date.today().month - 1) // 3 + 1
    res = []
    for _ in range(n):
        res.append((y, q))
        y, q = (y - 1, 4) if q == 1 else (y, q - 1)
    return res


def body(y, q):
    return {"corporation": None, "fromYear": y, "fromQuarter": q, "toYear": y, "toQuarter": q,
            "reportFromDate": None, "reportToDate": None, "investmentName": None,
            "reportType": REPORT_TYPE, "systemField": "", "statusReport": 1}


def waf_headers(h):
    keys = ("server", "content-type", "x-amzn-waf-action", "x-amzn-requestid", "x-cache", "via")
    return {k: h.get(k) for k in keys if h.get(k)}


def test_ip():
    try:
        info = requests.get("https://ipinfo.io/json", timeout=15).json()
        return f"{info.get('ip')} {info.get('country')} {info.get('org')}"
    except Exception as e:
        return f"unknown ({e})"


def test_requests():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9,en;q=0.8"})
    out = {}
    try:
        r = s.get(PAGE, timeout=30)
        out["page"] = {"status": r.status_code, "headers": waf_headers(r.headers), "len": len(r.content)}
        (OUT / "requests_page.html").write_bytes(r.content)
        y, q = recent_quarters(2)[1]
        r = s.post(API, json=body(y, q), timeout=30,
                   headers={"Accept": "application/json", "Referer": PAGE, "Origin": ORIGIN})
        ct = r.headers.get("content-type", "")
        n = len(r.json()) if "json" in ct else None
        out["api"] = {"status": r.status_code, "headers": waf_headers(r.headers), "items": n,
                      "head": r.text[:200] if n is None else ""}
    except Exception as e:
        out["error"] = repr(e)
    return out


FETCH_JS = """async ([y, q, rt]) => {
  const r = await fetch('/api/PublicReporting/GetPublicReports', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json', Accept: 'application/json'},
    body: JSON.stringify({corporation: null, fromYear: y, fromQuarter: q, toYear: y, toQuarter: q,
      reportFromDate: null, reportToDate: null, investmentName: null, reportType: rt,
      systemField: '', statusReport: 1})});
  const ct = r.headers.get('content-type') || '';
  if (!ct.includes('json')) return {status: r.status, nonJson: true, head: (await r.text()).slice(0, 200)};
  const d = await r.json();
  return {status: r.status, items: Array.isArray(d) ? d.length : null,
          first: Array.isArray(d) && d.length ? d[0] : null};
}"""

DOWNLOAD_JS = """async ([id, ext]) => {
  const r = await fetch(`/api/PublicReporting/downloadFiles?IdDoc=${id}&extention=${ext}`, {credentials: 'include'});
  const b = new Uint8Array(await r.arrayBuffer());
  return {status: r.status, bytes: b.length, magic: String.fromCharCode(b[0] || 0, b[1] || 0)};
}"""


def test_browser(headless, tag):
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="he-IL", timezone_id="Asia/Jerusalem")
        page = ctx.new_page()
        try:
            resp = page.goto(PAGE, wait_until="domcontentloaded", timeout=60000)
            out["page_status"] = resp.status if resp else None
            out["page_headers"] = waf_headers(resp.headers) if resp else {}
            page.wait_for_timeout(8000)  # זמן לאתגר ה-WAF ול-SPA
            out["waf_cookie"] = any(c["name"] == "aws-waf-token" for c in ctx.cookies())
            page.screenshot(path=str(OUT / f"{tag}.png"), full_page=True)
            (OUT / f"{tag}.html").write_text(page.content(), encoding="utf-8")
            results = {}
            first = None
            for y, q in recent_quarters(2):
                r = page.evaluate(FETCH_JS, [y, q, REPORT_TYPE])
                results[f"{y}Q{q}"] = {k: v for k, v in r.items() if k != "first"}
                first = first or r.get("first")
            out["api"] = results
            if first and first.get("DocumentId"):
                out["download"] = page.evaluate(DOWNLOAD_JS, [first["DocumentId"], first.get("fileExt") or "xlsx"])
                (OUT / f"{tag}_sample_item.json").write_text(json.dumps(first, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            out["error"] = repr(e)
        finally:
            browser.close()
    return out


DOC_URLS = [
    "https://www.gov.il/BlobFolder/dynamiccollectorresultitem/notice-2023-066/he/gate_5_part_4_chapter_3_V12.pdf",
]


def fetch_docs():
    """שולף PDF-ים גולמיים (בלי ניתוח בצד ה-runner - נקרא מקומית אחר כך) לתוך
    probe_out/docs/, כי gov.il חסום מה-sandbox המקומי אבל פתוח מ-Actions."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    dest = OUT / "docs"
    dest.mkdir(exist_ok=True)
    out = {}
    for url in DOC_URLS:
        name = url.rsplit("/", 1)[-1]
        try:
            r = s.get(url, timeout=30)
            r.raise_for_status()
            (dest / name).write_bytes(r.content)
            out[name] = {"status": r.status_code, "bytes": len(r.content)}
        except Exception as e:
            out[name] = {"error": repr(e)}
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    report = {"runner_ip": test_ip()}
    if mode in ("all", "requests"):
        report["0_docs"] = fetch_docs()
    if mode in ("all", "requests"):
        report["1_requests"] = test_requests()
    if mode in ("all", "headless"):
        report["2_headless"] = test_browser(True, "headless")
    if mode == "headful":
        report["3_headful"] = test_browser(False, "headful")
    txt = json.dumps(report, ensure_ascii=False, indent=2)
    print(txt)
    (OUT / f"report_{mode}.json").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
