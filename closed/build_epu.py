#!/usr/bin/env python3
"""Rebuild the closed block `epu` -> closed/out/epu.csv.

Baker, Bloom & Davis Economic Policy Uncertainty (US), as distributed on FRED:
  epu_daily       USEPUINDXD value dated t (same-day newspapers; not ex-ante)
  epu_daily_prev  USEPUINDXD value dated calendar day t-1 (no forward fill)
  epu_monthly     USEPUINDXM value of the month containing t (not ex-ante)
FRED access as in build_fred_thirdparty.py (FRED_API_KEY env var, else keyless fredgraph.csv).
The same series are published at https://www.policyuncertainty.com (All_Daily_Policy_Data.csv,
US_Policy_Uncertainty_Data.xlsx); the daily index is recomputed as articles are added, so later
downloads can differ from the authors' vintage.

Usage: python3 closed/build_epu.py [--raw-dir DIR] [--offline]
"""
import pandas as pd

from common import fetch_fred, fred_series, parser, raw_dir, spine, write_block


def main():
    a = parser(__doc__).parse_args()
    raw = raw_dir(a, "epu")
    epu_d = fred_series(fetch_fred("USEPUINDXD", raw / "fred_USEPUINDXD.json", a.offline, "1985-01-01"))
    epu_m = fred_series(fetch_fred("USEPUINDXM", raw / "fred_USEPUINDXM.json", a.offline, "1985-01-01"))
    epu_m.index = epu_m.index.to_period("M")
    s = spine()
    t = pd.to_datetime(s["trading_date"])
    s["epu_daily"] = t.map(epu_d)
    s["epu_daily_prev"] = (t - pd.Timedelta(days=1)).map(epu_d)
    s["epu_monthly"] = t.dt.to_period("M").map(epu_m)
    # released cell format: one round trip with float_format="%.6g"
    write_block("epu", s, a.out_dir, roundtrip_kwargs={"float_format": "%.6g"})


if __name__ == "__main__":
    main()
