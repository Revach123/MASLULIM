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
const NOISE_RX = /esg|אחראי|תגמול|פרטיות|privacy|תקנון|מבצע|גילוי[-_ ]נאות|מצגת|presentation/i;

async function waitComplete(tabId, timeoutMs = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const t = await chrome.tabs.get(tabId);
    if (t.status === "complete") return;
    await sleep(500);
  }
}

// רץ בתוך הדף: פותח אקורדיונים/לשוניות, ומחזיר את כל הקישורים (כולל בתוך iframes מאותו origin).
function pageCollectLinks() {
  const clickAll = (sel) => document.querySelectorAll(sel).forEach((el) => { try { el.click(); } catch (e) {} });
  clickAll('[aria-expanded="false"]:not(a)');
  clickAll("details:not([open]) > summary");
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

// מריץ על כל האתרים; מחזיר {files, errors}. setStatus - לעדכון החלונית.
export async function runPolicy(cfg, setStatus) {
  const sites = await readSites(cfg);
  const { policySeen } = await chrome.storage.local.get("policySeen");
  const seen = policySeen || {};
  const files = [], errors = [];
  for (const site of sites) {
    const pages = [...new Set([...(site.pages || []).map((p) => p.url), site.home].filter(Boolean))];
    for (const pageUrl of pages) {
      await setStatus({ policyProgress: `${site.name}: ${pageUrl}` });
      let tab;
      try {
        tab = await chrome.tabs.create({ url: pageUrl, active: false });
        await waitComplete(tab.id);
        await sleep(3000);
        const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: pageCollectLinks });
        const links = (res && res.result) || [];
        const docs = links.filter((l) => DOC_RX.test(l.href) && !NOISE_RX.test(l.text + " " + l.href)
          && (POLICY_RX.test(decodeURIComponent(l.href) + " " + l.text + " " + l.ctx) || (site.pages || []).some((p) => p.url === pageUrl)));
        const uniq = [...new Map(docs.map((d) => [d.href, d])).values()];
        for (const d of uniq) {
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
        if (tab) { try { await chrome.tabs.remove(tab.id); } catch (e) {} }
      }
    }
  }
  if (files.length) {
    await commitFiles(cfg.token, cfg.owner, cfg.repo, cfg.branch, files,
      `policy inbox (extension): ${files.length / 2} documents from blocked sites`);
  }
  await chrome.storage.local.set({ policySeen: seen });
  return { docs: files.length / 2, errors };
}
