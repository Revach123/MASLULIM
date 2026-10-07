"""מרכיבי תשואה מהמחשב הביתי - לאתרים שחוסמים שרתי ענן (via=extension), כמו scripts/policy/home_crawl.py.

רץ על ה-runner הביתי (Revach: .github/workflows/policy-home.yml) אחרי סריקת המדיניות. לכל אתר: scripts.returns.crawl לתיקייה
זמנית (returns/_home/<LegalId>) שמתחילה מה-docs_index הקיים - קבצים שכבר נאספו לא נשלחים שוב. כל קובץ חדש נכתב ל-
policy/inbox/<LegalId>/returns/ עם קובץ meta - נדחף יחד עם תיבת המדיניות, ונקלט ב-policy_inbox.yml (scripts.returns.ingest).
הרצה: python -m scripts.returns.home [--only LEGAL_ID ...] [--timeout-min 30]
"""
import argparse, json, os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITES = ROOT / "scripts" / "policy" / "sites"
RET = ROOT / "returns"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--timeout-min", type=int, default=30)
    a = ap.parse_args()
    known = set()
    for p in (RET / "companies").glob("*/docs_index.json"):
        known |= {e.get("sha256") for e in json.loads(p.read_text("utf-8")).values()}
    total = 0
    for p in sorted(SITES.glob("*.json")):
        c = json.loads(p.read_text("utf-8"))
        lid = c["legal_id"]
        if (a.only and lid not in a.only) or (not a.only and c.get("via") != "extension"):
            continue
        work = RET / "_home" / lid
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        src_idx = RET / "companies" / lid / "docs_index.json"
        before = json.loads(src_idx.read_text("utf-8")) if src_idx.exists() else {}
        (work / "docs_index.json").write_text(json.dumps(before, ensure_ascii=False), "utf-8")
        for f in ("discovered.json",):
            if (RET / "companies" / lid / f).exists():
                shutil.copyfile(RET / "companies" / lid / f, work / f)
        env = dict(os.environ, RETURNS_OUT=str(work), RETURNS_FORCE_CLOUD="1")
        env.setdefault("POLICY_HEADED", "1")
        env.setdefault("POLICY_OFFSCREEN", "1")
        try:
            r = subprocess.run([sys.executable, "-m", "scripts.returns.crawl", "--only", lid], cwd=ROOT, env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=a.timeout_min * 60)
            print((r.stdout + r.stderr)[-600:], flush=True)
        except subprocess.TimeoutExpired:
            print(f"[{lid}] timeout", flush=True)
        after = json.loads((work / "docs_index.json").read_text("utf-8")) if (work / "docs_index.json").exists() else {}
        n = 0
        for url, ent in after.items():
            if before.get(url, {}).get("sha256") == ent.get("sha256") or ent.get("sha256") in known or not ent.get("file"):
                continue
            f = ROOT / ent["file"] if not Path(ent["file"]).is_absolute() else Path(ent["file"])
            if not f.exists():
                continue
            dst = ROOT / "policy" / "inbox" / lid / "returns" / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
            meta = {"legal_id": lid, "url": url, "link_text": ent.get("link_text"), "source_page": ent.get("source_page"),
                    "sha256": ent["sha256"], "fetched_at": ent.get("last_seen") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "last_modified": ent.get("last_modified"), "via": "home", "kind": "returns"}
            Path(str(dst) + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
            known.add(ent["sha256"])
            n += 1
        disc = work / "discovered.json"
        if disc.exists():  # עמודים שנמצאו - נשלחים כדי שהריצה הבאה תתחיל מהם
            dst = ROOT / "policy" / "inbox" / lid / "returns" / "_discovered.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(disc, dst)
        shutil.rmtree(work, ignore_errors=True)
        total += n
        print(f"[{lid}] returns new={n}", flush=True)
    print(f"returns home: new files={total}")


if __name__ == "__main__":
    main()
