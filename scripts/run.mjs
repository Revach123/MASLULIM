import { chromium } from "playwright";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import {
  PUBLIC_REPORTS_URL,
  currentQuarter,
  prevQuarter,
  quarterRange,
  fetchQuarterReports,
  downloadDocumentBase64,
  buildBaseFilename,
  latestPerCompanyInQuarter,
  detectBlockedPage,
} from "./lib.mjs";

const ROOT = path.resolve(new URL(".", import.meta.url).pathname, "..");
const MANIFEST_PATH = path.join(ROOT, "manifest.json");
const CSV_PATH = path.join(ROOT, "manifest.csv");
const REPORTS_DIR = path.join(ROOT, "reports");

const MODE = (process.env.MODE || "incremental").toLowerCase();
const FORCE_BACKFILL = process.env.FORCE_BACKFILL === "1" || process.env.FORCE_BACKFILL === "true";
const INCREMENTAL_QUARTERS_BACK = 3; // כמה רבעונים אחורה לבדוק כל ריצה רגילה (תופס הגשות מאוחרות)
const MAX_LOOKBACK_QUARTERS = 80; // תקרת בטיחות ל-backfill (20 שנה)
const EMPTY_STREAK_STOP = 6; // עוצרים אחרי כך וכך רבעונים ריקים ברצף
const DOWNLOAD_DELAY_MS = 400;
const QUARTER_DELAY_MS = 400;

const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || "Revach123/maslulim";
const BRANCH = process.env.GITHUB_REF_NAME || "main";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function loadManifest() {
  if (!existsSync(MANIFEST_PATH)) {
    return { documents: {}, backfill: { done: false } };
  }
  return JSON.parse(readFileSync(MANIFEST_PATH, "utf-8"));
}

function saveManifest(manifest) {
  writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2) + "\n", "utf-8");
}

function writeCsv(manifest) {
  const rows = Object.values(manifest.documents).sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;
    if (a.quarter !== b.quarter) return b.quarter - a.quarter;
    return (a.ParentCorpName || "").localeCompare(b.ParentCorpName || "", "he");
  });
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
    "raw_url",
  ];
  const escape = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.join(",")];
  for (const row of rows) {
    const rawUrl = `https://raw.githubusercontent.com/${GITHUB_REPOSITORY}/${BRANCH}/${row.path}`;
    lines.push(cols.map((c) => escape(c === "raw_url" ? rawUrl : row[c])).join(","));
  }
  writeFileSync(CSV_PATH, "﻿" + lines.join("\n") + "\n", "utf-8");
}

function uniqueFilePath(dir, baseName, ext, documentId) {
  let filename = `${baseName}.${ext}`;
  let full = path.join(dir, filename);
  if (existsSync(full)) {
    // כבר יש קובץ אחר בשם הזה (למשל תיקון עם DocumentId שונה) - מוסיפים סיומת ייחודית.
    filename = `${baseName}_${documentId}.${ext}`;
    full = path.join(dir, filename);
  }
  return { filename, full };
}

