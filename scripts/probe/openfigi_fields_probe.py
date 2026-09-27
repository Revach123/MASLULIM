"""Probe round 3: `.info` alone (round 2) returned no `category` for any
mutual-fund sample - either yfinance's basic info call doesn't request the
fundProfile module for these, or Yahoo just doesn't attach it to these
OTC/foreign share classes. yfinance 1.x has a dedicated `funds_data` API
(separate from `.info`) that explicitly requests fund-specific modules,
including `asset_classes` (a real % breakdown by stocks/bonds/cash/other -
exactly the structured signal we want, if populated). Testing that
specifically before giving up on Yahoo/Morningstar data for this sample.
"""
import json

import yfinance as yf

SAMPLE = [
    ("0P0000SO5G", "bond", "UBAM Global High Yield Solution"),
    ("0P0001K29O", "bond", "Neuberger Berman Global Flexible Credit"),
    ("IE0034085260-USD.LU", "bond", "PIMCO GIS Global Investment Grade Credit"),
    ("0P0001AG9S.F", "?", "iShares Europe ex-UK Idx"),
]

for symbol, truth, label in SAMPLE:
    print(f"\n--- {symbol} ({label}) [expected: {truth}] ---")
    try:
        t = yf.Ticker(symbol)
        fd = t.funds_data
        print("description:", fd.description)
        print("fund_overview:", json.dumps(fd.fund_overview, indent=2, ensure_ascii=False, default=str))
        print("fund_operations:", json.dumps(fd.fund_operations.to_dict() if hasattr(fd.fund_operations, "to_dict") else fd.fund_operations, indent=2, ensure_ascii=False, default=str))
        print("asset_classes:", json.dumps(fd.asset_classes, indent=2, ensure_ascii=False, default=str))
        print("top_holdings:", fd.top_holdings.to_dict() if hasattr(fd.top_holdings, "to_dict") else fd.top_holdings)
    except Exception as e:
        print(f"failed: {type(e).__name__}: {e}")
