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
import { readManifest, commitFiles, verifyRepo, getFileBase64 } from "./github.js";

const ALARM = "cma-daily";
const INCREMENTAL_QUARTERS = 4;
const BACKFILL_EMPTY_STREAK_STOP = 6;
const BACKFILL_MAX_QUARTERS = 80;
const COMMIT_BATCH = 50;
const COMMIT_GAP_MS = 1200; // המתנה בין commits כדי לא לעורר secondary rate limit
const DOWNLOAD_DELAY_MS = 300;
// תיקייה מקומית אחת (שטוחה) בתיקיית ההורדות - כל הקבצים יחד, כמו ה-bookmarklet.
// ב-git הם נשמרים מחולקים לרבעונים; מקומית הכל במקום אחד.
const LOCAL_FOLDER = "דוחות רבעוניים - רשות שוק ההון";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// שומר עותק מקומי בתיקיית ההורדות (תיקייה אחת שטוחה).
async function saveLocal(base64, filename) {
  try {
    await chrome.downloads.download({
      url: "data:application/octet-stream;base64," + base64,
      filename: `${LOCAL_FOLDER}/${filename}`,
      conflictAction: "overwrite",
      saveAs: false,
    });
  } catch (e) {
    console.warn("local save failed", filename, e);
  }
}

