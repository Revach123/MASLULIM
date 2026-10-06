"""תמונת מצב של מבנה עמודי המדיניות באתרי החברות + זיהוי עדכונים, בלי להוריד את המסמכים.

הרצה: python -m scripts.policy.snapshot [--only LEGAL_ID ...] [--no-browser]
לכל חברה: סורק את עמודי ה-seed (+extra_urls) ועמודים קשורים למדיניות (עומק 2), ושומר לכל עמוד את
רשימת הפריטים הרלוונטיים (טקסט קישור, href, שנה, האם מסמך) ואת האש טקסט העמוד.
עמוד שנראה דינמי (אקורדיון/לשוניות, מעט קישורים) מרונדר בדפדפן (playwright): פותח אקורדיונים
ולשוניות ואוסף שוב. השוואה מול הריצה הקודמת -> policy/site_changes.json + policy/site_changes_log.csv.

פלט: policy/site_snapshot/<LegalId>.json, site_changes.json, site_changes_log.csv, site_report.csv
"""
import argparse, csv, hashlib, json, os, re, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urldefrag, unquote

from bs4 import BeautifulSoup

from .crawl import DOC_EXT, UA, is_doc_url, base_domain, get, load_companies, load_seeds, score

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
    return (score(text) + score(unquote(href)) > 0 or is_doc_url(href)
            or bool(DL_HINT.search(low)) or bool(re.search(r"גמל|פנסי|השתלמות|gemel|pension|provident|hishtalmut", low)))


TECH_TEXT = re.compile(r"^\((html|xhr|network file|config docs|iframe)\)")


def better_text(old, new):
    """הטקסט שהמשתמש רואה באתר (קישור + השורה/הכרטיס סביבו) עדיף על תווית טכנית ("(html)" - נתיב שנמצא בקוד
    המקור): תווית טכנית לא דורסת טקסט אמיתי, וטקסט אמיתי מחליף תווית טכנית."""
    if not old or (TECH_TEXT.match(old) and not TECH_TEXT.match(new or "")):
        return new
    return old


def merge_items(base, extra):
    for h, it in extra.items():
        if h in base:
            it = {**it, "text": better_text(base[h]["text"], it["text"])}
            it["year"] = it["year"] or base[h].get("year")
        base[h] = it
    return base


def items_from_anchors(anchors, page_url, dom):
    out = {}
    for a in anchors:
        href = urldefrag(urljoin(page_url, a["href"]))[0]
        text = re.sub(r"\s+", " ", a["text"]).strip()
        is_iframe = text == "(iframe)"
        if a.get("local"):
            out[href] = {"text": text, "href": href, "year": year_of(text + " " + unquote(href)), "iframe": False,
                         "doc": True, "internal": True, "local": a["local"]}
            continue
        if not href.startswith("http") or not (is_iframe or keep_item(text, href)):
            continue
        if href in out:  # אותו קובץ גם כקישור גלוי וגם בקוד המקור - נשמר הטקסט הגלוי
            text = better_text(out[href]["text"], text)
        out[href] = {"text": text, "href": href, "year": year_of(text + " " + unquote(href)), "iframe": is_iframe,
                     "doc": is_doc_url(href) or bool(DL_HINT.search(text.lower())),
                     "internal": base_domain(href) == dom}
    return out


def fetch_static(s, url):
    r = get(s, url)
    if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return None, getattr(r, "status_code", "ERR"), ""
    soup = BeautifulSoup(r.content, "html.parser")  # bytes: הקידוד נקבע מה-meta/כותרות, לא ניחוש requests
    anchors = []
    base = soup.find("base", href=True)  # <base href="/"> (ילין): קישורים יחסיים נפתרים מולו, לא מול נתיב העמוד
    base_url = urljoin(url, base["href"]) if base else None
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if len(t) < 4 or re.match(r"(הורד|להורדה|הורדת|לצפייה|צפייה|download|pdf|xlsx?|קובץ)", t, re.I):
            row = a.find_parent(["tr", "li"]) or a.parent
            ctx = re.sub(r"\s+", " ", row.get_text(" ", strip=True))[:200] if row else ""
            if ctx and ctx != t:
                t = f"{ctx} {t}".strip()
        anchors.append({"href": urljoin(base_url, a["href"]) if base_url else a["href"], "text": t})
    return anchors, 200, soup.get_text(" ", strip=True)


