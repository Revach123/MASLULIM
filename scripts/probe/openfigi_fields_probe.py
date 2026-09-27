"""Probe round 2: OpenFIGI's marketSector/securityType are already disproven
(round 1 showed every fund sample - equity AND bond - comes back
marketSector="Equity", securityType2="Mutual Fund": this is the FUND SHARE's
own instrument category, not its underlying asset allocation. Useless as a
classification signal, confirming it's not a shortcut around content-based
classification).

This round tests the `yfinance` library (handles Yahoo's cookie/crumb dance
internally, unlike a bare requests.get to quoteSummary which round 1 also
showed gets a 401 "Invalid Crumb") for its Morningstar-sourced `category`
field - a real structured fund classification (e.g. "High Yield Bond",
"India Equity"), not a binary equity/bond guess.
"""
import json

import yfinance as yf

SAMPLE = [
    ("0P0000SO5G", "bond", "UBAM Global High Yield Solution"),
    ("0P0001K29O", "bond", "Neuberger Berman Global Flexible Credit"),
    ("IE0034085260-USD.LU", "bond", "PIMCO GIS Global Investment Grade Credit"),
    ("A200.AX", "equity", "BetaShares Australia 200 ETF"),
    ("PSUS", "equity", "Pershing Square USA Ltd"),
    ("0P0001AG9S.F", "?", "iShares Europe ex-UK Idx"),
]

for symbol, truth, label in SAMPLE:
    print(f"\n--- {symbol} ({label}) [expected: {truth}] ---")
    try:
        t = yf.Ticker(symbol)
        info = t.info
        keys_of_interest = {
            k: info.get(k) for k in (
                "category", "fundFamily", "legalType", "quoteType", "longName",
                "shortName", "totalAssets",
            ) if k in info
        }
        print(json.dumps(keys_of_interest, indent=2, ensure_ascii=False))
        if not keys_of_interest:
            print("(no info returned)")
    except Exception as e:
        print(f"failed: {type(e).__name__}: {e}")
