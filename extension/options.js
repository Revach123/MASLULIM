const DEFAULTS = { owner: "Revach123", repo: "MASLULIM", branch: "main" };

async function load() {
  const { config: saved } = await chrome.storage.local.get("config");
  const config = saved || {};
  document.getElementById("owner").value = config.owner || DEFAULTS.owner;
  document.getElementById("repo").value = config.repo || DEFAULTS.repo;
  document.getElementById("branch").value = config.branch || DEFAULTS.branch;
  document.getElementById("token").value = config.token || "";
}

document.getElementById("save").addEventListener("click", async () => {
  const msg = document.getElementById("msg");
  const config = {
    owner: document.getElementById("owner").value.trim() || DEFAULTS.owner,
    repo: document.getElementById("repo").value.trim() || DEFAULTS.repo,
    branch: document.getElementById("branch").value.trim() || "main",
    token: document.getElementById("token").value.replace(/\s+/g, ""),
  };
  if (!config.owner || !config.repo || !config.token) {
    msg.textContent = "יש למלא owner, repo וטוקן.";
    msg.className = "err";
    return;
  }
  msg.textContent = "בודק חיבור...";
  msg.className = "";
  chrome.runtime.sendMessage({ type: "verify", config }, async (resp) => {
    if (resp && resp.ok) {
      await chrome.storage.local.set({ config });
      msg.textContent = "נשמר בהצלחה. החיבור ל-repo תקין ✓";
      msg.className = "ok";
    } else {
      msg.textContent = "החיבור נכשל: " + (resp?.error || "שגיאה לא ידועה");
      msg.className = "err";
    }
  });
});

load();
