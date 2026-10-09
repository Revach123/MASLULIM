"""קליטת קבצי מרכיבי תשואה מהמחשב הביתי (policy/inbox/<LegalId>/returns/) ל-returns/companies/<LegalId>/.
הרצה: python -m scripts.returns.ingest  -> מדפיס את רשימת החברות שנקלטו (לשלב הפרסור).
"""
import json, shutil
from pathlib import Path

from scripts.policy.urlkey import find_key

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "policy" / "inbox"


def main():
    touched = []
    for d in sorted(INBOX.glob("*/returns")) if INBOX.exists() else []:
        lid = d.parent.name
        comp = ROOT / "returns" / "companies" / lid
        idx_path = comp / "docs_index.json"
        index = json.loads(idx_path.read_text("utf-8")) if idx_path.exists() else {}
        disc = d / "_discovered.json"
        if disc.exists():
            comp.mkdir(parents=True, exist_ok=True)
            shutil.move(str(disc), comp / "discovered.json")
        for meta_p in sorted(d.glob("*.json")):
            f = meta_p.with_suffix("")
            if not f.exists():
                meta_p.unlink(); continue
            meta = json.loads(meta_p.read_text("utf-8"))
            if any(e.get("sha256") == meta["sha256"] for e in index.values()):
                f.unlink(); meta_p.unlink(); continue
            dest = comp / "raw" / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), dest)
            meta_p.unlink()
            key = find_key(index, meta["url"])
            prev = index.get(key, {})
            index[key] = {"legal_id": lid, "first_seen": prev.get("first_seen", meta["fetched_at"]), "last_seen": meta["fetched_at"],
                          "file": str(dest.relative_to(ROOT)), "sha256": meta["sha256"], "size": dest.stat().st_size,
                          "parsed_sha": None, "link_text": meta.get("link_text"), "source_page": meta.get("source_page"),
                          "via": meta.get("via") or "home", **({"last_modified": meta["last_modified"]} if meta.get("last_modified") else {})}
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
        shutil.rmtree(d, ignore_errors=True)
        if d.parent.exists() and not any(d.parent.iterdir()):
            d.parent.rmdir()
        touched.append(lid)
    print(" ".join(touched))


if __name__ == "__main__":
    main()
