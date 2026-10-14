"""מרכיבי תשואה מהמחשב הביתי - לאתרים שחוסמים שרתי ענן (via=extension), כמו scripts/policy/home_crawl.py.

רץ על ה-runner הביתי (Revach: .github/workflows/policy-home.yml) אחרי סריקת המדיניות. לכל אתר: scripts.returns.crawl לתיקייה
זמנית (returns/_home/<LegalId>) שמתחילה מה-docs_index הקיים - קבצים שכבר נאספו לא נשלחים שוב. כל קובץ חדש נכתב ל-
policy/inbox/<LegalId>/returns/ עם קובץ meta - נדחף יחד עם תיבת המדיניות, ונקלט ב-policy_inbox.yml (scripts.returns.ingest).
הרצה: python -m scripts.returns.home [--only LEGAL_ID ...] [--timeout-min 75]
      [--push] [--state FILE] [--cycle-file FILE] [--max-minutes N]

המחשב הביתי נפתח לפרקים קצרים (חצי דקה עד חצי שעה), ולכן ריצה של כל האתרים ברצף לא מסתיימת ומה שהורד אובד. אופציונלי:
  --push         אחרי כל אתר: דחיפה מיידית של מה שירד ל-origin/main (policy/inbox/<ח.פ.>/returns), בלי לחכות לסוף הריצה
  --state FILE   קובץ JSON (מחוץ למאגר) עם זמן הניסיון האחרון לכל אתר: האתרים נסרקים לפי הסדר "הכי ישן קודם"
  --cycle-file F קובץ עם זמן סיום המחזור הקודם (returns-last-ok.txt): רק אתרים שלא נוסו מאז נסרקים - ריצה שנקטעה ממשיכה
                 מהאתרים שנשארו; כשכולם נוסו הריצה מסתיימת מיד (והמחזור מסומן כגמור ב-workflow)
  --max-minutes  תקרת זמן כוללת: אחרי שעוברים אותה לא מתחילים אתר נוסף (היציאה תקינה; האתרים שנשארו - בריצה הבאה)
בלי הדגלים האלה ההתנהגות כמו קודם. עם --only הסינון לפי מחזור/מצב לא חל.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITES = ROOT / "scripts" / "policy" / "sites"
RET = ROOT / "returns"
LOW_PRIORITY = 0x00004000 if os.name == "nt" else 0  # Windows BELOW_NORMAL_PRIORITY_CLASS


def _now_local():
    return datetime.now().isoformat(timespec="seconds")  # אותו פורמט כמו Get-Date -Format s ב-workflow


def _read_ts(path):
    """זמן מקובץ (שורה ראשונה) כמחרוזת ISO; None אם אין/ריק."""
    try:
        t = Path(path).read_text("utf-8-sig").strip().splitlines()
        return t[0].strip() if t and t[0].strip() else None
    except OSError:
        return None


def load_state(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)


def order_sites(ids, state, cycle_ts=None):
    """האתרים לסריקה: אם יש cycle_ts - רק אלה שלא נוסו מאז; הכי ישן (או שלא נוסה מעולם) קודם. ISO באותו פורמט - השוואת מחרוזות."""
    todo = [i for i in ids if not (cycle_ts and state.get(i) and state[i] > cycle_ts)]
    return sorted(todo, key=lambda i: (state.get(i) or "", i))


def _git(*args, check=False):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def push_site(lid, n_files, retries=6, sleep=time.sleep):
    """דוחף את policy/inbox/<lid>/returns ל-origin/main (אותה לוגיקה כמו שלב ה-Push ב-returns-home.yml, רק לאתר אחד).
    מחזיר True אם נדחף או שאין מה לדחוף, False אחרי כל הניסיונות."""
    src = ROOT / "policy" / "inbox" / lid / "returns"
    if not src.exists():
        return True
    keep = Path(tempfile.mkdtemp(prefix="returns-home-keep-")) / "returns"
    shutil.copytree(src, keep)
    try:
        for i in range(1, retries + 1):
            _git("fetch", "-q", "--depth", "1", "origin", "main")
            _git("reset", "-q", "--hard", "origin/main")
            shutil.copytree(keep, src, dirs_exist_ok=True)
            rel = f"policy/inbox/{lid}/returns"
            _git("add", "--sparse", "--", rel)
            if _git("diff", "--cached", "--quiet").returncode == 0:
                print(f"[{lid}] push: nothing staged (already on main)", flush=True)
                return True
            _git("-c", "user.name=policy-home", "-c", "user.email=policy-home@users.noreply.github.com",
                 "commit", "-q", "-m", f"returns inbox (home runner): {n_files} files [{lid}]")
            r = _git("push", "-q", "origin", "HEAD:main")
            if r.returncode == 0:
                print(f"[{lid}] pushed {n_files} files", flush=True)
                shutil.rmtree(src, ignore_errors=True)  # כבר ב-main; לא לדחוף שוב עם האתר הבא
                return True
            print(f"[{lid}] push failed (attempt {i}): {(r.stderr or '').strip()[-200:]}", flush=True)
            sleep(5 * i)
        return False
    finally:
        shutil.rmtree(keep.parent, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--timeout-min", type=int, default=75)
    ap.add_argument("--push", action="store_true", help="דחיפה מיידית אחרי כל אתר")
    ap.add_argument("--state", help="קובץ JSON עם זמן הניסיון האחרון לכל אתר (סדר 'הכי ישן קודם')")
    ap.add_argument("--cycle-file", help="זמן סיום המחזור הקודם: רק אתרים שלא נוסו מאז נסרקים")
    ap.add_argument("--max-minutes", type=int, default=0, help="תקרת זמן כוללת (0 = בלי תקרה)")
    a = ap.parse_args()
    t0 = time.monotonic()
    known = set()
    for p in (RET / "companies").glob("*/docs_index.json"):
        known |= {e.get("sha256") for e in json.loads(p.read_text("utf-8")).values()}
    total = 0
    cfgs = {}
    for p in sorted(SITES.glob("*.json")):
        c = json.loads(p.read_text("utf-8"))
        lid = c["legal_id"]
        if (a.only and lid not in a.only) or (not a.only and c.get("via") != "extension"):
            continue
        if c.get("returns_skip_home") and not a.only:  # אתר שחסום גם בדפדפן הביתי (למשל ShieldSquare) - לא מבזבזים עליו 30 דקות בכל ריצה
            print(f"[{lid}] skipped (returns_skip_home): {c['returns_skip_home']}", flush=True)
            continue
        cfgs[lid] = c
    state = load_state(a.state) if a.state else {}
    order = list(cfgs)
    if not a.only and (a.state or a.cycle_file):
        cycle_ts = _read_ts(a.cycle_file) if a.cycle_file else None
        order = order_sites(order, state, cycle_ts)
        print(f"sites to crawl in this cycle: {len(order)} of {len(cfgs)}" + (f" (cycle since {cycle_ts})" if cycle_ts else ""), flush=True)
    for lid in order:
        if a.max_minutes and time.monotonic() - t0 > a.max_minutes * 60:
            print(f"time budget {a.max_minutes} min reached - remaining sites next run", flush=True)
            break
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
        # תקציב ההורדות נמדד מתחילת הסריקה (ברירת מחדל 2000s) - כשסריקת העמודים לבדה לוקחת יותר (מור: 46 עמודי מסלול, 2600s) לא יורד כלום
        env.setdefault("RETURNS_DL_BUDGET", str(max(2000, (a.timeout_min - 8) * 60)))
        env.setdefault("PYTHONUNBUFFERED", "1")  # הפלט החלקי בלוג גם כשהסריקה נהרגת בתקרה
        log = work / "crawl.log"
        # פלט לקובץ (לא pipe) וסיום עץ התהליכים בתקרה: subprocess.run(timeout, capture_output) נתקע ב-Windows אחרי kill כי Chrome (נכד)
        # מחזיק את ה-pipe פתוח - הסריקה של עגור רצתה 41 דקות במקום 30
        with open(log, "wb") as lf:
            p = subprocess.Popen([sys.executable, "-m", "scripts.returns.crawl", "--only", lid], cwd=ROOT, env=env,
                                 creationflags=LOW_PRIORITY, stdout=lf, stderr=subprocess.STDOUT)
            timed_out = False
            try:
                p.wait(timeout=a.timeout_min * 60)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                else:
                    p.kill()
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
        out = log.read_text("utf-8", errors="replace") if log.exists() else ""
        print((f"[{lid}] timeout after {a.timeout_min} min (killed)\n" if timed_out else "") + out[-1500 if timed_out else -600:], flush=True)
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
        snap = work / "site_snapshot.json"
        if snap.exists() and snap.stat().st_size < 6_000_000:  # לאבחון: אילו עמודים נסרקו ומה היה בהם
            dst = ROOT / "policy" / "inbox" / lid / "returns" / "_snapshot.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snap, dst)
        shutil.rmtree(work, ignore_errors=True)
        total += n
        print(f"[{lid}] returns new={n}", flush=True)
        if a.push:
            push_site(lid, n)
        if a.state and not a.only:  # רק אחרי שהאתר נוסה (גם אם פג זמנו - הוא ממשיך מ-discovered.json ביום הבא)
            state[lid] = _now_local()
            save_state(a.state, state)
    print(f"returns home: new files={total}")


if __name__ == "__main__":
    main()
