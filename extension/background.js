import {
  REPORT_TYPE,
  CMA_ORIGIN,
  CMA_PAGE,
  currentQuarter,
  prevQuarter,
  recentQuarters,
  latestPerCompanyInQuarter,
  buildBaseFilename,
  utf8ToBase64,
} from "./lib.js";
import { readManifest, commitFiles, verifyRepo } from "./github.js";

const ALARM = "cma-daily";
const INCREMENTAL_QUARTERS = 4;
const BACKFILL_EMPTY_STREAK_STOP = 6;
const BACKFILL_MAX_QUARTERS = 80;
const COMMIT_BATCH = 25;
const DOWNLOAD_DELAY_MS = 300;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getConfig() {
  const { config } = await chrome.storage.local.get("config");
  return config || {};
}
async function setStatus(patch) {
  const { status } = await chrome.storage.local.get("status");
  await chrome.storage.local.set({ status: { ...(status || {}), ...patch } });
}

// ----- הרצה בתוך דף ה-CMA (same-origin, בדיוק כמו ה-bookmarklet) -----

async function waitForTabComplete(tabId, timeoutMs = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return;
    await sleep(500);
  }
}

// session משותף לטאב ה-CMA, כדי שנוכל לשחזר אותו אם כרום מסלק/סוגר אותו
// כשעוברים לחלון אחר.
let session = null;

async function ensureCmaTab() {
  if (session) {
    try {
      await chrome.tabs.get(session.tabId);
      return session;
    } catch {
      session = null; // הטאב נסגר/סולק
    }
  }
  const tabs = await chrome.tabs.query({ url: "https://cmainfo.cma.gov.il/*" });
  if (tabs.length > 0) {
    session = { tabId: tabs[0].id, createdByUs: false };
  } else {
    const tab = await chrome.tabs.create({ url: CMA_PAGE, active: false });
    // מונע מכרום לסלק (discard) את הטאב כשעוברים לחלון אחר
    try { await chrome.tabs.update(tab.id, { autoDiscardable: false }); } catch { /* ignore */ }
    await waitForTabComplete(tab.id);
    await sleep(2500); // זמן קצר ל-SPA/עוגיות להתייצב
    session = { tabId: tab.id, createdByUs: true };
  }
  // ודא שגם טאב קיים לא יסולק במהלך הריצה
  try { await chrome.tabs.update(session.tabId, { autoDiscardable: false }); } catch { /* ignore */ }
  return session;
}

// מריץ בתוך הדף, ואם הטאב סולק/נסגר (למשל בזמן מעבר חלון) - משחזר ומנסה שוב.
async function execInTab(func, args) {
  let lastErr;
  for (let attempt = 1; attempt <= 3; attempt++) {
    const s = await ensureCmaTab();
    try {
      const [res] = await chrome.scripting.executeScript({ target: { tabId: s.tabId }, func, args, world: "MAIN" });
      return res?.result;
    } catch (e) {
      lastErr = e;
      session = null; // כנראה הטאב סולק - נשחזר בניסיון הבא
      await sleep(1500 * attempt);
    }
  }
  throw lastErr;
}

// שומר את ה-service worker חי לאורך הריצה (מונע השהיה כשעוברים חלון).
let keepAliveTimer = null;
function startKeepAlive() {
  if (keepAliveTimer) return;
  keepAliveTimer = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);
}
function stopKeepAlive() {
  if (keepAliveTimer) clearInterval(keepAliveTimer);
  keepAliveTimer = null;
}

// מושך רבעון עם ניסיונות חוזרים, כדי שגם אם הטאב עוד "מתחמם" - לחיצה אחת
// תספיק. 403 אמיתי לא מנסים שוב.
async function fetchQuarterResilient(year, quarter) {
  let last;
  for (let attempt = 1; attempt <= 5; attempt++) {
    const resp = await execInTab(pageFetchQuarter, [year, quarter, REPORT_TYPE]);
    if (resp && !resp.__error) return resp;
    last = resp;
    if (resp && resp.status === 403) return resp; // חסימת WAF אמיתית - אין טעם לנסות שוב
    await sleep(1500 * attempt); // 1.5s, 3s, 4.5s, 6s
  }
  return last;
}

