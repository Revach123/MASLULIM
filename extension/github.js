// עבודה מול GitHub REST API: קריאת ה-manifest הקיים ודחיפת קבצים חדשים
// כ-commit אחד (Git Data API: blobs -> tree -> commit -> ref), כדי שגם משיכה
// ראשונית של הרבה קבצים תיווצר כ-commit מסודר אחד ולא מאות.

const API = "https://api.github.com";

function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

async function gh(token, method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { ...authHeaders(token), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const err = new Error(`GitHub ${method} ${path} -> HTTP ${res.status}: ${text.slice(0, 200)}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function verifyRepo(token, owner, repo) {
  return gh(token, "GET", `/repos/${owner}/${repo}`);
}

// מחזיר את תוכן הקובץ מהרפו כ-base64 (לשחזור עותק מקומי מהארכיון).
export async function getFileBase64(token, owner, repo, branch, path) {
  const encPath = path.split("/").map(encodeURIComponent).join("/");
  const data = await gh(token, "GET", `/repos/${owner}/${repo}/contents/${encPath}?ref=${encodeURIComponent(branch)}`);
  if (data.content) return data.content.replace(/\n/g, "");
  if (data.sha) {
    const blob = await gh(token, "GET", `/repos/${owner}/${repo}/git/blobs/${data.sha}`);
    return (blob.content || "").replace(/\n/g, "");
  }
  throw new Error(`no content for ${path}`);
}

// קורא את manifest.json מהרפו; אם לא קיים - מחזיר ריק.
export async function readManifest(token, owner, repo, branch) {
  const res = await fetch(`${API}/repos/${owner}/${repo}/contents/manifest.json?ref=${encodeURIComponent(branch)}`, {
    headers: authHeaders(token),
  });
  if (res.status === 404) return { documents: {} };
  if (!res.ok) throw new Error(`readManifest HTTP ${res.status}`);
  const data = await res.json();
  const json = decodeURIComponent(escape(atob(data.content.replace(/\n/g, ""))));
  try {
    const parsed = JSON.parse(json);
    if (!parsed.documents) parsed.documents = {};
    return parsed;
  } catch {
    return { documents: {} };
  }
}

// files: [{ path, base64 }]  (base64 של תוכן בינארי או טקסט מקודד base64)
// יוצר commit אחד עם כל הקבצים על הענף branch.
export async function commitFiles(token, owner, repo, branch, files, message) {
  if (files.length === 0) return { committed: 0 };

  // 1) ref נוכחי של הענף (אם קיים)
  let baseCommitSha = null;
  let baseTreeSha = null;
  const refRes = await fetch(`${API}/repos/${owner}/${repo}/git/ref/heads/${encodeURIComponent(branch)}`, {
    headers: authHeaders(token),
  });
  if (refRes.ok) {
    const ref = await refRes.json();
    baseCommitSha = ref.object.sha;
    const commit = await gh(token, "GET", `/repos/${owner}/${repo}/git/commits/${baseCommitSha}`);
    baseTreeSha = commit.tree.sha;
  } else if (refRes.status !== 404 && refRes.status !== 409) {
    throw new Error(`get ref HTTP ${refRes.status}`);
  }

  // 2) blob לכל קובץ
  const treeEntries = [];
  for (const f of files) {
    const blob = await gh(token, "POST", `/repos/${owner}/${repo}/git/blobs`, {
      content: f.base64,
      encoding: "base64",
    });
    treeEntries.push({ path: f.path, mode: "100644", type: "blob", sha: blob.sha });
  }

  // 3) tree חדש
  const treeBody = { tree: treeEntries };
  if (baseTreeSha) treeBody.base_tree = baseTreeSha;
  const tree = await gh(token, "POST", `/repos/${owner}/${repo}/git/trees`, treeBody);

  // 4) commit
  const commitBody = { message, tree: tree.sha };
  if (baseCommitSha) commitBody.parents = [baseCommitSha];
  const newCommit = await gh(token, "POST", `/repos/${owner}/${repo}/git/commits`, commitBody);

  // 5) הזזת/יצירת ה-ref
  if (baseCommitSha) {
    await gh(token, "PATCH", `/repos/${owner}/${repo}/git/refs/heads/${encodeURIComponent(branch)}`, {
      sha: newCommit.sha,
      force: false,
    });
  } else {
    await gh(token, "POST", `/repos/${owner}/${repo}/git/refs`, {
      ref: `refs/heads/${branch}`,
      sha: newCommit.sha,
    });
  }

  return { committed: files.length, commitSha: newCommit.sha };
}
