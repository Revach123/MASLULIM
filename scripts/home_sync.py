"""עזרים משותפים לסריקות של המחשב הביתי (policy-home / returns-home): מצב לכל אתר, סדר "הכי ישן קודם", ודחיפה מיידית ל-origin/main.

המחשב הביתי נפתח לפרקים קצרים (חצי דקה - חצי שעה), לכן אחרי כל אתר דוחפים מה שירד, זוכרים איזה אתר נוסה, ומחזור שנקטע ממשיך
מהאתרים שנשארו. הזמנים בפורמט ISO מקומי (כמו Get-Date -Format s ב-workflow), לכן אפשר להשוות כמחרוזות.
"""
import json, os, shutil, subprocess, tempfile, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def now_local():
    return datetime.now().isoformat(timespec="seconds")


def read_ts(path):
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
    """אם יש cycle_ts - רק אתרים שלא נוסו מאז; הכי ישן (או שלא נוסה מעולם) קודם."""
    todo = [i for i in ids if not (cycle_ts and state.get(i) and state[i] > cycle_ts)]
    return sorted(todo, key=lambda i: (state.get(i) or "", i))


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def push_paths(rel_paths, message, label="", retries=6, sleep=time.sleep):
    """דוחף את הנתיבים (יחסיים לשורש המאגר) ל-origin/main: fetch + reset --hard + החזרת הקבצים + add + commit + push, עם ניסיונות חוזרים
    (אותה לוגיקה כמו שלב ה-Push ב-workflow). נתיב שלא קיים מדולג. מחזיר True אם נדחף או שאין מה לדחוף."""
    rel_paths = [r for r in rel_paths if (ROOT / r).exists()]
    if not rel_paths:
        return True
    keep = Path(tempfile.mkdtemp(prefix="home-sync-keep-"))
    try:
        for r in rel_paths:
            src, dst = ROOT / r, keep / r
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst) if src.is_dir() else shutil.copyfile(src, dst)
        for i in range(1, retries + 1):
            _git("fetch", "-q", "--depth", "1", "origin", "main")
            _git("reset", "-q", "--hard", "origin/main")
            for r in rel_paths:
                src, dst = keep / r, ROOT / r
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst, dirs_exist_ok=True) if src.is_dir() else shutil.copyfile(src, dst)
            _git("add", "--sparse", "--", *rel_paths)
            if _git("diff", "--cached", "--quiet").returncode == 0:
                print(f"[{label}] push: nothing staged (already on main)", flush=True)
                return True
            _git("-c", "user.name=policy-home", "-c", "user.email=policy-home@users.noreply.github.com", "commit", "-q", "-m", message)
            r = _git("push", "-q", "origin", "HEAD:main")
            if r.returncode == 0:
                print(f"[{label}] pushed: {message}", flush=True)
                return True
            print(f"[{label}] push failed (attempt {i}): {(r.stderr or '').strip()[-200:]}", flush=True)
            sleep(5 * i)
        return False
    finally:
        shutil.rmtree(keep, ignore_errors=True)