// הפונקציות הבאות מוזרקות ורצות בתוך הדף עצמו:
function pageFetchQuarter(year, quarter, reportType) {
  return fetch("/api/PublicReporting/GetPublicReports", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "include",
    body: JSON.stringify({
      corporation: null,
      fromYear: year,
      fromQuarter: quarter,
      toYear: year,
      toQuarter: quarter,
      reportFromDate: null,
      reportToDate: null,
      investmentName: null,
      reportType,
      systemField: "",
      statusReport: 1,
    }),
  })
    .then(async (r) => {
      const ct = r.headers.get("content-type") || "";
      if (!r.ok) return { __error: true, status: r.status };
      if (!ct.includes("application/json")) return { __error: true, status: r.status, nonJson: true };
      const data = await r.json();
      return { items: Array.isArray(data) ? data : [] };
    })
    .catch((e) => ({ __error: true, message: String(e) }));
}

function pageDownloadDoc(documentId, ext) {
  return fetch(`/api/PublicReporting/downloadFiles?IdDoc=${documentId}&extention=${ext}`, {
    credentials: "include",
  })
    .then(async (r) => {
      if (!r.ok) return { __error: true, status: r.status };
      const buf = await r.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = "";
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
      return { base64: btoa(binary) };
    })
    .catch((e) => ({ __error: true, message: String(e) }));
}

// ----- CSV ל-Power Query -----
function manifestCsv(manifest, owner, repo, branch) {
  const cols = ["DocumentId", "LegalId", "ParentCorpName", "SystemName", "ReportPeriodDesc", "StatusDate", "year", "quarter", "path", "content_api_url"];
  const esc = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = Object.values(manifest.documents).sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;
    if (a.quarter !== b.quarter) return b.quarter - a.quarter;
    return (a.ParentCorpName || "").localeCompare(b.ParentCorpName || "", "he");
  });
  const lines = [cols.join(",")];
  for (const r of rows) {
    const apiUrl = `https://api.github.com/repos/${owner}/${repo}/contents/${r.path}?ref=${branch}`;
    lines.push(cols.map((c) => esc(c === "content_api_url" ? apiUrl : r[c])).join(","));
  }
  return "﻿" + lines.join("\n") + "\n";
}

