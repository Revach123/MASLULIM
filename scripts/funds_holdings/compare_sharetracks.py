"""השוואה: הרכב המסלולים הידני ב-/sharetracks מול הפירוק האוטומטי לפי מדד.

שורה ב-sharetracks_data = (מוצר, חברה, סוג מסלול) + רשימת מדדים ואחוזים (ידני).
מסלולים מ-out/index_exposure.json מקובצים לאותו מפתח בדיוק כמו בדף
(product = "סוג קרן", company = "שם החברה", SUBTYPE_MAP על "סוג מסלול"),
ושמות המדדים הידניים מתורגמים לאותו אוצר מדדים (index_exposure.classify_index).
ההשוואה היא בחלקים מתוך החשיפה למניות (הידני מסתכם ל-100% מהמניות).

הרצה: python -m scripts.funds_holdings.compare_sharetracks --out-dir out
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import requests

from .index_exposure import classify_index

SHARETRACKS_URL = "https://revach.pages.dev/api/sharetracks"
MATCH_KEY_ENV = "REVACH_MATCH_KEY"
SUBTYPE_MAP = {  # כמו sharetracks/index.html
    "עוקב מדד s&p 500": "sp500", "עוקב מדדי מניות": "mdadim", "מניות סחיר": "sachir",
    "קיימות": "kiyamut", "הלכה": "halacha", "עוקב מדדים - גמיש": "gamiš", "עוקב מדדים גמיש": "gamiš",
}


def _pct(v) -> float | None:
    try:
        return float(str(v).replace("%", "").strip()) / 100
    except (TypeError, ValueError):
        return None


def fetch_sharetracks() -> list[dict]:
    key = (os.environ.get(MATCH_KEY_ENV) or "").strip()
    r = requests.get(SHARETRACKS_URL, headers={"X-Match-Key": key, "Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    return r.json()


def manual_shares(indices: list[dict]) -> dict[str, tuple[str, float]]:
    out: dict[str, list] = {}
    for i in indices or []:
        idx, label = classify_index(i.get("n"))
        p = _pct(i.get("p"))
        if p is None:
            continue
        cur = out.setdefault(idx, [i.get("n"), 0.0])
        cur[1] += p
    return {k: (v[0], v[1]) for k, v in out.items()}


def auto_shares(tracks: list[dict]) -> tuple[dict[str, tuple[str, float]], float]:
    """ממוצע (לפי מסלול) של חלק כל מדד מתוך החשיפה למניות של המסלול."""
    acc: dict[str, list] = {}
    eq = []
    for t in tracks:
        tot = t.get("equity_total") or 0.0
        eq.append(tot)
        if tot <= 0:
            continue
        for e in t["indices"]:
            cur = acc.setdefault(e["id"], [e["label"], 0.0])
            cur[1] += e["pct"] / tot / len(tracks)
    return {k: (v[0], v[1]) for k, v in acc.items()}, (sum(eq) / len(eq) if eq else 0.0)


def compare(share_rows: list[dict], index_table: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    by_num: dict[str, list[dict]] = defaultdict(list)  # ביטוח: לפי מספר מסלול, כמו insuranceCompByNum בדף
    for t in index_table:
        if t.get("product") in ("ביטוח", "ביטוח (ישן)"):
            by_num[str(t.get("track_number") or t["key"].split("_")[1]).strip()].append(t)
        sub = SUBTYPE_MAP.get(str(t.get("track_type") or "").strip().lower())
        if sub:
            groups[(t.get("product"), t.get("company"), sub)].append(t)
    out = []
    for row in share_rows:
        indices = (row.get("data") or {}).get("indices")
        if not isinstance(indices, list) or not indices:
            continue
        key = (row.get("product"), row.get("company"), row.get("subtype"))
        if row.get("product") == "פוליסות חסכון":
            tracks = by_num.get(str((row.get("data") or {}).get("track_number") or "").strip(), [])
        else:
            tracks = groups.get(key, [])
        man = manual_shares(indices)
        auto, eq = auto_shares(tracks)
        ids = set(man) | set(auto)
        overlap = sum(min(man.get(i, ("", 0))[1], auto.get(i, ("", 0))[1]) for i in ids)
        out.append({
            "product": key[0], "company": key[1], "subtype": key[2],
            "tracks": [t["key"] for t in tracks], "equity_total": eq,
            "overlap": overlap if tracks else None,
            "manual": sorted(((v[0], v[1], i) for i, v in man.items()), key=lambda x: -x[1]),
            "auto": sorted(((v[0], v[1], i) for i, v in auto.items()), key=lambda x: -x[1]),
        })
    return out


def to_markdown(rows: list[dict], top: int = 8) -> str:
    lines = ["| מוצר | חברה | סוג | מסלולים | חפיפה | ידני (sharetracks) | אוטומטי (מהדוחות) |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["overlap"] is None, r["overlap"] or 0)):
        man = "<br>".join(f"{n} {p*100:.0f}%" for n, p, _ in r["manual"][:top])
        auto = "<br>".join(f"{n} {p*100:.0f}%" for n, p, _ in r["auto"][:top]) or "—"
        ov = "אין מסלול תואם" if r["overlap"] is None else f"{r['overlap']*100:.0f}%"
        lines.append(f"| {r['product']} | {r['company']} | {r['subtype']} | {len(r['tracks'])} | {ov} | {man} | {auto} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path("out"))
    args = ap.parse_args()
    index_table = json.load(open(args.out_dir / "index_exposure.json", encoding="utf-8"))
    rows = compare(fetch_sharetracks(), index_table)
    (args.out_dir / "sharetracks_compare.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    md = to_markdown(rows)
    (args.out_dir / "sharetracks_compare.md").write_text(md, encoding="utf-8")
    matched = [r for r in rows if r["overlap"] is not None]
    print(f"[compare] {len(rows)} שורות הרכב ידני; {len(matched)} עם מסלול תואם; "
          f"חפיפה ממוצעת {sum(r['overlap'] for r in matched) / max(len(matched), 1) * 100:.0f}%")
    print(md)


if __name__ == "__main__":
    main()
