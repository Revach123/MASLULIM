// אבחון: בודק אם data.gov.il (CKAN) נגיש מ-GitHub Actions ומה יש שם עבור
// רשות שוק ההון (organization: cma). read-only, מדפיס לוג בלבד.

async function j(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  const text = await res.text();
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {
    /* not json */
  }
  return { status: res.status, contentType: res.headers.get("content-type"), data, textSnippet: text.slice(0, 300) };
}

async function main() {
  const base = "https://data.gov.il/api/3/action";

  console.log("=== 1) package_search organization:cma ===");
  const search = await j(`${base}/package_search?fq=organization:cma&rows=200`);
  console.log(`HTTP ${search.status}, content-type=${search.contentType}`);
  if (!search.data) {
    console.log("body snippet:", search.textSnippet.replace(/\s+/g, " "));
    console.log("data.gov.il NOT reachable/usable from here. Stopping.");
    return;
  }
  const result = search.data.result || {};
  console.log(`total datasets for cma: ${result.count}`);
  const datasets = result.results || [];
  for (const ds of datasets) {
    const resources = ds.resources || [];
    console.log(`\n- title: ${ds.title}`);
    console.log(`  name:  ${ds.name}`);
    console.log(`  resources: ${resources.length}`);
    for (const r of resources.slice(0, 12)) {
      console.log(`    * [${r.format}] ${r.name || "(no name)"} | datastore_active=${r.datastore_active} | id=${r.id}`);
    }
  }
}

main().catch((e) => {
  console.error("probe failed:", e);
  process.exit(1);
});
