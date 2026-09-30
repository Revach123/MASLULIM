function fmt(ts) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("he-IL", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

const COLORS = { downloaded: "#2e7d32", ready: "#e65100", pending: "#9e9e9e" };
const LABELS = { downloaded: "הורדו", ready: "מוכנים שטרם נמשכו", pending: "טרם הגישו" };

// בונה SVG של פאי מרשימת פלחים [{value,color}]
function pieSvg(parts, size) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  const r = size / 2, cx = r, cy = r;
  if (total === 0) {
    return `<svg class="pie" width="${size}" height="${size}"><circle cx="${cx}" cy="${cy}" r="${r - 1}" fill="#eee"/></svg>`;
  }
  // פלח יחיד = עיגול מלא (path של arc לא עובד ל-360°)
  const nonzero = parts.filter((p) => p.value > 0);
  if (nonzero.length === 1) {
    return `<svg class="pie" width="${size}" height="${size}"><circle cx="${cx}" cy="${cy}" r="${r - 1}" fill="${nonzero[0].color}"/></svg>`;
  }
  let angle = -Math.PI / 2;
  let paths = "";
  for (const p of nonzero) {
    const slice = (p.value / total) * Math.PI * 2;
    const x1 = cx + (r - 1) * Math.cos(angle), y1 = cy + (r - 1) * Math.sin(angle);
    angle += slice;
    const x2 = cx + (r - 1) * Math.cos(angle), y2 = cy + (r - 1) * Math.sin(angle);
    const large = slice > Math.PI ? 1 : 0;
    paths += `<path d="M${cx},${cy} L${x1},${y1} A${r - 1},${r - 1} 0 ${large} 1 ${x2},${y2} Z" fill="${p.color}"/>`;
  }
  return `<svg class="pie" width="${size}" height="${size}">${paths}</svg>`;
}

function qLabel(k) {
  const [y, q] = k.split("Q");
  return `${y} רבעון ${q}`;
}

async function renderDashboard() {
  const { dashboard } = await chrome.storage.local.get("dashboard");
  const el = document.getElementById("dashboard");
  const byQ = dashboard && dashboard.byQuarter;
  if (!byQ || Object.keys(byQ).length === 0) {
    el.innerHTML = `<div class="dash-title">התקדמות לפי רבעון</div><div class="dash-empty">אין עדיין נתונים - הרץ "בדוק ומשוך עכשיו".</div>`;
    return;
  }
  const keys = Object.keys(byQ).sort((a, b) => byQ[b].year - byQ[a].year || byQ[b].quarter - byQ[a].quarter);
  let html = `<div class="dash-title">התקדמות לפי רבעון <span class="dash-updated">(עודכן ${fmt(dashboard.updatedAt)})</span></div>`;
  for (const k of keys) {
    const d = byQ[k];
    const parts = [
      { key: "downloaded", value: d.downloaded || 0, color: COLORS.downloaded },
      { key: "ready", value: d.readyNotDownloaded || 0, color: COLORS.ready },
      { key: "pending", value: d.pending || 0, color: COLORS.pending },
    ];
    const legend = parts
      .filter((p) => !(p.key === "pending" && d.pending === null))
      .map((p) => `<div class="legrow"><span class="dot" style="background:${p.color}"></span>${LABELS[p.key]}: <b>${p.value}</b></div>`)
      .join("");
    html += `<div class="qcard">${pieSvg(parts, 74)}<div class="info"><div class="qname">${qLabel(k)}</div>${legend}</div></div>`;
  }
  el.innerHTML = html;
}

async function render() {
  const { status, config } = await chrome.storage.local.get(["status", "config"]);
  const s = status || {};
  renderDashboard();
  document.getElementById("setup-warn").hidden = !!(config && config.token && config.owner && config.repo);
  document.getElementById("block-warn").hidden = !s.blocked;
  document.getElementById("token-warn").hidden = !s.tokenInvalid;
  document.getElementById("last-run").textContent = s.running ? "רץ כעת..." : fmt(s.lastRun);
  document.getElementById("last-new").textContent =
    s.lastNewCount === undefined ? "—" : String(s.lastNewCount) + (s.lastFailCount ? ` (${s.lastFailCount} נכשלו)` : "");
  document.getElementById("total").textContent = s.totalDocs ?? "—";
  document.getElementById("err").textContent = s.lastError && !s.blocked && !s.needsSetup && !s.tokenInvalid ? "שגיאה: " + s.lastError : "";
  // חיווי התקדמות חי + נעילת כפתורים בזמן ריצה; כפתור עצור מוצג רק בזמן ריצה
  document.getElementById("run").disabled = !!s.running;
  document.getElementById("policy-last").textContent = fmt(s.policyLastRun);
  document.getElementById("policy-docs").textContent = s.policyLastDocs ?? "—";
  document.getElementById("policy-progress").textContent = s.policyProgress || "";
  document.getElementById("policy-err").textContent = (s.policyErrors || []).join(" | ");
  document.getElementById("backfill").disabled = !!s.running;
  document.getElementById("sync-local").disabled = !!s.running;
  document.getElementById("stop").hidden = !s.running;
  if (s.running && s.progress) document.getElementById("msg").textContent = s.progress;
  if (!s.running && s.stopped) document.getElementById("msg").textContent = s.progress || "נעצר";
}

// עדכון חי של הפופאפ כל עוד הוא פתוח (הריצה עצמה ממשיכה ברקע בכל מקרה)
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes.status || changes.dashboard)) render();
});

function busy(on, text) {
  document.getElementById("run").disabled = on;
  document.getElementById("backfill").disabled = on;
  document.getElementById("sync-local").disabled = on;
  const stop = document.getElementById("stop");
  stop.hidden = !on;
  stop.disabled = false;
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

document.getElementById("sync-local").addEventListener("click", () => {
  busy(true, "שומר עותק מקומי מ-git...");
  chrome.runtime.sendMessage({ type: "sync-local" }, async () => {
    busy(false, "הסנכרון המקומי הסתיים");
    await render();
    setTimeout(() => (document.getElementById("msg").textContent = ""), 3000);
  });
});

document.getElementById("stop").addEventListener("click", () => {
  document.getElementById("stop").disabled = true;
  document.getElementById("msg").textContent = "עוצר...";
  chrome.runtime.sendMessage({ type: "stop" });
});

document.getElementById("setup").addEventListener("click", () => chrome.runtime.openOptionsPage());

render();
// רענון יזום כל שנייה כל עוד הפופאפ פתוח - מבטיח שהפאי מתעדכן חי גם אם אירוע
// storage.onChanged מתעכב בזמן שה-service worker עסוק.
setInterval(render, 1000);

document.getElementById("run-policy").addEventListener("click", () => {
  document.getElementById("msg").textContent = "מושך מסמכי מדיניות מהאתרים החסומים...";
  chrome.runtime.sendMessage({ type: "run-policy" }, () => {
    document.getElementById("msg").textContent = "הסתיים - ראה סיכום למעלה";
    render();
  });
});