async function processQuarters(page, manifest, quarters, stats) {
  let emptyStreak = 0;
  for (const { year, quarter } of quarters) {
    const result = await fetchQuarterReports(page, year, quarter);
    if (!result.ok) {
      console.log(`[${year}Q${quarter}] fetch failed (status=${result.status}) - stopping this run.`);
      if (result.headers && Object.keys(result.headers).length) {
        console.log(`  headers: ${JSON.stringify(result.headers)}`);
      }
      if (result.bodySnippet) {
        console.log(`  body snippet: ${result.bodySnippet.replace(/\s+/g, " ").trim()}`);
      }
      if (result.error) {
        console.log(`  error: ${result.error}`);
      }
      stats.fetchFailed = true;
      break;
    }
    const items = latestPerCompanyInQuarter(result.items);
    console.log(`[${year}Q${quarter}] ${items.length} companies reported`);

    if (items.length === 0) {
      emptyStreak += 1;
    } else {
      emptyStreak = 0;
    }

    const quarterDir = path.join(REPORTS_DIR, `${year}Q${quarter}`);
    if (items.length > 0 && !existsSync(quarterDir)) mkdirSync(quarterDir, { recursive: true });

    for (const item of items) {
      if (!item.DocumentId) continue;
      const docKey = String(item.DocumentId);
      if (manifest.documents[docKey]) continue; // כבר הורד בעבר

      const ext = item.fileExt || "xlsx";
      const baseName = buildBaseFilename(item);
      const { filename, full } = uniqueFilePath(quarterDir, baseName, ext, docKey);

      try {
        const base64 = await downloadDocumentBase64(page, item.DocumentId, ext);
        writeFileSync(full, Buffer.from(base64, "base64"));
        manifest.documents[docKey] = {
          DocumentId: docKey,
          LegalId: item.LegalId || "",
          ParentCorpName: item.ParentCorpName || "",
          SystemName: item.SystemName || "",
          ReportPeriodDesc: item.ReportPeriodDesc || "",
          StatusDate: item.StatusDate || "",
          year,
          quarter,
          path: path.relative(ROOT, full).split(path.sep).join("/"),
        };
        stats.downloaded += 1;
        console.log(`  + downloaded ${filename}`);
      } catch (err) {
        stats.failed += 1;
        console.error(`  ! failed ${filename}:`, err.message || err);
      }
      await sleep(DOWNLOAD_DELAY_MS);
    }

    await sleep(QUARTER_DELAY_MS);

    if (emptyStreak >= EMPTY_STREAK_STOP) {
      console.log(`Stopping: ${EMPTY_STREAK_STOP} consecutive empty quarters.`);
      stats.stoppedOnEmptyStreak = { year, quarter };
      break;
    }
  }
}

async function main() {
  const manifest = loadManifest();
  const stats = { downloaded: 0, failed: 0 };

  const browser = await chromium.launch({ args: ["--disable-blink-features=AutomationControlled"] });
  const context = await browser.newContext({
    locale: "he-IL",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    extraHTTPHeaders: { "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7" },
  });
  const page = await context.newPage();
  const gotoResponse = await page.goto(PUBLIC_REPORTS_URL, { waitUntil: "networkidle" });
  console.log(`Initial page load: HTTP ${gotoResponse?.status()}`);

  const blockCheck = await detectBlockedPage(page);
  console.log(`Page title: "${blockCheck.title}"`);
  if (blockCheck.looksBlocked) {
    console.log(`Page body looks like a block/challenge page: "${blockCheck.bodySnippet.replace(/\s+/g, " ").trim()}"`);
  }

  if (MODE === "backfill") {
    if (manifest.backfill?.done && !FORCE_BACKFILL) {
      console.log("Backfill already marked done. Set FORCE_BACKFILL=1 to rescan from the current quarter.");
    } else {
      const { year: curY, quarter: curQ } = currentQuarter();
      let { year: oldY, quarter: oldQ } = prevQuarter(curY, curQ);
      for (let i = 0; i < MAX_LOOKBACK_QUARTERS; i++) {
        ({ year: oldY, quarter: oldQ } = prevQuarter(oldY, oldQ));
      }
      const quarters = quarterRange(oldY, oldQ, curY, curQ).reverse(); // מהחדש לישן, עוצרים כשריק
      await processQuarters(page, manifest, quarters, stats);
      manifest.backfill = {
        done: !!stats.stoppedOnEmptyStreak,
        stoppedAt: stats.stoppedOnEmptyStreak || null,
        lastRun: new Date().toISOString(),
      };
    }
  } else {
    const { year: curY, quarter: curQ } = currentQuarter();
    let { year: fromY, quarter: fromQ } = { year: curY, quarter: curQ };
    for (let i = 0; i < INCREMENTAL_QUARTERS_BACK; i++) {
      ({ year: fromY, quarter: fromQ } = prevQuarter(fromY, fromQ));
    }
    const quarters = quarterRange(fromY, fromQ, curY, curQ);
    await processQuarters(page, manifest, quarters, stats);
  }

  await browser.close();

  manifest.meta = { ...(manifest.meta || {}), lastRun: new Date().toISOString(), lastMode: MODE, lastStats: stats };
  saveManifest(manifest);
  writeCsv(manifest);

  console.log(`Done. Downloaded ${stats.downloaded}, failed ${stats.failed}.`);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