# טקסט קישור; כשהוא כללי ("הורדת טופס", "להורדה", אייקון) - מוסיפים את טקסט השורה/הכרטיס (ילין: uploads/n/<מספר>.pdf)
A_JS = """els => els.map(e => {
    let t = (e.innerText || e.textContent || e.getAttribute('aria-label') || e.title || '').trim();
    if (t.length < 4 || /^(הורד|להורדה|הורדת|לצפייה|צפייה|download|pdf|xlsx?|קובץ)/i.test(t)) {
        const row = e.closest('tr,li,[class*=item],[class*=row],[class*=card],[class*=file],[class*=doc]') || e.parentElement;
        const ctx = row ? (row.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200) : '';
        if (ctx && ctx !== t) t = (ctx + ' ' + t).trim();
    }
    return {href: e.href, text: t};
})"""
FILE_RX = re.compile(r"""["'(=\s]((?:https?:)?[\w\-./%:?=&~א-ת]+?\.(?:xlsx|xls|pdf|docx))(?=["')\s&<,]|$)""", re.I)
# כתובת מלאה עם ( ) ' בשם הקובץ (מנורה "...-כספי-(שקלי)-41.xlsx", "תשפ''ז-31.12.26-.pdf") - FILE_RX נחתך בהם
FILE_URL_RX = re.compile(r"""(https?://[\w.\-]+/[^"<>\s\\]*?\.(?:xlsx|xls|pdf|docx))(?![\w])""", re.I)


