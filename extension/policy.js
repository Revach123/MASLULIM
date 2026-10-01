// משיכת מסמכי "מדיניות השקעה מוצהרת" מאתרים שחוסמים שרתי ענן (403 ל-GitHub Actions),
// מהדפדפן שלך על החיבור הביתי - אותו רעיון כמו משיכת הדוחות מרשות שוק ההון.
//
// זרימה: רשימת האתרים נקראת מהרפו (policy/extension_sites.json, נבנה ע"י combine.py מ-
// scripts/policy/sites/*.json עם "via": "extension") -> לכל עמוד: טאב רקע, פתיחת אקורדיונים,
// איסוף קישורים לקבצים -> הורדה מתוך הדף (אותו origin + עוגיות) -> דילוג על מה שכבר נשלח (sha256)
// -> commit אחד ל-policy/inbox/<LegalId>/ . ב-GitHub, workflow policy_inbox מכניס לתיקיית החברה ומפרסר.
import { commitFiles, getFileBase64 } from "./github.js";

export const POLICY_ALARM = "policy-daily";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const DOC_RX = /\.(xlsx|xls|pdf|docx)(\?|#|$)/i;
const POLICY_RX = /מדיניות|הצהר|policy|mediniut|hatzarat|expected|investment/i;
const NOISE_RX = /esg|אחראי|תגמול(?!ים)|tagmul(?!im)|פרטיות|privacy|תקנון|מבצע|גילוי[-_ ]נאות|מצגת|presentation|נוהל|העברת זכויות|הצבעות|דוח[ -]כספי|רבעון/i;

// Chrome דוחה זמנית עריכת טאבים ("Tabs cannot be edited right now (user may be dragging a tab)") - מנסים שוב.
async function tabsRetry(fn, tries = 20) {
  for (let i = 1; ; i++) {
    try { return await fn(); } catch (e) {
      const msg = String(e && e.message || e);
      if (i >= tries || !/cannot be edited|dragging|Tabs cannot/i.test(msg)) throw e;
      await sleep(500 + 250 * i);
    }
  }
}

async function waitComplete(tabId, timeoutMs = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const t = await chrome.tabs.get(tabId);
    if (t.status === "complete") return;
    await sleep(500);
  }
}

// רץ בתוך הדף: פותח אקורדיונים/לשוניות, ומחזיר את כל הקישורים (כולל בתוך iframes מאותו origin).
async function pageCollectLinks(clicks) {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const clickAll = (sel) => document.querySelectorAll(sel).forEach((el) => { try { el.click(); } catch (e) {} });
  // רצף לחיצות לפי טקסט (מההגדרות של האתר), למשל איילון: "נושא" -> "הצהרת מדיניות השקעות"
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  for (const label of clicks || []) {
    const cands = [...document.querySelectorAll("button, a, li, span, div, label, [role=option], [role=combobox], [role=button]")]
      .filter((el) => visible(el) && (el.innerText || "").trim() === label);
    const el = cands.sort((a, b) => a.querySelectorAll("*").length - b.querySelectorAll("*").length)[0];
    if (el) { try { el.click(); } catch (e) {} await wait(1200); }
  }
  clickAll('[aria-expanded="false"]:not(a)');
  clickAll("details:not([open]) > summary");
  // כותרות אקורדיון לפי שנה ("שנת 2026")
  // ("שנת 2026", "הצהרה מראש של גוף מוסדי לשנת 2026") - רק אלמנטים קצרים, לא מיכלים שלמים
  [...document.querySelectorAll("button, h2, h3, h4, div, span, a")].filter((el) => {
    const t = (el.innerText || "").trim();
    return t.length < 120 && /(^|\s|ל)שנת\s+20\d\d$/.test(t) && visible(el) && !el.querySelector("a[href$='.xlsx'], a[href$='.pdf']");
  })
    .forEach((el) => { try { el.click(); } catch (e) {} });
  await wait(1500);
  const out = [];
  const grab = (doc, base) => {
    doc.querySelectorAll("a[href]").forEach((a) => {
      const row = a.closest("tr,li,.row,[class*=item],[class*=card]");
      out.push({ href: new URL(a.getAttribute("href"), base).href, text: (a.innerText || a.textContent || "").trim(),
                 ctx: row ? (row.innerText || "").trim().slice(0, 300) : "" });
    });
    doc.querySelectorAll("iframe").forEach((f) => { try { if (f.contentDocument) grab(f.contentDocument, f.src); } catch (e) {} });
  };
  return new Promise((resolve) => setTimeout(() => { grab(document, location.href); resolve(out); }, 2500));
}

