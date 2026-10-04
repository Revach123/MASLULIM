"""סריקה מהמחשב הביתי - תחליף לתוסף ה-Chrome לאתרים שחוסמים שרתי ענן (Cloudflare / חסימת חו"ל).

רץ על GitHub self-hosted runner (Windows) בריפו פרטי, ומשם דוחף לריפו הזה רק קבצים חדשים ל-policy/inbox/<LegalId>/ -
בדיוק כמו התוסף. הקליטה, הפענוח והצירוף ממשיכים כרגיל ב-workflow של ה-inbox בענן.

לכל אתר: crawl.py רץ לתיקייה זמנית (policy/_home/<LegalId>) שמתחילה מה-docs_index הקיים - קבצים שכבר נאספו
לא מורדים שוב (POLICY_TRUST_INDEX). כל קובץ חדש נכתב ל-inbox עם קובץ meta (url, link_text, source_page, sha256,
last_modified, via=home). יומן לכל אתר: policy/extension_log/home/<מועד>.json - להשוואה מול התוסף.

הרצה: python -m scripts.policy.home_crawl [--only LEGAL_ID ...] [--timeout-min 40]
"""
import argparse, json, os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POL = ROOT / "policy"
SITES = Path(__file__).with_name("sites")


def home_sites(only):
    out = []
    for p in sorted(SITES.glob("*.json")):
        c = json.loads(p.read_text("utf-8"))
        if (only and c["legal_id"] in only) or (not only and c.get("via") == "extension"):
            out.append(c)
    return out


def run_site(c, timeout_min):
    lid = c["legal_id"]
    work = POL / "_home" / lid
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    idx_src = POL / "companies" / lid / "docs_index.json"
    before = json.loads(idx_src.read_text("utf-8")) if idx_src.exists() else {}
    (work / "docs_index.json").write_text(json.dumps(before, ensure_ascii=False), "utf-8")
    env = dict(os.environ, POLICY_OUT=str(work.relative_to(ROOT)), POLICY_FORCE_CLOUD="1", POLICY_TRUST_INDEX="1")
    env.setdefault("POLICY_HEADED", "1")
    t0 = datetime.now(timezone.utc)
    try:
        p = subprocess.run([sys.executable, "-m", "scripts.policy.crawl", "--only", lid], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_min * 60)
        log, code = (p.stdout + p.stderr)[-3000:], p.returncode
    except subprocess.TimeoutExpired as e:
        log, code = f"timeout after {timeout_min} min\n" + str(e.stdout or "")[-2000:], "timeout"
    after = json.loads((work / "docs_index.json").read_text("utf-8")) if (work / "docs_index.json").exists() else {}
    new = []
    for url, ent in after.items():
        if before.get(url, {}).get("sha256") == ent.get("sha256") or not ent.get("file"):
            continue
        src = ROOT / ent["file"]
        if not src.exists():
            continue
        dst = POL / "inbox" / lid / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        meta = {"legal_id": lid, "url": url, "link_text": ent.get("link_text"), "source_page": ent.get("source_page"),
                "sha256": ent["sha256"], "fetched_at": ent.get("last_seen") or t0.isoformat(timespec="seconds"),
                "via": "home"}
        if ent.get("last_modified"):
            meta["last_modified"] = ent["last_modified"]
        Path(str(dst) + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        new.append(url)
    shutil.rmtree(work, ignore_errors=True)
    status = "ok" if code == 0 else f"exit {code}"
    blocked = any(s in log for s in ("status=403", "Cloudflare", "you have been blocked", "בגלישה מחו"))
    return {"legal_id": lid, "name": c["name"], "status": status, "blocked": blocked, "new_docs": len(new),
            "known_docs": len(before), "seconds": int((datetime.now(timezone.utc) - t0).total_seconds()),
            "new": new[:50], "log_tail": log[-1200:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--timeout-min", type=int, default=40)
    a = ap.parse_args()
    started = datetime.now(timezone.utc)
    results = []
    for c in home_sites(a.only):
        r = run_site(c, a.timeout_min)
        results.append(r)
        print(f"[{r['legal_id']}] {r['name'][:30]}: {r['status']} new={r['new_docs']}"
              f"{' BLOCKED' if r['blocked'] else ''} ({r['seconds']}s)", flush=True)
    logd = POL / "extension_log" / "home"
    logd.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y-%m-%dT%H-%M-%S")
    (logd / f"{stamp}.json").write_text(json.dumps({"started": started.isoformat(timespec="seconds"), "sites": results},
                                                   ensure_ascii=False, indent=1), "utf-8")
    print(f"sites={len(results)} new_docs={sum(r['new_docs'] for r in results)} "
          f"blocked={sum(r['blocked'] for r in results)}")


if __name__ == "__main__":
    main()
