"""בניית הטבלה הראשית: שורה למסלול (מפתח), נתוני tracks + טורים שנוספים גליון-גליון.

הרצה: python -m funds_holdings.main [--reports-dir reports] [--out out/master.json]
"""
import argparse
import json
from pathlib import Path

from .file_list import get_file_list
from .interest import build_interest
from .sheet_source import build_source
from .tracks_reference import fetch_tracks, track_key


def build_master_table(reports_dir: Path, tracks: list[dict]) -> list[dict]:
    files = get_file_list(reports_dir)
    source = build_source(files)
    interest = build_interest(source)

    rows: dict[str, dict] = {}
    for t in tracks:
        key = track_key(t)
        if key is None:
            continue
        rows[key] = dict(t)
        rows[key]["מפתח"] = key

    for key, has_interest in interest.items():
        row = rows.setdefault(key, {"מפתח": key})
        row["ריבית"] = "ריבית" if has_interest else None

    return list(rows.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--out", type=Path, default=Path("out/master.json"))
    args = ap.parse_args()

    tracks = fetch_tracks()
    print(f"[main] {len(tracks)} מסלולים מ-tracks")

    master = build_master_table(args.reports_dir, tracks)
    print(f"[main] {len(master)} שורות בטבלה הראשית")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    print(f"[main] נשמר -> {args.out}")


if __name__ == "__main__":
    main()
