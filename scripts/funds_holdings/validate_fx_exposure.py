"""אימות מודל החשיפה למט"ח (fx_exposure) מול FOREIGN_CURRENCY_EXPOSURE הרשמי (data.gov.il) לחודש
הדוח - כמו validate_equity_exposure למניות. MAE לכל וריאנט (עם / בלי חוזים עתידיים ואופציות),
הפערים הגדולים, ובמצב DUMP_EQUITY_COMPONENTS שורת FXCOMP לכל מסלול (לסימולציה מקומית).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .file_list import get_file_list
from .fund_exposure_reference import fetch_fund_fx_exposure
from .funds_reference import build_funds_reference
from .fx_exposure import COMPONENTS, build_fx_exposure, fx_total
from .isin_swap import build_isin_swap
from .sheet_source import build_source
from .track_pct_normalize import normalize_track_pct
from .tracks_reference import fetch_tracks, track_key

VARIANTS = {
    "מלא": COMPONENTS,
    "בלי חוזים עתידיים": tuple(c for c in COMPONENTS if c != "futures"),
    "בלי חוזים ואופציות": tuple(c for c in COMPONENTS if c not in ("futures", "options")),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = ap.parse_args()

    tracks = fetch_tracks()
    source = build_source(get_file_list(args.reports_dir))
    normalize_track_pct(source)
    funds_ref = build_funds_reference()
    comps = build_fx_exposure(source, build_isin_swap(funds_ref), funds_ref, fetch_fund_fx_exposure())

    report_month: dict[str, str] = {}
    for rec in source:
        d = rec.get("ReportMonth")
        if d is None:
            continue
        ym = f"{d.year}{d.month:02d}"
        for r in rec["Clean"]:
            k = r.get("מפתח")
            if k is not None and ym > report_month.get(k, ""):
                report_month[k] = ym
    domain_track = {}
    for t in tracks:
        key = track_key(t)
        if key is not None:
            domain_track[key] = (str(t.get("תחום") or "").strip(), key.split("_", 1)[1])

    from .official_history import fetch_exposure
    hist = fetch_exposure({m for m in report_month.values() if m}, "FOREIGN_CURRENCY_EXPOSURE")
    official = {}
    for key, (dom, track) in domain_track.items():
        v = hist.get((dom, track, report_month.get(key, "")))
        if v is not None and key in comps:
            official[key] = v
    print(f"[fx] {len(hist)} ערכים רשמיים (חשיפה למט\"ח) מ-data.gov.il, {len(official)} מסלולים עם דוח הותאמו")
    if not official:
        return

    for name, inc in VARIANTS.items():
        errs = [abs(fx_total(comps[k], inc) - v) for k, v in official.items()]
        print(f"MAE חשיפה למט\"ח ({name}) מול הנתון הרשמי לחודש הדוח: {len(errs)} מסלולים, "
              f"{sum(errs) / len(errs) * 100:.3f} נק' אחוז")
    gaps = sorted(official.items(), key=lambda kv: -abs(fx_total(comps[kv[0]]) - kv[1]))
    print("  30 הפערים הגדולים (מודל מול רשמי):")
    for k, v in gaps[:30]:
        c = comps[k]
        parts = " ".join(f"{n}={c[n] * 100:.1f}" for n in COMPONENTS if abs(c.get(n, 0)) >= 0.0005)
        print(f"    {k:22s} {fx_total(c) * 100:7.2f}% {v * 100:7.2f}%  {parts}")
    if os.environ.get("DUMP_EQUITY_COMPONENTS"):
        for k, v in official.items():
            print("FXCOMP|" + "|".join([k, f"{v:.6f}"] + [f"{comps[k].get(n, 0.0):.6f}" for n in COMPONENTS]))


if __name__ == "__main__":
    main()
