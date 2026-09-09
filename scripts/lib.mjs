// לוגיקה משותפת לשליפת דוחות ציבוריים מ-cmainfo.cma.gov.il, זהה במהות
// ל-bookmarklet המקורי, אבל רץ בתוך דף אמיתי (Playwright) כדי לעבור כל
// הגנת בוט/WAF של האתר בדיוק כמו דפדפן רגיל.

export const SYSTEM_CODE = { "ביטוח": "in", "גמל": "gm", "פנסיה": "pn" };
export const REPORT_TYPE = "71100184,71100185,71100190";
export const PUBLIC_REPORTS_URL = "https://cmainfo.cma.gov.il/publicreports";

export function quarterCode(periodDesc) {
  const m = (periodDesc || "").match(/רבעון\s*(\d)/);
  return m ? String(m[1]).padStart(2, "0") : "00";
}

export function yearCode(periodDesc) {
  const m = (periodDesc || "").match(/(\d{4})/);
  return m ? m[1].slice(2) : "00";
}

export function currentQuarter() {
  const now = new Date();
  return { year: now.getFullYear(), quarter: Math.ceil((now.getMonth() + 1) / 3) };
}

export function prevQuarter(year, quarter) {
  return quarter === 1 ? { year: year - 1, quarter: 4 } : { year, quarter: quarter - 1 };
}

// רשימת רבעונים כרונולוגית (מהישן לחדש) בין שתי נקודות, כולל.
export function quarterRange(fromYear, fromQuarter, toYear, toQuarter) {
  const list = [];
  let y = fromYear;
  let q = fromQuarter;
  // הגנה מפני לולאה אינסופית אם הפרמטרים הפוכים בטעות
  let guard = 0;
  while ((y < toYear || (y === toYear && q <= toQuarter)) && guard < 400) {
    list.push({ year: y, quarter: q });
    if (q === 4) {
      q = 1;
      y += 1;
    } else {
      q += 1;
    }
    guard += 1;
  }
  return list;
}

// שולף מהעמוד עצמו (page.evaluate) כדי לשתף cookies/headers אמיתיים.
export async function fetchQuarterReports(page, year, quarter) {
  return page.evaluate(
    async ({ year, quarter, reportType }) => {
      try {
        const res = await fetch("/api/PublicReporting/GetPublicReports", {
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
        });
        if (!res.ok) return { ok: false, status: res.status, items: [] };
        const contentType = res.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) return { ok: false, status: res.status, items: [] };
        const data = await res.json();
        return { ok: true, status: res.status, items: Array.isArray(data) ? data : [] };
      } catch (err) {
        return { ok: false, status: 0, items: [], error: String(err) };
      }
    },
    { year, quarter, reportType: REPORT_TYPE }
  );
}

// מוריד קובץ בתוך הדף (fetch + blob->base64) ומחזיר מחרוזת base64,
// כדי שאפשר יהיה לכתוב אותו לדיסק מ-Node.
export async function downloadDocumentBase64(page, documentId, ext) {
  return page.evaluate(
    async ({ documentId, ext }) => {
      const res = await fetch(`/api/PublicReporting/downloadFiles?IdDoc=${documentId}&extention=${ext}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buffer = await res.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
      }
      return btoa(binary);
    },
    { documentId, ext }
  );
}

export function buildBaseFilename(item) {
  const sys = SYSTEM_CODE[item.SystemName] || item.SystemName || "xx";
  return `${item.LegalId || item.DocumentId}_${sys}`;
}

// בכל רבעון בודד, לרוב יש הגשה אחת לכל חברה+מערכת; אם יש כמה (תיקונים),
// שומרים רק את העדכנית ביותר (לפי StatusDate).
export function latestPerCompanyInQuarter(items) {
  const byKey = {};
  for (const item of items) {
    const key = `${item.LegalId}_${item.SystemName}`;
    const existing = byKey[key];
    if (!existing || new Date(item.StatusDate || 0) > new Date(existing.StatusDate || 0)) {
      byKey[key] = item;
    }
  }
  return Object.values(byKey);
}
