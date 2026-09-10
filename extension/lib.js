// לוגיקה משותפת: שליפת דוחות ציבוריים מ-cmainfo.cma.gov.il (מהדפדפן, כלומר
// מה-IP הביתי שעובר את חסימת ה-WAF) וחישובי רבעונים/שמות קבצים.

export const SYSTEM_CODE = { "ביטוח": "in", "גמל": "gm", "פנסיה": "pn" };
export const REPORT_TYPE = "71100184,71100185,71100190";
export const CMA_ORIGIN = "https://cmainfo.cma.gov.il";

export function currentQuarter() {
  const now = new Date();
  return { year: now.getFullYear(), quarter: Math.ceil((now.getMonth() + 1) / 3) };
}

export function prevQuarter(year, quarter) {
  return quarter === 1 ? { year: year - 1, quarter: 4 } : { year, quarter: quarter - 1 };
}

// רשימת רבעונים מהחדש לישן, החל מהרבעון הנוכחי אחורה count רבעונים.
export function recentQuarters(count) {
  const list = [];
  let { year, quarter } = currentQuarter();
  for (let i = 0; i < count; i++) {
    list.push({ year, quarter });
    ({ year, quarter } = prevQuarter(year, quarter));
  }
  return list;
}

export async function fetchQuarterReports(year, quarter) {
  const res = await fetch(`${CMA_ORIGIN}/api/PublicReporting/GetPublicReports`, {
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
      reportType: REPORT_TYPE,
      systemField: "",
      statusReport: 1,
    }),
  });
  if (!res.ok) {
    const err = new Error(`GetPublicReports HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    const err = new Error("GetPublicReports returned non-JSON (likely blocked / not logged in)");
    err.blocked = true;
    throw err;
  }
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

// מוריד קובץ דוח ומחזיר Uint8Array.
export async function downloadDocument(documentId, ext) {
  const res = await fetch(
    `${CMA_ORIGIN}/api/PublicReporting/downloadFiles?IdDoc=${documentId}&extention=${ext}`,
    { credentials: "include" }
  );
  if (!res.ok) throw new Error(`downloadFiles HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  return new Uint8Array(buf);
}

// בכל רבעון, שומרים את ההגשה העדכנית ביותר לכל חברה+מערכת (לפי StatusDate).
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

export function buildBaseFilename(item) {
  const sys = SYSTEM_CODE[item.SystemName] || item.SystemName || "xx";
  return `${item.LegalId || item.DocumentId}_${sys}`;
}

export function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function utf8ToBase64(str) {
  return bytesToBase64(new TextEncoder().encode(str));
}