// רץ בתוך הדף: לוחץ על כפתורים/קישורים של הורדה שלא מצביעים ישירות לקובץ (JS / postback).
// ההורדות עצמן נתפסות ברקע ע"י chrome.downloads.onCreated (ר' captureDownloads).
function pageClickDownloads() {
  const rx = /הורד|להורדה|download|אקסל|excel|xls/i;
  const els = [...document.querySelectorAll("a, button, [role=button], input[type=button], input[type=submit]")];
  let n = 0;
  for (const el of els) {
    const t = (el.innerText || el.value || el.getAttribute("aria-label") || el.title || "") + " " + (el.getAttribute("href") || "");
    const href = el.getAttribute("href") || "";
    if (!rx.test(t) || /\.(xlsx|xls|pdf)(\?|$)/i.test(href)) continue;
    try { el.click(); n++; } catch (e) {}
    if (n >= 40) break;
  }
  return n;
}

// רץ בתוך הדף: מוריד קובץ (same-origin/עוגיות) ומחזיר base64.
function pageFetchBase64(url) {
  return fetch(url, { credentials: "include" }).then(async (r) => {
    if (!r.ok) return { __error: true, status: r.status };
    const bytes = new Uint8Array(await r.arrayBuffer());
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return { base64: btoa(bin), type: r.headers.get("content-type") || "" };
  }).catch((e) => ({ __error: true, message: String(e) }));
}

// תופס הורדות שהדף מפעיל (לחיצה על כפתור) ומבטל אותן - מחזיר את כתובות הקבצים. מוריד אותם אח"כ בעצמנו.
async function captureDownloads(tabId, ms = 8000) {
  const urls = [];
  const onCreated = (item) => {
    urls.push({ href: item.finalUrl || item.url, text: item.filename || "" });
    chrome.downloads.cancel(item.id).catch(() => {});
    chrome.downloads.erase({ id: item.id }).catch(() => {});
  };
  chrome.downloads.onCreated.addListener(onCreated);
  let clicked = 0;
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId }, func: pageClickDownloads });
    clicked = (r && r.result) || 0;
    if (clicked) await sleep(ms);
  } finally {
    chrome.downloads.onCreated.removeListener(onCreated);
  }
  return { clicked, urls };
}

// chrome.downloads.onCreated גלובלי לדפדפן (אין tabId בהורדה) - כשכמה אתרים רצים במקביל, הורדה שאתר אחד
// הפעיל הייתה נתפסת גם ע"י המאזין של אתר אחר (ומשויכת לחברה הלא נכונה). לכן שלב לחיצות ההורדה רץ אתר-אחד-בכל-פעם;
// טעינת העמודים, איסוף הקישורים וההורדות הישירות נשארים מקביליים.
let downloadLock = Promise.resolve();
function withDownloadLock(fn) {
  const run = downloadLock.then(fn, fn);
  downloadLock = run.catch(() => {});
  return run;
}

