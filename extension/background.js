import {
  recentQuarters,
  currentQuarter,
  prevQuarter,
  fetchQuarterReports,
  downloadDocument,
  latestPerCompanyInQuarter,
  buildBaseFilename,
  bytesToBase64,
  utf8ToBase64,
} from "./lib.js";
import { readManifest, commitFiles, verifyRepo } from "./github.js";

const ALARM = "cma-daily";
const INCREMENTAL_QUARTERS = 4; // כמה רבעונים אחורה לבדוק בריצה יומית (תופס הגשות מאוחרות)
const BACKFILL_EMPTY_STREAK_STOP = 6;
const BACKFILL_MAX_QUARTERS = 80;
const COMMIT_BATCH = 25; // כמה קבצים בכל commit (חוסך זיכרון בעת backfill גדול)
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

function manifestCsv(manifest, owner, repo, branch) {
  const cols = [
    "DocumentId",
    "LegalId",
    "ParentCorpName",
    "SystemName",
    "ReportPeriodDesc",
    "StatusDate",
    "year",
    "quarter",
    "path",
    "content_api_url",
  ];
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
  await setStatus({ running: true, needsSetup: false, lastError: null, mode });

  const manifest = await readManifest(cfg.token, cfg.owner, cfg.repo, branch);
  if (!manifest.documents) manifest.documents = {};

  const quarters =
    mode === "backfill"
      ? buildBackfillQuarters()
      : recentQuarters(INCREMENTAL_QUARTERS);

  let downloaded = 0;
  let failed = 0;
  let emptyStreak = 0;
  let batch = [];
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

  for (const { year, quarter } of quarters) {
    let items;
    try {
      items = latestPerCompanyInQuarter(await fetchQuarterReports(year, quarter));
    } catch (e) {
      if (e.blocked || e.status === 403) {
        await setStatus({ running: false, blocked: true, lastError: "האתר חסם את הבקשה (403). ודא שאתה גולש מישראל ומחובר לאתר." });
        notify("נחסם ע\"י האתר", "פתח את אתר רשות שוק ההון בטאב, ודא שנטען, ונסה שוב.");
        return;
      }
      throw e;
    }

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
      // התנגשות שם (תיקון עם DocumentId שונה) -> להוסיף מזהה
      if (Object.values(manifest.documents).some((d) => d.path === path)) {
        path = `reports/${year}Q${quarter}/${base}_${key}.${ext}`;
      }

      try {
        const bytes = await downloadDocument(item.DocumentId, ext);
        batch.push({ path, base64: bytesToBase64(bytes) });
        manifest.documents[key] = {
          DocumentId: key,
          LegalId: item.LegalId || "",
          ParentCorpName: item.ParentCorpName || "",
          SystemName: item.SystemName || "",
          ReportPeriodDesc: item.ReportPeriodDesc || "",
          StatusDate: item.StatusDate || "",
          year,
          quarter,
          path,
        };
        downloaded++;
        newNames.push(item.ParentCorpName || key);
        if (batch.length >= COMMIT_BATCH) await flush();
      } catch (e) {
        failed++;
        console.error("download failed", item, e);
      }
      await sleep(DOWNLOAD_DELAY_MS);
    }
  }

  await flush();

  await chrome.storage.local.set({ manifest_meta: { total: Object.keys(manifest.documents).length } });
  await setStatus({
    running: false,
    blocked: false,
    lastRun: Date.now(),
    lastMode: mode,
    lastNewCount: downloaded,
    lastFailCount: failed,
    totalDocs: Object.keys(manifest.documents).length,
    lastError: null,
  });

  if (downloaded > 0) {
    chrome.action.setBadgeBackgroundColor({ color: "#2e7d32" });
    chrome.action.setBadgeText({ text: String(downloaded) });
    notify(
      "דוחות חדשים נדחפו ל-GitHub",
      `${downloaded} קבצים חדשים` + (failed ? ` (${failed} נכשלו)` : "") + " — " + newNames.slice(0, 4).join(", ")
    );
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
  chrome.notifications.create(`cma-${Date.now()}`, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
  });
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
  const last = status?.lastRun || 0;
  if (Date.now() - last > 20 * 60 * 60 * 1000) runSafe("incremental");
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 24 * 60, delayInMinutes: 2 });
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 24 * 60, delayInMinutes: 2 });
  maybeCatchUp();
});
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === ALARM) runSafe("incremental");
});
chrome.notifications.onClicked.addListener(() => chrome.action.setBadgeText({ text: "" }));

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "run-incremental") {
    runSafe("incremental").then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg?.type === "run-backfill") {
    runSafe("backfill").then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg?.type === "verify") {
    (async () => {
      try {
        const c = msg.config;
        await verifyRepo(c.token, c.owner, c.repo);
        sendResponse({ ok: true });
      } catch (e) {
        sendResponse({ ok: false, error: String(e.message || e) });
      }
    })();
    return true;
  }
  return false;
});
