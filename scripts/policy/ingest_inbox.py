"""קליטת קבצים שהתוסף דחף ל-policy/inbox/<LegalId>/ (אתרים שחוסמים שרתי ענן).

לכל קובץ יש צמד <name>.json עם url/link_text/source_page/sha256/fetched_at. הקובץ עובר ל-
policy/companies/<LegalId>/raw/<LegalId>/, נרשם ב-docs_index.json של החברה (אותו מבנה כמו crawl.py),
ונמחק מה-inbox. אחר כך ה-workflow מריץ extract לחברה ו-combine.
הרצה: python -m scripts.policy.ingest_inbox   -> מדפיס את רשימת החברות שנקלטו (לשורת פקודה הבאה).
"""
import json, shutil
from pathlib import Path

from .crawl import sniff_ext

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "policy" / "inbox"
DOC_EXTS = {".xlsx", ".xls", ".pdf", ".docx", ".htm", ".html", ".doc", ".csv"}


def main():
    touched = []
    for d in sorted(p for p in INBOX.iterdir() if p.is_dir()) if INBOX.exists() else []:
        lid = d.name
        comp = ROOT / "policy" / "companies" / lid
        idx_path = comp / "docs_index.json"
        index = json.loads(idx_path.read_text("utf-8")) if idx_path.exists() else {}
        for meta_p in sorted(d.glob("*.json")):
            f = meta_p.with_suffix("")  # "<name>.json" -> "<name>"
            if not f.exists():
                continue
            meta = json.loads(meta_p.read_text("utf-8"))
            dest = comp / "raw" / lid / f.name
            if dest.suffix.lower() not in DOC_EXTS:  # שם ארוך שנחתך בתוסף ("...-(עד-25-אחוז-מניות)-867") - הסיומת לפי התוכן
                dest = dest.with_name(dest.name + (sniff_ext(f.read_bytes()[:400000]) or ""))
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), dest)
            meta_p.unlink()
            prev = index.get(meta["url"], {})
            hist = prev.get("history", [])
            if prev.get("sha256") and prev["sha256"] != meta["sha256"]:
                hist.append({"sha256": prev["sha256"], "file": prev.get("file"), "last_seen": prev.get("last_seen")})
            index[meta["url"]] = {"legal_id": lid, "first_seen": prev.get("first_seen", meta["fetched_at"]),
                                  "last_seen": meta["fetched_at"], "file": str(dest.relative_to(ROOT)),
                                  "sha256": meta["sha256"], "size": dest.stat().st_size, "parsed_sha": None,
                                  "history": hist, "link_text": meta.get("link_text"),
                                  "source_page": meta.get("source_page"), "via": "extension"}
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
        if not any(d.iterdir()):
            d.rmdir()
        touched.append(lid)
    print(" ".join(touched))


if __name__ == "__main__":
    main()
