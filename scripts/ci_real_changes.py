# -*- coding: utf-8 -*-
"""
האם יש בשינויים שב-staging (git add) שינוי אמיתי, או רק נתוני-ריצה של הסריקה?

מופעל לפני commit בסריקות היומיות (policy_sites.yml, returns_sites.yml).
יציאה 0 = יש שינוי אמיתי (לעשות commit); יציאה 1 = רק נתוני ריצה (לא לעשות commit).

נתוני ריצה = מה שמשתנה בכל סריקה גם כשלא השתנה אף מסמך:
  * קבצים: crawl_report.*, discovered.json, site_snapshot.json / site_snapshot/,
    coverage.csv, gaps*.csv, run.json
  * שדות בתוך JSON: last_seen, via, run, taken, seconds, visited_since
כל שינוי אחר (מסמך חדש/שונה, sha, טבלאות התשואות/המדיניות וכו') = שינוי אמיתי.
"""
import json
import os
import re
import subprocess
import sys

META_FILE = re.compile(r"(^|/)(crawl_report\.(json|csv)|discovered\.json|site_snapshot\.json|coverage\.csv|gaps[^/]*\.csv|run\.json)$"
                       r"|(^|/)site_snapshot/")
BASE = os.environ.get("CI_BASE", "HEAD")       # לבדיקה מול commit אחר; בריצה - HEAD
VOLATILE = {"last_seen", "via", "run", "taken", "seconds", "visited_since"}


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8").stdout


def strip(o):
    if isinstance(o, dict):
        out = {k: strip(v) for k, v in o.items() if k not in VOLATILE}
        # history חוזר על אותה גרסה (אותו sha256) בכל סריקה - משווים לפי הגרסאות השונות בלבד
        if isinstance(out.get("history"), list):
            out["history"] = sorted({json.dumps(h, sort_keys=True, ensure_ascii=False) for h in out["history"]})
        return out
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o


def load(spec):
    txt = subprocess.run(["git", "show", spec], capture_output=True, text=True, encoding="utf-8")
    if txt.returncode != 0:
        return None
    try:
        return json.loads(txt.stdout)
    except ValueError:
        return txt.stdout


def main():
    files = [l for l in git("diff", "--cached", "--name-only", BASE).splitlines() if l]
    real = []
    for f in files:
        if META_FILE.search(f):
            continue
        if f.endswith(".json"):
            a, b = load(f"{BASE}:{f}"), load(f":{f}")    # לפני / אחרי (staged)
            if a is not None and b is not None and strip(a) == strip(b):
                continue
        real.append(f)
    if real:
        print(f"real changes in {len(real)} file(s): " + ", ".join(real[:8]) + (" ..." if len(real) > 8 else ""))
        return 0
    print(f"only scan metadata changed ({len(files)} file(s)) - no commit")
    return 1


if __name__ == "__main__":
    sys.exit(main())
