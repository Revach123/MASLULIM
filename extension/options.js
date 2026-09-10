async function load() {
  const { config } = await chrome.storage.local.get("config");
  if (!config) return;
  document.getElementById("owner").value = config.owner || "";
  document.getElementById("repo").value = config.repo || "";
  document.getElementById("branch").value = config.branch || "main";
  document.getElementById("token").value = config.token || "";
}

document.getElementById("save").addEventListener("click", async () => {
  const msg = document.getElementById("msg");
  const config = {
    owner: document.getElementById("owner").value.trim(),
    repo: document.getElementById("repo").value.trim(),
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
