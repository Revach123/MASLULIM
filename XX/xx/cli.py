from __future__ import annotations

import argparse
from pathlib import Path

from . import download as dl
from . import search as srch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="xx", description="חיפוש תמונות לעבודות גרפיקה והעלאה ל-Drive")
    ap.add_argument("query", help="מילות חיפוש (עדיף באנגלית)")
    ap.add_argument("-n", "--limit", type=int, default=10)
    ap.add_argument("--min-width", type=int, default=1200, help="רוחב מינימלי בפיקסלים")
    ap.add_argument("--any-license", action="store_true", help="לא לסנן לרישיון מסחרי")
    ap.add_argument("-o", "--out", default="downloads", help="תיקייה מקומית")
    ap.add_argument("--list-only", action="store_true", help="הצג תוצאות בלבד, בלי הורדה")
    ap.add_argument("--drive", action="store_true", help="העלה ל-Google Drive")
    ap.add_argument("--folder-id", help="מזהה תיקיית יעד ב-Drive (אחרת נוצרת תיקייה בשם --folder-name)")
    ap.add_argument("--folder-name", default="XX Images")
    ap.add_argument("--credentials", default="credentials.json")
    a = ap.parse_args(argv)

    images = srch.search(a.query, a.limit, commercial=not a.any_license, min_width=a.min_width)
    if not images:
        print("לא נמצאו תמונות")
        return 1
    for i, img in enumerate(images, 1):
        print(f"{i:>2}. {img.title} [{img.width}x{img.height}] {img.license.upper()} - {img.url}")
    if a.list_only:
        return 0

    out = Path(a.out) / a.query.replace(" ", "_")
    files = dl.download(images, out)
    print(f"הורדו {len(files)} קבצים אל {out}")

    if a.drive:
        from . import drive

        svc = drive.get_service(a.credentials)
        folder = a.folder_id or drive.ensure_folder(svc, a.folder_name)
        drive.upload(svc, files + [out / "credits.csv"], folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