async function getConfig() {
  const { config } = await chrome.storage.local.get("config");
  const c = config || {};
  // ניקוי רווחים/שורות נסתרים שנדבקו יחד עם הטוקן (גורם ל-401 Bad credentials)
  if (c.token) c.token = c.token.replace(/\s+/g, "");
  if (c.owner) c.owner = c.owner.trim();
  if (c.repo) c.repo = c.repo.trim();
  return c;
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
// דגל עצירה - נדלק כשהמשתמש לוחץ "עצור".
let stopRequested = false;

// תמיד מייצרים טאב רקע ייעודי משלנו (לא משתמשים בטאב שהמשתמש פתח), כדי
// שניווט/רענון מצד המשתמש לא יפיל את הריצה. הטאב נסגר בסוף הריצה.
async function ensureCmaTab() {
  if (session) {
    try {
      const t = await chrome.tabs.get(session.tabId);
      if (t && t.status === "complete") return session;
      await waitForTabComplete(session.tabId, 20000);
      return session;
    } catch {
      session = null; // הטאב נסגר/סולק - ניצור חדש
    }
  }
  const tab = await chrome.tabs.create({ url: CMA_PAGE, active: false });
  try { await chrome.tabs.update(tab.id, { autoDiscardable: false }); } catch { /* ignore */ }
  await waitForTabComplete(tab.id);
  await sleep(3000); // זמן ל-SPA לסיים redirect/טעינה לפני הזרקה
  session = { tabId: tab.id, createdByUs: true };
  return session;
}

// מריץ בתוך הדף. אם המסגרת נעלמה (ניווט/רענון/סגירה) - יוצר טאב טרי ומנסה שוב.
async function execInTab(func, args) {
  let lastErr;
  for (let attempt = 1; attempt <= 4; attempt++) {
    const s = await ensureCmaTab();
    try {
      await waitForTabComplete(s.tabId, 20000); // לא להזריק באמצע טעינה/ניווט
      const [res] = await chrome.scripting.executeScript({ target: { tabId: s.tabId, frameIds: [0] }, func, args, world: "MAIN" });
      return res?.result;
    } catch (e) {
      lastErr = e;
      // "Frame with ID 0 was removed" / טאב נסגר - נשמיד ונשחזר טאב חדש
      try { if (session) await chrome.tabs.remove(session.tabId); } catch { /* ignore */ }
      session = null;
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
  stopRequested = false;
  await setStatus({ running: true, needsSetup: false, blocked: false, tokenInvalid: false, lastError: null, mode, progress: "בודק חיבור ל-GitHub..." });

  // בדיקת טוקן מראש (fail-fast) - כדי לא לבזבז הורדות אם הטוקן לא תקף/בלי כתיבה
  try {
    const repoInfo = await verifyRepo(cfg.token, cfg.owner, cfg.repo);
    if (repoInfo && repoInfo.permissions && repoInfo.permissions.push === false) {
      await setStatus({ running: false, tokenInvalid: true, progress: "", lastRun: Date.now(),
        lastError: "לטוקן אין הרשאת כתיבה. צור טוקן עם Contents: Read and write ועדכן בהגדרות." });
      notify("אין הרשאת כתיבה", "הטוקן קורא אך לא כותב. צור טוקן עם Contents: Read and write.");
      return;
    }
  } catch (e) {
    const msg = String(e.message || e);
    await setStatus({ running: false, tokenInvalid: true, progress: "", lastRun: Date.now(),
      lastError: `בדיקת החיבור ל-GitHub נכשלה (${msg.match(/HTTP \d+/)?.[0] || "שגיאה"}). ודא שהטוקן תקף ושייך לחשבון ${cfg.owner}.` });
    notify("חיבור GitHub נכשל", "הטוקן לא תקף או לא שייך לחשבון/repo הנכון. עדכן בהגדרות.");
    return;
  }

  await setStatus({ progress: "פותח את אתר רשות שוק ההון..." });
  startKeepAlive();
  const { createdByUs } = await ensureCmaTab();
  try {
    const manifest = await readManifest(cfg.token, cfg.owner, cfg.repo, branch);
    if (!manifest.documents) manifest.documents = {};

    const quarters = mode === "backfill" ? buildBackfillQuarters() : recentQuarters(INCREMENTAL_QUARTERS);

    let downloaded = 0, failed = 0, emptyStreak = 0, batch = [];
    const newNames = [];
    // איסוף רשימת החברות שהגישו בכל רבעון, לחישוב הדשבורד
    const submittedByQ = {}; // "YYYYQn" -> Set(LegalId_System)
    const orderedQ = [];     // סדר הרבעונים שנבדקו (מהחדש לישן)

    // דחיפה מקבילה: כל אצווה נדחפת ל-git ברקע בזמן שהמשיכה ממשיכה. ה-commits
    // עצמם מסודרים בשרשרת (אחד בכל פעם) כדי למנוע התנגשות בתוך אותה ריצה.
    let commitChain = Promise.resolve();
    let commitError = null;
    const enqueueFlush = () => {
      if (batch.length === 0 || commitError) return;
      const n = batch.length;
      const files = [
        ...batch,
        { path: "manifest.json", base64: utf8ToBase64(JSON.stringify(manifest, null, 2) + "\n") },
        { path: "manifest.csv", base64: utf8ToBase64(manifestCsv(manifest, cfg.owner, cfg.repo, branch)) },
      ];
      batch = [];
      commitChain = commitChain
        .then(async () => {
          await commitFiles(cfg.token, cfg.owner, cfg.repo, branch, files, `Add ${n} report file(s) [${mode}]`);
          await sleep(COMMIT_GAP_MS);
        })
        .catch((e) => { commitError = e; });
    };

    // ===== שלב 1: סריקת הרשימה המלאה ובניית הדשבורד לפני שמתחילים להוריד =====
    const quarterItems = {}; // qKey -> items[]
    let firstQuarter = true;
    for (const { year, quarter } of quarters) {
      if (stopRequested) break;
      await setStatus({ progress: `סורק את הרשימה: ${year}Q${quarter}...` });
      const resp = await fetchQuarterResilient(year, quarter);
      if (!resp || resp.__error) {
        const status = resp?.status;
        if (status === 403 || (firstQuarter && resp?.nonJson)) {
          await setStatus({ running: false, blocked: true, progress: "", lastError: `נחסם (status=${status || "?"}). ודא שהדף publicreports נטען ומציג נתונים, ונסה שוב.` });
          notify("נחסם ע\"י האתר", "פתח את publicreports בטאב, ודא שהוא מציג דוחות, ונסה שוב.");
          return;
        }
        firstQuarter = false;
        continue;
      }
      firstQuarter = false;

      const items = latestPerCompanyInQuarter(resp.items || []);
      const qKey = `${year}Q${quarter}`;
      submittedByQ[qKey] = new Set(items.map((it) => `${it.LegalId}_${it.SystemName}`));
      orderedQ.push(qKey);
      quarterItems[qKey] = items;
      await updateDashboard(manifest, submittedByQ, orderedQ); // בונה את הדשבורד תוך כדי הסריקה
      if (items.length === 0) {
        emptyStreak++;
        if (mode === "backfill" && emptyStreak >= BACKFILL_EMPTY_STREAK_STOP) break;
      } else {
        emptyStreak = 0;
      }
    }

    // ===== שלב 2: הורדה ודחיפה, לפי הרשימה שנסרקה =====
    for (const qKey of orderedQ) {
      if (stopRequested || commitError) break;
      const items = quarterItems[qKey] || [];
      const year = parseInt(qKey);
      const quarter = parseInt(qKey.split("Q")[1]);

      for (const item of items) {
        if (stopRequested) break;
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
          await saveLocal(dl.base64, path.split("/").pop()); // עותק מקומי שטוח
          manifest.documents[key] = {
            DocumentId: key, LegalId: item.LegalId || "", ParentCorpName: item.ParentCorpName || "",
            SystemName: item.SystemName || "", ReportPeriodDesc: item.ReportPeriodDesc || "",
            StatusDate: item.StatusDate || "", year, quarter, path,
          };
          downloaded++;
          newNames.push(item.ParentCorpName || key);
          if (batch.length >= COMMIT_BATCH) {
            enqueueFlush(); // דוחף ברקע, לא חוסם את המשך המשיכה
            await updateDashboard(manifest, submittedByQ, orderedQ);
          }
        }
        if (commitError) throw commitError;
        await sleep(DOWNLOAD_DELAY_MS);
      }
      await updateDashboard(manifest, submittedByQ, orderedQ); // עדכון בסוף הרבעון
    }

    enqueueFlush();
    await setStatus({ progress: "משלים דחיפה ל-GitHub..." });
    await commitChain; // ממתין לסיום כל הדחיפות שברקע
    if (commitError) throw commitError;

    await updateDashboard(manifest, submittedByQ, orderedQ);

    await setStatus({
      running: false, blocked: false, lastRun: Date.now(), lastMode: mode,
      lastNewCount: downloaded, lastFailCount: failed, stopped: stopRequested,
      totalDocs: Object.keys(manifest.documents).length, lastError: null,
      progress: stopRequested ? `נעצר - ${downloaded} קבצים נמשכו עד העצירה` : "",
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

// מחשב ומאחסן סטטיסטיקת דשבורד לכל רבעון:
//  downloaded            = כמה דוחות של הרבעון כבר בארכיון
//  readyNotDownloaded    = הגישו לרשות אך עדיין לא נמשכו אלינו
//  pending               = טרם הגישו (מי שהגיש ברבעון הקודם ולא ברבעון זה)
async function updateDashboard(manifest, submittedByQ, orderedQ) {
  // ספירת מה שהורד בפועל, לכל רבעון
  const downloadedByQ = {};
  for (const d of Object.values(manifest.documents)) {
    const k = `${d.year}Q${d.quarter}`;
    downloadedByQ[k] = (downloadedByQ[k] || 0) + 1;
  }

  const { dashboard } = await chrome.storage.local.get("dashboard");
  const byQuarter = (dashboard && dashboard.byQuarter) || {};

  for (let i = 0; i < orderedQ.length; i++) {
    const k = orderedQ[i];
    const cur = submittedByQ[k];
    if (!cur) continue;
    const submitted = cur.size;
    const downloaded = downloadedByQ[k] || 0;
    const readyNotDownloaded = Math.max(0, submitted - downloaded);

    // רבעון קודם (הישן יותר) = הבא ברשימה שמסודרת מהחדש לישן
    let pending = null;
    const prevKey = orderedQ[i + 1];
    if (prevKey && submittedByQ[prevKey]) {
      const prev = submittedByQ[prevKey];
      let miss = 0;
      for (const c of prev) if (!cur.has(c)) miss++;
      pending = miss;
    }

    byQuarter[k] = {
      year: parseInt(k), quarter: parseInt(k.split("Q")[1]),
      submitted, downloaded, readyNotDownloaded, pending,
    };
  }

  await chrome.storage.local.set({ dashboard: { byQuarter, updatedAt: Date.now() } });
}

// שומר מקומית (תיקייה אחת שטוחה) את כל הקבצים שכבר בארכיון ה-git.
// שימושי כדי למלא את התיקייה המקומית בלי למשוך שוב מהאתר, וגם במחשב חדש.
async function syncLocalFromArchive() {
  const cfg = await getConfig();
  if (!cfg.token || !cfg.owner || !cfg.repo) {
    await setStatus({ running: false, needsSetup: true, lastError: "חסרות הגדרות GitHub" });
    return;
  }
  const branch = cfg.branch || "main";
  stopRequested = false;
  await setStatus({ running: true, needsSetup: false, tokenInvalid: false, lastError: null, progress: "קורא רשימה מ-GitHub..." });
  startKeepAlive();
  try {
    const manifest = await readManifest(cfg.token, cfg.owner, cfg.repo, branch);
    const docs = Object.values(manifest.documents || {});
    let saved = 0, failed = 0, i = 0;
    for (const d of docs) {
      if (stopRequested) break;
      i++;
      await setStatus({ progress: `שומר מקומית ${i}/${docs.length}: ${d.ParentCorpName || d.DocumentId}` });
      try {
        const b64 = await getFileBase64(cfg.token, cfg.owner, cfg.repo, branch, d.path);
        await saveLocal(b64, d.path.split("/").pop());
        saved++;
      } catch (e) {
        failed++;
        console.warn("sync-local failed", d.path, e);
      }
      await sleep(120);
    }
    await setStatus({ running: false, progress: "", lastError: null, lastRun: Date.now(), lastNewCount: saved, lastFailCount: failed, totalDocs: docs.length });
    notify("סנכרון מקומי הושלם", `${saved} קבצים נשמרו לתיקייה המקומית` + (failed ? ` (${failed} נכשלו)` : ""));
  } catch (e) {
    await setStatus({ running: false, progress: "", lastError: String(e.message || e) });
    notify("שגיאה בסנכרון מקומי", String(e.message || e).slice(0, 120));
  } finally {
    stopKeepAlive();
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

function isBadToken(msg) {
  return /HTTP 401/.test(msg) || /bad credentials/i.test(msg);
}

async function runSafe(mode) {
  try {
    await collectAndCommit(mode);
  } catch (e) {
    console.error("run failed", e);
    const msg = String(e.message || e);
    if (isBadToken(msg)) {
      await setStatus({ running: false, progress: "", tokenInvalid: true, lastRun: Date.now(),
        lastError: "הטוקן ל-GitHub לא תקף או פג תוקף. צור טוקן חדש (Contents: Read and write) ועדכן בהגדרות." });
      notify("טוקן GitHub לא תקף", "צור טוקן חדש (Contents: Read and write) ועדכן בהגדרות התוסף.");
    } else {
      await setStatus({ running: false, tokenInvalid: false, lastError: msg, lastRun: Date.now() });
      notify("שגיאה בריצה", msg.slice(0, 120));
    }
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
  if (msg?.type === "sync-local") { syncLocalFromArchive().then(() => sendResponse({ ok: true })); return true; }
  if (msg?.type === "stop") { stopRequested = true; setStatus({ progress: "עוצר..." }).then(() => sendResponse({ ok: true })); return true; }
  if (msg?.type === "verify") {
    (async () => {
      try { await verifyRepo(msg.config.token, msg.config.owner, msg.config.repo); sendResponse({ ok: true }); }
      catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    })();
    return true;
  }
  return false;
});