def json_file_labels(body):
    """{שם קובץ: הטקסט שהאתר מציג לו} מתוך תגובת JSON: לכל אובייקט שמחזיק נתיב קובץ - שאר שדות הטקסט הקצרים
    באותו אובייקט (title/name/description/date), בלי כתובות ומזהים. רשימות קבצים שנטענות ב-XHR (הראל) כך מקבלות
    את הכותרת הגלויה במקום התווית הטכנית "(xhr)"."""
    try:
        data = json.loads(body)
    except Exception:
        return {}
    out = {}

    def walk(o):
        if isinstance(o, dict):
            strs = [v for v in o.values() if isinstance(v, str)]
            files = [v for v in strs if re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", v, re.I)]
            if files:
                lab = [v.strip() for v in strs if v not in files and 2 < len(v.strip()) <= 200
                       and not re.match(r"^(https?:|/|[\w-]{20,}$|\{)", v.strip()) and re.search(r"[א-ת]|\d{4}", v)]
                if lab:
                    for f in files:
                        out.setdefault(unquote(f).split("?")[0].rsplit("/", 1)[-1], " ".join(dict.fromkeys(lab))[:200])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def file_tail(u, parts=2):
    """תיקייה/שם-קובץ מהכתובת (מפוענח, בלי query) - לזיהוי קובץ בעמוד כששמות זהים בתיקיות שונות."""
    return "/".join(unquote(u).split("?")[0].rstrip("/").split("/")[-parts:])


def html_json_labels(html):
    """{שם קובץ: כותרת} לקבצים שנמצאים בנתוני JSON שמוטמעים בעמוד (Next.js __NEXT_DATA__ / self.__next_f, מנורה):
    האובייקט {...} הקרוב שמחזיק את הנתיב, ושדות הטקסט הקצרים שבו - כמו json_file_labels, בלי לפענח את כל העמוד
    (ה-payload של __next_f הוא מחרוזות JS ולא JSON תקין)."""
    h = html.replace('\\\\"', '"').replace('\\"', '"').replace("\\/", "/")
    h = re.sub(r"\\u0026", "&", h.replace("&amp;", "&").replace("&quot;", '"'), flags=re.I)
    out = {}

    def enclosing(a, b):
        """גבולות האובייקט {...} שמכיל את h[a:b], או None."""
        depth, i = 0, a
        while i > max(0, a - 4000):
            i -= 1
            if h[i] == "}":
                depth += 1
            elif h[i] == "{":
                if depth == 0:
                    break
                depth -= 1
        else:
            return None
        depth, j = 0, b
        while j < min(len(h), b + 4000):
            if h[j] == "{":
                depth += 1
            elif h[j] == "}":
                if depth == 0:
                    return i, j + 1
                depth -= 1
            j += 1
        return None

    for m in re.finditer(r"""[^"'\s<>]+?\.(?:xlsx|xls|pdf|docx)(?![\w])""", h, re.I):
        name = file_tail(m.group(0))
        if name in out:
            continue
        span = (m.start(), m.end())
        for _ in range(3):  # הנתיב בתת-אובייקט ({"file": {"url": ...}, "title": ...}) - עולים עד שתי רמות
            span = enclosing(*span)
            if not span:
                break
            obj = h[span[0] + 1:span[1] - 1]
            while re.search(r"\{[^{}]*\}", obj):
                obj = re.sub(r"\{[^{}]*\}", "", obj)
            vals = re.findall(r'"[\w$-]+"\s*:\s*"([^"\n]{3,200})"', obj)
            lab = [v.strip() for v in vals if not re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", v, re.I)
                   and not re.match(r"^(https?:|/|\$|[\w-]{20,}$)", v.strip()) and re.search(r"[א-ת]|\d{4}", v)]
            if lab:
                out[name] = " ".join(dict.fromkeys(lab))[:200]
                out.setdefault(file_tail(m.group(0), 1), out[name])
                break
    return out


def html_files(html):
    """נתיבי קבצים ב-HTML/סקריפטים, בלי כפילויות (עמוד מנורה מחזיק >300 התאמות כפולות)."""
    html = re.sub(r"\\u0026", "&", html.replace("&amp;", "&").replace("\\/", "/"), flags=re.I)
    out = []
    for m in FILE_URL_RX.findall(html) + FILE_RX.findall(html):
        if m not in out and not any(o.endswith(m) for o in out):
            out.append(m)
    return out[:800]


def signed_url_name(u):
    """שם הקובץ המקורי מתוך כתובת הורדה חתומה (מגדל/Wix: download-files.wixmp.com/...?token=<JWT>, ב-dis.filename:
    "Hatzarat Migdal Bituach JUL 2026_P - ACC.xlsx") - בכתובת עצמה רק מזהה."""
    m = re.search(r"[?&]token=([\w-]+)\.([\w-]+)\.", u)
    if not m:
        return None
    try:
        import base64
        pl = json.loads(base64.urlsafe_b64decode(m.group(2) + "=" * (-len(m.group(2)) % 4)))
        return (pl.get("dis") or {}).get("filename")
    except Exception:
        return None


def fetch_browser(pw, url, click_texts=None):
    """רינדור: רשת שקטה, פתיחת אקורדיונים/לשוניות, ולכידת בקשות רשת (JSON עם נתיבי קבצים, קבצים ישירים, iframes).
    -> (anchors, status, body_text)"""
    b = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None, headless=os.environ.get("POLICY_HEADED") != "1",
                           args=["--disable-blink-features=AutomationControlled", "--disable-http2",
                         *(["--window-position=-32000,-32000"] if os.environ.get("POLICY_OFFSCREEN") == "1" else [])])
    try:
        ctx = b.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1400, "height": 1000})
        pg = ctx.new_page()
        net = []
        clicked_row = {"text": None, "at": 0.0}  # שורת כפתור ההורדה שנלחץ עכשיו - הכיתוב של הקובץ שיגיע ברשת

        def on_response(r):
            try:
                ct = r.headers.get("content-type", "")
                u = r.url
                if re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", u, re.I) or re.search(r"spreadsheet|pdf|msword|excel", ct):
                    row = clicked_row["text"] if time.monotonic() - clicked_row["at"] < 15 else None
                    net.append({"href": u, "text": row or signed_url_name(u) or "(network file)"})
                elif "json" in ct or "x-component" in ct or "javascript" not in ct and "text/html" not in ct and "xml" in ct:  # x-component: Next.js RSC
                    body = r.text()
                    labels = json_file_labels(body) if len(body) < 3_000_000 else {}
                    if len(body) < 3_000_000:
                        for m in FILE_RX.findall(body):
                            h = urljoin(u, m.replace("\\/", "/"))
                            w = re.match(r"wix:document://v1/(?:ugd/)?([0-9a-f]+_[0-9a-f]+\.(?:xlsx|xls|pdf|docx))/?(.*)", h)
                            if w:  # Wix (מגדל): כל הקבצים ברשימת ה-XHR - כתובת ציבורית ישירה, בלי לחיצה על כפתור הורדה
                                host = re.match(r"https?://[^/]+", url).group(0)
                                net.append({"href": f"{host}/_files/ugd/{w.group(1)}", "text": unquote(w.group(2)).strip() or "(xhr)"})  # שם הקובץ שמוצג (מגדל: "Hatzarat ... Mar 2026")
                            else:
                                # הכותרת שהאתר מציג לקובץ - שדות הטקסט באותו אובייקט JSON (הראל: title/name ליד נתיב הקובץ)
                                net.append({"href": h, "text": labels.get(unquote(m.replace("\\/", "/")).rsplit("/", 1)[-1]) or "(xhr)"})
            except Exception:
                pass

        pg.on("response", on_response)
        try:
            resp = pg.goto(url, wait_until="networkidle", timeout=60000)
        except Exception:  # אתרים עם חיבורים פתוחים/בדיקת בוט: טעינה קלה יותר
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(5000)
        status = resp.status if resp else 200
        seen, anchors = set(), []

        def collect():
            for a in pg.eval_on_selector_all("a[href]", A_JS):
                if (a["href"], a["text"].strip()) not in seen:
                    seen.add((a["href"], a["text"].strip())); anchors.append(a)
            for f in pg.eval_on_selector_all("iframe[src]", "els=>els.map(e=>e.src)"):
                if (f, "iframe") not in seen:
                    seen.add((f, "iframe")); anchors.append({"href": f, "text": "(iframe)"})

        pg.wait_for_timeout(2500)  # SPA/בדיקת בוט: תוכן שנטען אחרי networkidle
        collect()

        def expand():
            for sel in ('[aria-expanded="false"]:not(a)', "details:not([open]) > summary",
                        "button:has-text('הצג עוד')", "button:has-text('עוד')", "[class*=accordion] [class*=header]"):
                for el in pg.query_selector_all(sel)[:80]:
                    try:
                        if not el.is_visible():  # תפריטים מוסתרים: כל לחיצה הייתה מחכה 600ms לשווא (הכשרה: מאות)
                            continue
                        el.click(timeout=600); pg.wait_for_timeout(120)
                    except Exception:
                        pass
            collect()

        # לחיצות מפורשות מהגדרות האתר (click_texts): טקסט מדויק, force (באנר עוגיות מכסה), המתנה לתוכן מ-API
        # (הכשרה: הצ'יפ 'מדיניות השקעה משתתפות' - בלעדיו מוצגות רק ההצבעות)
        for t in click_texts or []:
            try:
                for ok_t in ("הבנתי", "אישור", "מאשר", "Accept"):  # באנר עוגיות שמכסה את הדף
                    try:
                        pg.get_by_role("button", name=ok_t, exact=True).first.click(timeout=1500)
                    except Exception:
                        pass
                loc = pg.get_by_text(t, exact=True)
                n0 = len(anchors)
                vis = []
                for attempt in range(3):  # React: לחיצה לפני hydration לא עושה כלום - ממתינים לקישור קובץ, אחרת לוחצים שוב
                    pg.wait_for_timeout(3000)
                    vis = [i for i in range(min(loc.count(), 10)) if loc.nth(i).is_visible()]
                    el = loc.nth(vis[0]) if vis else loc.first
                    try:
                        el.scroll_into_view_if_needed(timeout=3000); el.click(timeout=5000)
                    except Exception:
                        el.click(timeout=5000, force=True)
                    try:
                        pg.wait_for_selector("a[href*='.xls'], a[href*='.pdf'], a[href*='.XLS']", timeout=15000)
                    except Exception:
                        pass
                    collect()
                    if any(re.search(r"\.(xlsx?|pdf)(\?|$)", a["href"], re.I) for a in anchors[n0:]):
                        break
                files = [a["href"] for a in anchors[n0:] if re.search(r"\.(xlsx?|pdf)(\?|$)", a["href"], re.I)]
                print(f"[snapshot] click_texts {t!r}: matches={loc.count()} visible={vis} new_anchors={len(anchors) - n0} files={len(files)} {files[:3]}", flush=True)
                for _ in range(10):  # "טען עוד" / "הצג עוד" ברשימת הכרטיסים
                    more = pg.get_by_text(re.compile(r"^(טען|הצג)\s+(עוד|נוספים)"))
                    if not more.count():
                        break
                    more.first.click(timeout=3000, force=True); pg.wait_for_timeout(2000); collect()
            except Exception as e:
                print(f"[snapshot] click_texts {t!r}: {type(e).__name__}", flush=True)
        expand()
        t_int = time.monotonic() + float(os.environ.get("POLICY_PAGE_BUDGET", "120"))
        # לשוניות/כפתורי מוצר (הראל: גמל/השתלמות/פנסיה...): לוחצים על כל אחד, פותחים אקורדיונים, אוספים
        tabs = pg.query_selector_all('[role="tab"], button, [role="button"], li[tabindex], [class*=tab]:not(a)')
        # לשוניות/צ'יפים של מדיניות קודם (הכשרה: צ'יפ "מדיניות השקעה משתתפות" אחרי ~150 כפתורי תפריט)
        try:
            ttxt = pg.eval_on_selector_all('[role="tab"], button, [role="button"], li[tabindex], [class*=tab]:not(a)',
                                           "els => els.map(e => (e.innerText || '').trim().slice(0, 60))")
            if len(ttxt) == len(tabs):
                # אחריהן צ'יפים של מוצר (הראל: "הראל השתלמות", "קרן החיסכון לצבא הקבע" - אחרי עשרות כפתורי תפריט,
                # ותקציב הזמן נגמר לפני שהגענו אליהם: הקבצים נמצאו בקוד העמוד אבל בלי הכותרת שמוצגת בלשונית)
                prio = lambda t: 0 if re.search(r"מדיניות|הצהר", t) else 1 if re.search(r"גמל|פנסי|השתלמ|קרן|קופ|ביטוח|חיסכון", t) and len(t) <= 35 else 2
                tabs = [el for _, el in sorted(zip(ttxt, tabs), key=lambda p: prio(p[0]))]
        except Exception:
            pass
        clicked = set()
        for el in tabs[:150]:
            if time.monotonic() > t_int:  # תקציב זמן לעמוד (כלל: 3 רשימות x עשרות אפשרויות = 13+ דקות)
                break
            try:
                t = (el.inner_text() or "").strip()
                if not (2 <= len(t) <= 40) or t in clicked or not el.is_visible():
                    continue
                if re.search(r"חיפוש|אזור אישי|כניסה|צ'?אט|WhatsApp|סגור|✕|תפריט|נגישות|שפה|English|עוגיות|הבנתי|דלג", t):
                    continue
                clicked.add(t)
                el.click(timeout=800)
                # לשונית/צ'יפ של מדיניות: התוכן נטען אחרי הלחיצה (הכשרה: כרטיסים מ-API) - מחכים ואוספים לפני שהלשונית הבאה מחליפה אותו
                if re.search(r"מדיניות|הצהר", t):
                    pg.wait_for_timeout(2500); collect(); pg.wait_for_timeout(1500)
                else:
                    pg.wait_for_timeout(400)
                if pg.url.split("#")[0] != url.split("#")[0]:  # כפתור שניווט החוצה - חוזרים
                    collect(); pg.go_back(wait_until="networkidle", timeout=30000)
                    continue
                expand()
            except Exception:
                pass
        # רשימות נפתחות ("מה תרצו למצוא?", בחירת שנה/מוצר): כל אפשרות -> בחירה, פתיחה, איסוף
        for sel_el in pg.query_selector_all("select")[:6]:
            if time.monotonic() > t_int:  # תקציב זמן לעמוד (כלל: 3 רשימות x עשרות אפשרויות = 13+ דקות)
                break
            try:
                opts = sel_el.eval_on_selector_all("option", "os => os.map(o => o.value)")
            except Exception:
                continue
            for v in opts[:40]:
                if time.monotonic() > t_int:  # תקציב זמן לעמוד (כלל: 3 רשימות x עשרות אפשרויות = 13+ דקות)
                    break
                try:
                    sel_el.select_option(v); pg.wait_for_timeout(700)
                    if pg.url.split("#")[0] != url.split("#")[0]:
                        collect(); pg.go_back(wait_until="networkidle", timeout=30000); continue
                    expand()
                except Exception:
                    pass
        for el in pg.query_selector_all('[role="option"], [role="menuitem"], [class*=dropdown] li, [class*=select] li')[:60]:
            if time.monotonic() > t_int:  # תקציב זמן לעמוד (כלל: 3 רשימות x עשרות אפשרויות = 13+ דקות)
                break
            try:
                t = (el.inner_text() or "").strip()
                if 2 <= len(t) <= 60 and el.is_visible():
                    el.click(timeout=800); pg.wait_for_timeout(500)
                    if pg.url.split("#")[0] != url.split("#")[0]:
                        collect(); pg.go_back(wait_until="networkidle", timeout=30000); continue
                    expand()
            except Exception:
                pass
        # מסננים/לשוניות שהם DIV/SPAN עם cursor:pointer (הכשרה: "מדיניות השקעה משתתפות"; מנורה: שנים 2026..2017)
        pointer_js = """els => els.filter(e => {
            const t = (e.innerText || '').trim();
            if (t.length < 2 || t.length > 45 || e.closest('a[href]')) return false;
            if (!(e.offsetWidth || e.offsetHeight)) return false;
            if ([...e.children].some(c => (c.innerText || '').trim() === t)) return false;  // הפנימי ביותר
            return getComputedStyle(e).cursor === 'pointer' || e.hasAttribute('onclick') || e.getAttribute('tabindex') === '0';
        }).map(e => (e.innerText || '').trim())"""
        try:
            ptexts = pg.eval_on_selector_all("div, span, li, p, h3, h4, label", pointer_js)
        except Exception:
            ptexts = []
        want = [t for t in dict.fromkeys(ptexts)
                if t not in clicked and re.search(r"מדיניות|הצהר|השקע|policy|^(שנת\s*)?20[12]\d$", t) and not re.search(r"פרטיות|תגמול|נגישות|הצבע", t)]
        for t in want[:25]:
            if time.monotonic() > t_int:  # תקציב זמן לעמוד (כלל: 3 רשימות x עשרות אפשרויות = 13+ דקות)
                break
            try:
                pg.get_by_text(t, exact=True).first.click(timeout=1500); pg.wait_for_timeout(1200)
                if pg.url.split("#")[0] != url.split("#")[0]:
                    collect(); pg.go_back(wait_until="networkidle", timeout=30000); continue
                expand()
                for a in pg.eval_on_selector_all("a[href]", "els=>els.map(e=>({href:e.href,text:e.innerText||e.textContent||''}))"):
                    if (a["href"], a["text"].strip()) not in seen and re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", a["href"], re.I):
                        seen.add((a["href"], a["text"].strip())); anchors.append({"href": a["href"], "text": f"{t} {a['text']}".strip()})
            except Exception:
                pass
        pg.wait_for_timeout(1000)
        collect()
        # כפתורי "הורדה" שלא מצביעים לקובץ (postback של ASP.NET / JS): לוחצים ולוכדים את ההורדה עצמה
        t_dl = time.monotonic() + float(os.environ.get("POLICY_DL_BUDGET", "180"))
        dl_dir = Path(os.environ.get("RUNNER_TEMP") or "/tmp") / "policy_dl"
        dl_dir.mkdir(parents=True, exist_ok=True)
        els = pg.query_selector_all("a, button, [role=button], input[type=submit], input[type=button]")
        def _label(el):
            return " ".join(x for x in ((el.inner_text() or "").strip(), el.get_attribute("value") or "",
                                        el.get_attribute("aria-label") or "", el.get_attribute("title") or "") if x)
        cands = []
        for el in els[:1500]:
            try:
                t, href = _label(el), el.get_attribute("href") or ""
                # מנורה: <a> בלי href, רק אייקון; התיאור ב-aria-label ("... - קובץ EXCEL להורדה")
                if re.search(r"הורד|להורדה|download|אקסל|excel|xls", t + " " + href, re.I) \
                        and not re.search(r"\.(xlsx|xls|pdf|docx)(\?|$)", href, re.I):
                    cands.append((el, t))
            except Exception:
                pass
        for el, t in cands[:80]:
            if time.monotonic() > t_dl:  # תקציב זמן לעמוד (כלל: 3 רשימות x עשרות אפשרויות = 13+ דקות)
                break
            try:
                ctx_text = el.evaluate("e => (e.closest('tr,li,.row,[class*=item],[class*=card]') || e.parentElement || e).innerText || ''")
                ctx_text = re.sub(r"\s+", " ", f"{ctx_text} {t}").strip()[:300]
                n_pages = len(ctx.pages)
                if not el.is_visible():  # מנורה: האייקון בתוך אקורדיון מסלול סגור - פותחים את כל האבות הסגורים
                    el.evaluate("""e => { for (let p = e.parentElement; p; p = p.parentElement) {
                        const s = p.querySelector(':scope > [aria-expanded="false"]'); if (s) s.click(); } }""")
                    pg.wait_for_timeout(700)
                    if not el.is_visible():
                        continue
                clicked_row.update(text=ctx_text, at=time.monotonic())
                try:
                    with pg.expect_download(timeout=8000) as info:
                        el.scroll_into_view_if_needed(timeout=2000); el.click(timeout=3000)
                    dl = info.value
                    local = dl_dir / f"{abs(hash((url, dl.suggested_filename, ctx_text))) % 10**10}_{dl.suggested_filename}"
                    dl.save_as(str(local))
                    anchors.append({"href": f"{url}#download={dl.suggested_filename}",
                                    "text": f"{ctx_text} {dl.suggested_filename}"[:300], "local": str(local)})
                except Exception:
                    for np_ in ctx.pages[n_pages:]:  # הקובץ נפתח בלשונית חדשה (HTML/PDF) במקום הורדה
                        try:
                            np_.wait_for_load_state("domcontentloaded", timeout=10000)
                        except Exception:
                            pass
                        if np_.url and np_.url != "about:blank":
                            anchors.append({"href": np_.url, "text": ctx_text})
                        np_.close()
                if pg.url.split("#")[0] != url.split("#")[0]:
                    pg.goto(url, wait_until="networkidle", timeout=60000)
            except Exception:
                pass
        anchors += [x for x in net if (x["href"], x["text"]) not in seen]
        try:  # נתיבי קבצים בתוך ה-HTML/סקריפטים (Next.js __NEXT_DATA__ ודומיו)
            html = pg.content()
            found = html_files(html)
            jlabels = html_json_labels(html) if found and len(html) < 5_000_000 else {}
            # הטקסט סביב הקובץ בעמוד (שורה/כרטיס של האלמנט שמחזיק את הנתיב באחת מתכונותיו) - מה שהמשתמש רואה
            # תיקייה + שם (מנורה: אותו שם קובץ בתיקיות 20240124/ ו-20241201/ - "עד" ו"החל מ" - כל אחד והשורה שלו)
            names = [file_tail(m) for m in found]
            ctxs = pg.evaluate("""names => names.map(n => {
                const els = document.querySelectorAll('a,[href],[src],[data-href],[data-url],[data-file],[data-src],[onclick]');
                for (const e of els) {
                    let hit = false;
                    for (const a of e.attributes) { let v = a.value; try { v = decodeURIComponent(v); } catch (x) {} if (v.includes(n)) { hit = true; break; } }
                    if (!hit) continue;
                    const row = e.closest('tr,li,[class*=item],[class*=row],[class*=card],[class*=file],[class*=doc]') || e.parentElement;
                    const t = ((row || e).innerText || '').replace(/\\s+/g, ' ').trim();
                    if (t) return t.slice(0, 200);
                }
                return '';
            })""", names) if found else []
            for m, c in zip(found, ctxs):
                # & בשם הקובץ (מנורה "...-s&p500-14316.xlsx"): ב-HTML &amp;, ב-JSON של Next.js \u0026
                anchors.append({"href": urljoin(url, m), "text": c or jlabels.get(file_tail(m)) or jlabels.get(file_tail(m, 1)) or "(html)"})
        except Exception:
            pass
        text = pg.inner_text("body")
        return anchors, (200 if status < 400 else status), text
    except Exception as e:
        return None, f"browser:{type(e).__name__}:{str(e).splitlines()[0][:120]}", ""
    finally:
        b.close()


