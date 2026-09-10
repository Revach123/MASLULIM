function fmt(ts) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("he-IL", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

async function render() {
  const { status, config } = await chrome.storage.local.get(["status", "config"]);
  const s = status || {};
  document.getElementById("setup-warn").hidden = !!(config && config.token && config.owner && config.repo);
  document.getElementById("block-warn").hidden = !s.blocked;
  document.getElementById("last-run").textContent = s.running ? "רץ כעת..." : fmt(s.lastRun);
  document.getElementById("last-new").textContent =
    s.lastNewCount === undefined ? "—" : String(s.lastNewCount) + (s.lastFailCount ? ` (${s.lastFailCount} נכשלו)` : "");
  document.getElementById("total").textContent = s.totalDocs ?? "—";
  document.getElementById("err").textContent = s.lastError && !s.blocked && !s.needsSetup ? "שגיאה: " + s.lastError : "";
  // חיווי התקדמות חי + נעילת כפתורים בזמן ריצה
  document.getElementById("run").disabled = !!s.running;
  document.getElementById("backfill").disabled = !!s.running;
  if (s.running && s.progress) document.getElementById("msg").textContent = s.progress;
}

// עדכון חי של הפופאפ כל עוד הוא פתוח (הריצה עצמה ממשיכה ברקע בכל מקרה)
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.status) render();
});

function busy(on, text) {
  document.getElementById("run").disabled = on;
  document.getElementById("backfill").disabled = on;
  document.getElementById("msg").textContent = text || "";
}

document.getElementById("run").addEventListener("click", () => {
  busy(true, "מושך ודוחף ל-GitHub...");
  chrome.runtime.sendMessage({ type: "run-incremental" }, async () => {
    busy(false, "הריצה הסתיימה");
    await render();
    setTimeout(() => (document.getElementById("msg").textContent = ""), 3000);
  });
});

document.getElementById("backfill").addEventListener("click", () => {
  if (!confirm("למשוך את כל ההיסטוריה? זה יכול לקחת כמה דקות. אל תסגור את הדפדפן באמצע.")) return;
  busy(true, "מושך היסטוריה... (יכול לקחת כמה דקות)");
  chrome.runtime.sendMessage({ type: "run-backfill" }, async () => {
    busy(false, "ה-backfill הסתיים");
    await render();
    setTimeout(() => (document.getElementById("msg").textContent = ""), 3000);
  });
});

document.getElementById("setup").addEventListener("click", () => chrome.runtime.openOptionsPage());

render();