async function sha256Hex(base64) {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const h = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function looksLikeDoc(base64) {
  const b = atob(base64.slice(0, 16));
  return b.startsWith("PK\x03\x04") || b.startsWith("\xd0\xcf\x11\xe0") || b.startsWith("%PDF-");
}

function utf8b64(s) { return btoa(unescape(encodeURIComponent(s))); }

async function readSites(cfg) {
  const b64 = await getFileBase64(cfg.token, cfg.owner, cfg.repo, cfg.branch, "policy/extension_sites.json");
  return JSON.parse(decodeURIComponent(escape(atob(b64))));
}

// מסלול אתר בודד (כל העמודים שלו, ברצף - בתוך אתר אחד אין תועלת למקביליות:
// אותו טאב/session) - מוזז מתוך runPolicy כדי שאפשר יהיה להריץ כמה אתרים
// שונים במקביל (ר' POLICY_CONCURRENCY). seen משותף בין כל האתרים - בדיוק
// כמו בגרסה הרצית-לגמרי, כדי לשמר את אותה התנהגות דה-דופליקציה.
async function runSite(site, cfg, seen, onProgress) {
  const pages = [...new Set([...(site.pages || []).map((p) => p.url), site.home].filter(Boolean))];
  const files = [], errors = [], diag = [];
  const report = (pi, step) => onProgress({ page: pages[pi], pageNo: pi + 1, pages: pages.length, step, docs: files.length / 2 });
  for (const [pi, pageUrl] of pages.entries()) {
    await report(pi, "טוען עמוד");
    let tab;
    try {
      tab = await tabsRetry(() => chrome.tabs.create({ url: pageUrl, active: false }));
      await waitComplete(tab.id);
      await sleep(3000);
      await report(pi, "פותח אקורדיונים ואוסף קישורים");
      const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: pageCollectLinks,
                                                          args: [(site.clicks || {})[pageUrl] || site.click || []] });
      const links = (res && res.result) || [];
      await report(pi, "ממתין לתור לחיצות ההורדה");
      const cap = await withDownloadLock(async () => { await report(pi, "לוחץ על כפתורי הורדה"); return captureDownloads(tab.id); });
      links.push(...cap.urls.map((u) => ({ ...u, ctx: "(download)" })));
      const docs = links.filter((l) => (DOC_RX.test(l.href) || l.ctx === "(download)" || DOC_RX.test(l.text)) && !NOISE_RX.test(l.text + " " + l.href)
        && (POLICY_RX.test(decodeURIComponent(l.href) + " " + l.text + " " + l.ctx)
            // any_sheet (מור: 7_17_0_2026_9.xlsx): בעמוד שהוגדר ידנית גם גיליונות בלי מילות מדיניות בשם - לא PDF כלליים
            || (site.any_sheet && (site.pages || []).some((p) => p.url === pageUrl) && /\.(xlsx|xls)(\?|#|$)/i.test(l.href))));
      // exclude: מסמכים של חברה אחרת באותו אתר (קרנות: מורים וגננות / מורים תיכוניים)
      const ex = site.exclude ? new RegExp(site.exclude) : null;
      const uniq = [...new Map(docs.filter((d) => !ex || !ex.test(decodeURIComponent(d.href) + " " + d.text))
        .map((d) => [d.href, d])).values()];
      diag.push(`${site.name.slice(0, 18)}: links=${links.length} files=${links.filter((l) => DOC_RX.test(l.href)).length} clicked=${cap.clicked} captured=${cap.urls.length} selected=${uniq.length}`);
      if (!uniq.length) {  // אבחון: אילו קבצים נמצאו ולמה לא נבחרו
        links.filter((l) => DOC_RX.test(l.href)).slice(0, 6).forEach((l) =>
          diag.push(`   ? ${decodeURIComponent(l.href.split("/").pop()).slice(0, 60)} | ${(l.text || "").slice(0, 40)} | ${(l.ctx || "").replace(/\s+/g, " ").slice(0, 60)}`));
      }
      for (const [di, d] of uniq.entries()) {
        await report(pi, `מוריד קובץ ${di + 1}/${uniq.length}`);
        const [r2] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: pageFetchBase64, args: [d.href] });
        const got = r2 && r2.result;
        if (!got || got.__error || !looksLikeDoc(got.base64)) { errors.push(`${d.href} -> ${got && (got.status || got.message)}`); continue; }
        const sha = await sha256Hex(got.base64);
        if (seen[d.href] === sha) continue;
        const name = decodeURIComponent(new URL(d.href).pathname.split("/").pop()).replace(/[^\w.\-֐-׿]/g, "_").slice(0, 90);
        const base = `policy/inbox/${site.legal_id}/${sha.slice(0, 12)}_${name}`;
        files.push({ path: base, base64: got.base64 });
        files.push({ path: base + ".json", base64: utf8b64(JSON.stringify({
          legal_id: site.legal_id, url: d.href, link_text: d.text || d.ctx, source_page: pageUrl,
          sha256: sha, fetched_at: new Date().toISOString(), via: "extension" }, null, 1)) });
        seen[d.href] = sha;
      }
    } catch (e) {
      errors.push(`${pageUrl}: ${e && e.message || e}`);
    } finally {
      if (tab) { try { await tabsRetry(() => chrome.tabs.remove(tab.id)); } catch (e) {} }
    }
  }
  return { files, errors, diag };
}

// כמה אתרים (לא עמודים בתוך אתר - שם אין תועלת, ר' runSite) מותר להריץ
// במקביל - בכל אתר יש לו טאב/session נפרד משלו, אז מקביליות בין-אתרים
// לא מתנגשת. "4" נבחר כמספר בטוח שלא יעמיס מדי על הדפדפן (לא "כל האתרים
// ביחד" ללא הגבלה) - קבוע יחיד כדי שיהיה קל לכוונן.
const POLICY_CONCURRENCY = 4;

// מריץ על כל האתרים, עד POLICY_CONCURRENCY במקביל (לא אחד-אחרי-השני) -
// worker pool: כל worker מושך את האתר הבא מתוך תור משותף עד שנגמר.
// מחזיר {docs, errors, diag}. setStatus - לעדכון החלונית (שורה מצרפת,
// כי כמה אתרים עשויים לדווח התקדמות בו-זמנית).
export async function runPolicy(cfg, setStatus) {
  const sites = await readSites(cfg);
  const { policySeen } = await chrome.storage.local.get("policySeen");
  const seen = policySeen || {};
  const allFiles = [], allErrors = [], allDiag = [];
  const progress = {};  // site.name -> {page, pageNo, pages, step, docs} - אתרים פעילים
  const finished = [];  // {name, docs, errors}
  const started = Date.now();

  // מצב מובנה לחלונית (פס התקדמות + שורה לכל אתר). כתיבות מסודרות בשרשרת - כמה workers מעדכנים במקביל
  // ו-setStatus הוא read-modify-write
  let chain = Promise.resolve();
  function flushStatus(phase) {
    const state = { running: true, phase: phase || "אתרים", total: sites.length, done: finished.length,
                    newDocs: allFiles.length / 2 + Object.values(progress).reduce((a, p) => a + (p.docs || 0), 0),
                    started, active: Object.entries(progress).map(([name, p]) => ({ name, ...p })), finished };
    const text = state.active.map((a) => `${a.name}: ${a.step} (${a.pageNo}/${a.pages})`).join("\n") || "מתחיל...";
    chain = chain.then(() => setStatus({ policyState: state, policyProgress: text })).catch(() => {});
    return chain;
  }

  let nextIdx = 0;
  async function worker() {
    while (nextIdx < sites.length) {
      const site = sites[nextIdx++];
      try {
        const { files, errors, diag } = await runSite(site, cfg, seen, async (p) => {
          progress[site.name] = p;
          await flushStatus();
        });
        allFiles.push(...files);
        allErrors.push(...errors);
        allDiag.push(...diag);
        finished.push({ name: site.name, docs: files.length / 2, errors: errors.length });
      } catch (e) {
        finished.push({ name: site.name, docs: 0, errors: 1 });
        allErrors.push(`${site.name}: ${e && e.message || e}`);
      } finally {
        delete progress[site.name];
        await flushStatus();
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(POLICY_CONCURRENCY, sites.length) }, worker));

  if (allFiles.length) {
    await flushStatus(`מעלה ל-GitHub ${allFiles.length / 2} מסמכים`);
    await commitFiles(cfg.token, cfg.owner, cfg.repo, cfg.branch, allFiles,
      `policy inbox (extension): ${allFiles.length / 2} documents from blocked sites`);
  }
  await chrome.storage.local.set({ policySeen: seen });
  await chain;
  await setStatus({ policyState: { running: false, total: sites.length, done: finished.length, newDocs: allFiles.length / 2,
                                   started, ended: Date.now(), active: [], finished } });
  return { docs: allFiles.length / 2, errors: allErrors, diag: allDiag };
}
