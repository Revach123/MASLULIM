"""חיפוש תמונות ב-Openverse (ללא מפתח API; תמונות ברישיון פתוח)."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import requests

API = "https://api.openverse.org/v1/images/"


@dataclass
class Image:
    id: str
    title: str
    url: str
    creator: str
    license: str
    license_version: str
    license_url: str
    source_page: str
    width: int | None
    height: int | None
    filetype: str

    @property
    def attribution(self) -> str:
        lic = f"CC {self.license.upper()} {self.license_version}".strip()
        return f'"{self.title}" by {self.creator or "unknown"} ({lic}) - {self.source_page}'

    def as_dict(self) -> dict:
        return {**asdict(self), "attribution": self.attribution}


def parse(item: dict) -> Image:
    return Image(
        id=item["id"],
        title=item.get("title") or "untitled",
        url=item["url"],
        creator=item.get("creator") or "",
        license=item.get("license") or "",
        license_version=item.get("license_version") or "",
        license_url=item.get("license_url") or "",
        source_page=item.get("foreign_landing_url") or "",
        width=item.get("width"),
        height=item.get("height"),
        filetype=(item.get("filetype") or "jpg").lower(),
    )


def search(
    query: str,
    limit: int = 20,
    commercial: bool = True,
    min_width: int = 0,
    session: requests.Session | None = None,
) -> list[Image]:
    """מחזיר עד `limit` תמונות. commercial=True מסנן לרישיונות שמותרים לשימוש מסחרי."""
    s = session or requests.Session()
    params = {
        "q": query,
        "page_size": min(max(limit, 1), 20),
        "mature": "false",
    }
    if commercial:
        params["license_type"] = "commercial,modification"
    out: list[Image] = []
    page = 1
    while len(out) < limit:
        params["page"] = page
        r = s.get(API, params=params, timeout=30)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            break
        for item in results:
            img = parse(item)
            if min_width and (img.width or 0) < min_width:
                continue
            out.append(img)
            if len(out) >= limit:
                break
        page += 1
        if page > 10:
            break
    return out
