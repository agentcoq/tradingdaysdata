#!/usr/bin/env python3
"""Rebuild the closed block `fred_thirdparty` -> closed/out/fred_thirdparty.csv.

FRED series whose underlying data carry third-party copyright (so they are not redistributed here):
  vix, vix_prev, vix_change_prev, vix_regime      <- VIXCLS (CBOE)
  credit_spread_baa10y, credit_spread_baa10y_prev <- BAA10Y (Moody's; DBAA, DGS10 fetched for the
  credit_spread_aaa10y                            <- AAA10Y  same start-date check as the released construction)
  sp500_level_fred                                <- SP500 (S&P Dow Jones Indices; FRED keeps ~10 years)
  ted_spread, ted_spread_prev                     <- TEDRATE (ICE LIBOR; discontinued 2022-01-21)

FRED access: set FRED_API_KEY in the environment (free key from https://fred.stlouisfed.org/docs/api/api_key.html).
Without it, the keyless fredgraph.csv download is used. The key is never printed or stored.
Observations are requested for 1960-01-01..2025-12-31.

Usage: python3 closed/build_fred_thirdparty.py [--raw-dir DIR] [--offline]
"""
import pandas as pd

from common import fetch_fred, parser, raw_dir, read_fred_json, round8, spine, write_block

SERIES = ["VIXCLS", "DBAA", "DAAA", "BAA10Y", "AAA10Y", "DGS10", "SP500", "TEDRATE"]
START, END = "1960-01-01", "2025-12-31"


def main():
    a = parser(__doc__).parse_args()
    raw = raw_dir(a, "fred_thirdparty")
    fred = {s: read_fred_json(fetch_fred(s, raw / f"fred_{s}.json", a.offline, START, END)) for s in SERIES}
    out = spine()

    def add(df, dst):
        nonlocal out
        out = out.merge(df[["trading_date", "value"]].rename(columns={"value": dst}), on="trading_date", how="left")

    add(fred["VIXCLS"], "vix")
    # BAA10Y / AAA10Y direct if at least as long as DBAA-DGS10 / DAAA-DGS10, else computed (released construction)
    for direct, comp_a, dst in [("BAA10Y", "DBAA", "credit_spread_baa10y"), ("AAA10Y", "DAAA", "credit_spread_aaa10y")]:
        comp = fred[comp_a].merge(fred["DGS10"], on="trading_date", suffixes=("_a", "_10"))
        comp["value"] = comp["value_a"] - comp["value_10"]
        if fred[direct]["trading_date"].min() <= comp["trading_date"].min():
            add(fred[direct], dst)
        else:
            print(f"  NOTE {dst}: computed as {comp_a} - DGS10 (direct series starts later)")
            add(comp, dst)
    add(fred["SP500"], "sp500_level_fred")
    add(fred["TEDRATE"], "ted_spread")

    v = out["vix"].astype(float)
    out["vix_prev"] = v.shift(1)
    out["vix_change_prev"] = v.shift(1) - v.shift(2)
    out["vix_regime"] = pd.cut(out["vix_prev"], bins=[0, 15, 25, 1000], labels=["low", "medium", "high"],
                               right=True).astype(object)
    for c in ["credit_spread_baa10y", "ted_spread"]:
        out[f"{c}_prev"] = out[c].astype(float).shift(1)
    write_block("fred_thirdparty", round8(out), a.out_dir)


if __name__ == "__main__":
    main()
