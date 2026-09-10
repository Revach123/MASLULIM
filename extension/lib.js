// עזרי לוגיקה טהורים (חישובי רבעונים, שמות קבצים). המשיכה עצמה מהאתר קורית
// בתוך דף ה-CMA (ראה background.js) כדי לשלוח בקשות same-origin בדיוק כמו
// ה-bookmarklet - זה מה שעובר את חסימת ה-WAF.

export const SYSTEM_CODE = { "ביטוח": "in", "גמל": "gm", "פנסיה": "pn" };
export const REPORT_TYPE = "71100184,71100185,71100190";
export const CMA_ORIGIN = "https://cmainfo.cma.gov.il";
export const CMA_PAGE = "https://cmainfo.cma.gov.il/publicreports";

export function currentQuarter() {
  const now = new Date();
  return { year: now.getFullYear(), quarter: Math.ceil((now.getMonth() + 1) / 3) };
}

export function prevQuarter(year, quarter) {
  return quarter === 1 ? { year: year - 1, quarter: 4 } : { year, quarter: quarter - 1 };
}

export function recentQuarters(count) {
  const list = [];
  let { year, quarter } = currentQuarter();
  for (let i = 0; i < count; i++) {
    list.push({ year, quarter });
    ({ year, quarter } = prevQuarter(year, quarter));
  }
  return list;
}

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

export function utf8ToBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}
