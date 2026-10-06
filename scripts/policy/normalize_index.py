"""ניקוי חד-פעמי (אפשר להריץ שוב) של docs_index.json לכל החברות:
1. אותה כתובת בשתי צורות (התוסף שמר מקודד %D7%9E..., הסריקה בענן קריא) - רשומה אחת: המפתח הקריא,
   הכיתוב הגלוי הטוב מבין השתיים, first_seen המוקדם, last_seen ו-last_modified הקיימים. השורות של הכפילות
   יוצאות בפרסור הבא (extract מוחק שורות של כתובת שלא באינדקס).
   כתובת הורדה חתומה (מגדל/Wix, token חדש בכל סריקה) - בלי ה-token (crawl.doc_key).
2. הכיתוב העדכני מתמונת האתר האחרונה (site_snapshot), כשהוא עדיף על השמור (תאריך מלא במקום שנה בלבד).
3. כתובת הורדה חתומה (מגדל/Wix) עם תווית טכנית - שם הקובץ המקורי מתוך ה-token ("... JUL 2026_P - ACC.xlsx").
הרצה: python -m scripts.policy.normalize_index  -> מדפיס את החברות שהשתנו (לפרסור מחדש).
"""
import json
from pathlib import Path
from urllib.parse import unquote

from scripts.policy.crawl import visible_text_better
from scripts.policy.urlkey import doc_key, wix_id
from scripts.policy.snapshot import signed_url_name

ROOT = Path(__file__).resolve().parents[2]


def merge(a, b):
    """שתי רשומות של אותו קובץ -> אחת (a = המפתח שנשאר)."""
    out = dict(a)
    if b.get("last_seen", "") > a.get("last_seen", "") and b.get("sha256") != a.get("sha256"):
        # הגרסה העדכנית בצד השני - היא הקובץ הנוכחי, הישן להיסטוריה
        out.update({k: b[k] for k in ("file", "sha256", "size", "last_seen") if k in b})
        out["history"] = a.get("history", []) + b.get("history", []) + [
            {"sha256": a.get("sha256"), "file": a.get("file"), "last_seen": a.get("last_seen")}]
        out["parsed_sha"] = None
    else:
        out["last_seen"] = max(a.get("last_seen", ""), b.get("last_seen", ""))
    out["first_seen"] = min(x for x in (a.get("first_seen"), b.get("first_seen")) if x) if a.get("first_seen") or b.get("first_seen") else None
    for k in ("last_modified", "source_page"):
        if not out.get(k) and b.get(k):
            out[k] = b[k]
    if visible_text_better(out.get("link_text"), b.get("link_text")):
        out["link_text"] = b["link_text"]
        out["parsed_sha"] = None
    return out


def main():
    changed = []
    for idx_path in sorted((ROOT / "policy" / "companies").glob("*/docs_index.json")):
        index = json.loads(idx_path.read_text("utf-8"))
        groups = {}
        pub = {wix_id(u): doc_key(u) for u in index if wix_id(u) and "/_files/" in u}  # Wix: הכתובת הציבורית
        for u in index:
            groups.setdefault(pub.get(wix_id(u)) or doc_key(u), []).append(u)
        snap = {}
        for sp in idx_path.parent.glob("site_snapshot/*.json"):
            for pg in json.loads(sp.read_text("utf-8")).get("pages", {}).values():
                for it in pg.get("items", []) if isinstance(pg, dict) else []:
                    h, t = unquote(it.get("href") or ""), (it.get("text") or "").strip()
                    if h and visible_text_better(snap.get(h), t):
                        snap[h] = t
        new, n_merged, n_named, n_snap = {}, 0, 0, 0
        for readable, keys in groups.items():
            keep = readable if readable in keys else keys[0]
            ent = index[keep]
            for k in keys:
                if k != keep:
                    ent = merge(ent, index[k]); n_merged += 1
            signed = next((k for k in keys if signed_url_name(k)), None)
            t = snap.get(readable)
            if t and visible_text_better(ent.get("link_text"), t):
                ent = {**ent, "link_text": t, "parsed_sha": None}; n_snap += 1
            name = signed_url_name(signed) if signed else None
            if name and visible_text_better(ent.get("link_text"), name):
                ent = {**ent, "link_text": name, "parsed_sha": None}; n_named += 1
            if keep != readable:  # המפתח הקבוע (בלי token) - השורות של הכתובת הישנה יוצאות, פרסור מחדש
                ent = {**ent, "parsed_sha": None}
            new[readable] = ent
        if n_merged or n_named or n_snap:
            idx_path.write_text(json.dumps(new, ensure_ascii=False, indent=1), "utf-8")
            changed.append(idx_path.parent.name)
            print(f"{idx_path.parent.name}: merged {n_merged} duplicate urls, {n_named} names from signed urls, {n_snap} texts from site snapshot", flush=True)
    print(" ".join(changed))


if __name__ == "__main__":
    main()
