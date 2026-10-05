"""אבחון חד-פעמי: רמות MSCI ב-Yahoo (מחיר / NTR / GTR) לתאריך נתון, לזיהוי חוזי Cboe (FJW, OEY)."""
import sys
from datetime import date

from .option_delta_pricing import price_as_of

CODES = {"World": "990100", "USA": "984000", "ACWI": "892400", "EAFE": "990300"}
VARIANTS = ("STRD", "NETR", "GRTR")
EXTRA = ["^MXUSA", "^MXWLD", "^MXACW", "^MXWO", "^MXUS", "URTH", "ACWI", "EUSA", "SPY"]

d = date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2025-09-30")
for name, code in CODES.items():
    for v in VARIANTS:
        sym = f"^{code}-USD-{v}"
        print(f"[msci] {d} {name:5} {v}  {sym:20} {price_as_of(sym, d)}")
for sym in EXTRA:
    print(f"[msci] {d} {sym:20} {price_as_of(sym, d)}")