async function collectAndCommit(mode) {
  const cfg = await getConfig();
  if (!cfg.token || !cfg.owner || !cfg.repo) {
    await setStatus({ running: false, needsSetup: true, lastError: "חסרות הגדרות GitHub (owner/repo/token)" });
    notify("נדרשת הגדרה", "פתח את הגדרות התוסף והזן repo + טוקן GitHub.");
    return;
  }
  const branch = cfg.branch || "main";
  await setStatus({ running: true, needsSetup: false, blocked: false, lastError: null, mode, progress: "פותח את אתר רשות שוק ההון..." });

  startKeepAlive();
  const { createdByUs } = await ensureCmaTab();
  try {
    const manifest = await readManifest(cfg.token, cfg.owner, cfg.repo, branch);
    if (!manifest.documents) manifest.documents = {};

    const quarters = mode === "backfill" ? buildBackfillQuarters() : recentQuarters(INCREMENTAL_QUARTERS);

    let downloaded = 0, failed = 0, emptyStreak = 0, batch = [];
    const newNames = [];

    const flush = async () => {
      if (batch.length === 0) return;
      const files = [
        ...batch,
        { path: "manifest.json", base64: utf8ToBase64(JSON.stringify(manifest, null, 2) + "\n") },
        { path: "manifest.csv", base64: utf8ToBase64(manifestCsv(manifest, cfg.owner, cfg.repo, branch)) },
      ];
      await commitFiles(cfg.token, cfg.owner, cfg.repo, branch, files, `Add ${batch.length} report file(s) [${mode}]`);
      batch = [];
    };

    let firstQuarter = true;
    for (const { year, quarter } of quarters) {
      await setStatus({ progress: `בודק ${year}Q${quarter}...` });
      const resp = await fetchQuarterResilient(year, quarter);
      if (!resp || resp.__error) {
        const status = resp?.status;
        // רק 403 אמיתי, או כישלון מתמשך כבר על הרבעון הראשון, נחשב כחסימה
        if (status === 403 || (firstQuarter && resp?.nonJson)) {
          await setStatus({ running: false, blocked: true, progress: "", lastError: `נחסם (status=${status || "?"}). ודא שהדף publicreports נטען ומציג נתונים, ונסה שוב.` });
          notify("נחסם ע\"י האתר", "פתח את publicreports בטאב, ודא שהוא מציג דוחות, ונסה שוב.");
          return;
        }
        firstQuarter = false;
        continue; // שגיאה חולפת - נדלג על הרבעון ונמשיך
      }
      firstQuarter = false;

      const items = latestPerCompanyInQuarter(resp.items || []);
      if (items.length === 0) {
        emptyStreak++;
        if (mode === "backfill" && emptyStreak >= BACKFILL_EMPTY_STREAK_STOP) break;
        continue;
      }
      emptyStreak = 0;

      for (const item of items) {
        if (!item.DocumentId) continue;
        const key = String(item.DocumentId);
        if (manifest.documents[key]) continue;

        const ext = item.fileExt || "xlsx";
        const base = buildBaseFilename(item);
        let path = `reports/${year}Q${quarter}/${base}.${ext}`;
        if (Object.values(manifest.documents).some((d) => d.path === path)) {
          path = `reports/${year}Q${quarter}/${base}_${key}.${ext}`;
        }

        await setStatus({ progress: `מוריד ${year}Q${quarter}: ${item.ParentCorpName || key}` });
        const dl = await execInTab(pageDownloadDoc, [item.DocumentId, ext]);
        if (!dl || dl.__error || !dl.base64) {
          failed++;
        } else {
          batch.push({ path, base64: dl.base64 });
          manifest.documents[key] = {
            DocumentId: key, LegalId: item.LegalId || "", ParentCorpName: item.ParentCorpName || "",
            SystemName: item.SystemName || "", ReportPeriodDesc: item.ReportPeriodDesc || "",
            StatusDate: item.StatusDate || "", year, quarter, path,
          };
          downloaded++;
          newNames.push(item.ParentCorpName || key);
          if (batch.length >= COMMIT_BATCH) {
            await setStatus({ progress: `דוחף ${batch.length} קבצים ל-GitHub...` });
            await flush();
          }
        }
        await sleep(DOWNLOAD_DELAY_MS);
      }
    }

    if (batch.length > 0) await setStatus({ progress: `דוחף ${batch.length} קבצים ל-GitHub...` });
    await flush();

    await setStatus({
      running: false, blocked: false, lastRun: Date.now(), lastMode: mode,
      lastNewCount: downloaded, lastFailCount: failed,
      totalDocs: Object.keys(manifest.documents).length, lastError: null, progress: "",
    });

    if (downloaded > 0) {
      chrome.action.setBadgeBackgroundColor({ color: "#2e7d32" });
      chrome.action.setBadgeText({ text: String(downloaded) });
      notify("דוחות חדשים נדחפו ל-GitHub", `${downloaded} קבצים` + (failed ? ` (${failed} נכשלו)` : "") + " — " + newNames.slice(0, 4).join(", "));
    }
  } finally {
    stopKeepAlive();
    if (createdByUs && session) {
      try { await chrome.tabs.remove(session.tabId); } catch { /* ignore */ }
      session = null;
    }
  }
}

function buildBackfillQuarters() {
  const list = [];
  let { year, quarter } = currentQuarter();
  for (let i = 0; i < BACKFILL_MAX_QUARTERS; i++) {
    list.push({ year, quarter });
    ({ year, quarter } = prevQuarter(year, quarter));
  }
  return list;
}

function notify(title, message) {
  chrome.notifications.create(`cma-${Date.now()}`, { type: "basic", iconUrl: "icons/icon128.png", title, message });
}

async function runSafe(mode) {
  try {
    await collectAndCommit(mode);
  } catch (e) {
    console.error("run failed", e);
    await setStatus({ running: false, lastError: String(e.message || e), lastRun: Date.now() });
    notify("שגיאה בריצה", String(e.message || e).slice(0, 120));
  }
}

async function maybeCatchUp() {
  const { status } = await chrome.storage.local.get("status");
  if (Date.now() - (status?.lastRun || 0) > 20 * 60 * 60 * 1000) runSafe("incremental");
}

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create(ALARM, { periodInMinutes: 24 * 60, delayInMinutes: 2 }));
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 24 * 60, delayInMinutes: 2 });
  maybeCatchUp();
});
chrome.alarms.onAlarm.addListener((a) => { if (a.name === ALARM) runSafe("incremental"); });
chrome.notifications.onClicked.addListener(() => chrome.action.setBadgeText({ text: "" }));

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "run-incremental") { runSafe("incremental").then(() => sendResponse({ ok: true })); return true; }
  if (msg?.type === "run-backfill") { runSafe("backfill").then(() => sendResponse({ ok: true })); return true; }
  if (msg?.type === "verify") {
    (async () => {
      try { await verifyRepo(msg.config.token, msg.config.owner, msg.config.repo); sendResponse({ ok: true }); }
      catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    })();
    return true;
  }
  return false;
});
