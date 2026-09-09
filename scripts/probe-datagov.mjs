// אבחון שלב 2: בודק את מבנה טבלת הגמל-נט (2024-היום) ב-datastore של data.gov.il:
// שדות, כמות רשומות, וטווח תאריכים - כדי לוודא שזה נתונים חיים ומתעדכנים.

const BASE = "https://data.gov.il/api/3/action";
const RESOURCES = {
  "gemelnet-2024+": "a30dcbea-a1d2-482c-ae29-8f781f5025fb",
  "pensianet-2024+": "6d47d6b5-cb08-488b-b333-f1e717b1e1bd",
  "insurance-2024+": "c6c62cc7-fe02-4b18-8f3e-813abfbb4647",
};

async function j(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  return res.json();
}

async function describe(label, resourceId) {
  console.log(`\n========== ${label} (${resourceId}) ==========`);

  // דגימת רשומה אחת -> שמות שדות
  const sample = await j(`${BASE}/datastore_search?resource_id=${resourceId}&limit=1`);
  if (!sample.success) {
    console.log("datastore_search failed:", JSON.stringify(sample.error));
    return;
  }
  const fields = sample.result.fields.map((f) => f.id);
  console.log("total records:", sample.result.total);
  console.log("fields:", fields.join(", "));
  console.log("sample row:", JSON.stringify(sample.result.records[0]));

  // ניסיון למצוא את שדה התאריך ואת הערך המקסימלי (הכי עדכני)
  const dateField = fields.find((f) => /date|תאריך|month|חודש|תקופה|period/i.test(f));
  if (dateField) {
    const sql = encodeURIComponent(
      `SELECT MAX("${dateField}") AS max_d, MIN("${dateField}") AS min_d FROM "${resourceId}"`
    );
    const range = await j(`${BASE}/datastore_search_sql?sql=${sql}`);
    if (range.success) {
      console.log(`date field "${dateField}" range:`, JSON.stringify(range.result.records[0]));
    } else {
      console.log("SQL range query failed:", JSON.stringify(range.error).slice(0, 200));
    }
  } else {
    console.log("no obvious date field found among:", fields.join(", "));
  }
}

async function main() {
  for (const [label, id] of Object.entries(RESOURCES)) {
    await describe(label, id);
  }
}

main().catch((e) => {
  console.error("probe failed:", e);
  process.exit(1);
});