def product_of(url: str, text: str, hint: str | None):
    """גמל / פנסיה / ביטוח: לפי תווית ב-seed, ואחרת לפי כתובת/טקסט העמוד."""
    if hint:
        return hint
    t = unquote(url) + " " + text[:300]
    hits = [p for p, pat in (("פנסיה", r"פנסי|pension"), ("גמל", r"גמל|gemel|השתלמות"), ("ביטוח", r"ביטוח|insurance")) if re.search(pat, t, re.I)]
    return "+".join(hits) or None


SKIP_PATH = re.compile(r"/(magazine|articles?|blog|news|search|tag|press|careers?|jobs|privacy|cookies?)(/|$)|[?&]tag=", re.I)
PRODUCT_RX = re.compile(r"גמל|פנסי|השתלמות|gemel|pension|provident|kupot|השקע|invest", re.I)


def _prio(text: str, href: str) -> int:
    """עדיפות בתור הסריקה (נמוך = קודם): מדיניות > מוצר > שאר."""
    from .crawl import POLICY
    blob = text + " " + unquote(href)
    if text == "(iframe)":
        return 0
    return 0 if POLICY.search(blob) else 1 if PRODUCT_RX.search(blob) else 2


def snapshot_company(s, pw, home, extra, products=None, max_pages=15, depth_max=2, follow=None, click_texts=None):
    """follow: regex לקישורים שתמיד נכנסים אליהם ותמיד ברינדור דפדפן (מנורה: עמוד לכל מסלול, הקובץ נחשף רק ברינדור)"""
    import heapq, itertools
    frx = re.compile(follow) if follow else None
    products = products or {}
    dom = base_domain(home)
    pages, seen, iframes = {}, set(), set()
    tick = itertools.count()
    q = [(0, next(tick), u, 0) for u in extra] + [(1, next(tick), home, 0)]
    heapq.heapify(q)
    # תקציב כולל לסריקה: ג'וב חברה מוגבל ל-40 דק' ובוטל = לא נשמר כלום. בתום התקציב עוצרים ועוברים להורדה/פרסור/commit
    # עם מה שנאסף (עמודי ה-seed בעדיפות 0 - נסרקים ראשונים)
    deadline = time.monotonic() + float(os.environ.get("POLICY_CRAWL_BUDGET", "1320"))
    while q and len(pages) < max_pages:
        if time.monotonic() > deadline:
            print(f"[snapshot] crawl budget reached after {len(pages)} pages - stopping", flush=True)
            break
        _, _, url, d = heapq.heappop(q)
        url = urldefrag(url)[0]
        if url in seen:
            continue
        seen.add(url)
        anchors, status, text = fetch_static(s, url)
        items = items_from_anchors(anchors or [], url, dom)
        method = "requests"
        policy_like = sum(score(i["text"]) >= 1 or i["doc"] for i in items.values())
        forced = bool(frx and frx.search(unquote(url)))
        if pw and (forced or ((anchors is None or url in iframes or (d == 0 and url in extra) or policy_like < MIN_LINKS_STATIC) and (
                url in extra or url in iframes or score(url) > 0 or d == 0))):
            b_anchors, b_status, b_text = fetch_browser(pw, url, click_texts if url in extra else None)
            if b_anchors is not None:
                merge_items(items, items_from_anchors(b_anchors, url, dom)); text, method, status = b_text, "browser", b_status
            elif anchors is None:
                status = b_status
        pages[url] = {"product": product_of(url, text, products.get(url)), "status": status, "method": method, "text_hash": hashlib.sha1(text.encode()).hexdigest() if text else None, "text_head": re.sub(r"\s+", " ", text)[:600],
                      "items": sorted(items.values(), key=lambda i: (i["year"] or "", i["text"]), reverse=True)}
        if d < depth_max:
            for i in items.values():
                if i["href"] in seen or i["doc"]:
                    continue
                if SKIP_PATH.search(unquote(i["href"])):
                    continue
                if i.get("iframe"):
                    iframes.add(i["href"])
                if frx and frx.search(unquote(i["href"])):
                    heapq.heappush(q, (0, next(tick), i["href"], d + 1))
                elif i.get("iframe") or (i["internal"] and (score(i["text"] + unquote(i["href"])) > 0
                                                            or PRODUCT_RX.search(i["text"] + unquote(i["href"])))):
                    heapq.heappush(q, (_prio(i["text"], i["href"]), next(tick), i["href"], d + 1))
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
        pw.stop()
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
