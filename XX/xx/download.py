from __future__ import annotations

import csv
import re
from pathlib import Path

import requests

from .search import Image


def safe_name(img: Image) -> str:
    base = re.sub(r"[^\w\-]+", "_", img.title, flags=re.UNICODE).strip("_")[:60] or "image"
    return f"{base}_{img.id[:8]}.{img.filetype}"


def download(images: list[Image], dest: Path, session: requests.Session | None = None) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    s = session or requests.Session()
    paths: list[Path] = []
    for img in images:
        p = dest / safe_name(img)
        try:
            r = s.get(img.url, timeout=60)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"דילוג על {img.url}: {e}")
            continue
        p.write_bytes(r.content)
        paths.append(p)
    write_credits(images, dest / "credits.csv")
    return paths


def write_credits(images: list[Image], path: Path) -> None:
    """קובץ ייחוס (יוצר + רישיון) - חובה ברוב רישיונות CC."""
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "title", "creator", "license", "license_url", "source_page", "attribution"])
        for i in images:
            w.writerow([safe_name(i), i.title, i.creator, i.license, i.license_url, i.source_page, i.attribution])
