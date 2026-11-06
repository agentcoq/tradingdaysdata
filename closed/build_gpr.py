#!/usr/bin/env python3
"""Rebuild the closed block `gpr` -> closed/out/gpr.csv.

Caldara & Iacoviello Geopolitical Risk indexes (https://www.matteoiacoviello.com/gpr.htm):
  gpr_daily       GPRD of data_gpr_daily_recent.dta dated t (not ex-ante)
  gpr_daily_prev  GPRD dated calendar day t-1 (no forward fill)
  gpr_monthly     GPR  of data_gpr_export.dta for the month containing t (1985+; not ex-ante)
  gprh_monthly    GPRH of data_gpr_export.dta for the month containing t (historical index; not ex-ante)
Public download, no account. The files are updated regularly; history can be revised.

Usage: python3 closed/build_gpr.py [--raw-dir DIR] [--offline]
"""
import pandas as pd

from common import fetch_url, parser, raw_dir, spine, write_block

GPR_BASE = "https://www.matteoiacoviello.com/gpr_files/"


def main():
    a = parser(__doc__).parse_args()
    raw = raw_dir(a, "gpr")
    pd_ = fetch_url(GPR_BASE + "data_gpr_daily_recent.dta", raw / "data_gpr_daily_recent.dta", a.offline)
    pm_ = fetch_url(GPR_BASE + "data_gpr_export.dta", raw / "data_gpr_export.dta", a.offline)
    s = spine()
    t = pd.to_datetime(s["trading_date"])

    g = pd.read_stata(pd_)
    gcol = "GPRD" if "GPRD" in g.columns else [c for c in g.columns if c.upper().startswith("GPR")][0]
    dcol = [c for c in g.columns if "date" in c.lower()][0]
    gs = g[[dcol, gcol]].dropna()
    gs[dcol] = pd.to_datetime(gs[dcol])
    gs = gs.set_index(dcol)[gcol].sort_index()
    gs = gs[~gs.index.duplicated(keep="last")]
    s["gpr_daily"] = t.map(gs)
    s["gpr_daily_prev"] = (t - pd.Timedelta(days=1)).map(gs)

    gm = pd.read_stata(pm_)
    mcol = [c for c in gm.columns if "month" in c.lower() or "date" in c.lower()][0]
    gm[mcol] = pd.to_datetime(gm[mcol])
    gm = gm.set_index(gm[mcol].dt.to_period("M"))
    s["gpr_monthly"] = t.dt.to_period("M").map(gm["GPR"].dropna())
    s["gprh_monthly"] = t.dt.to_period("M").map(gm["GPRH"].dropna())
    write_block("gpr", s, a.out_dir, roundtrip_kwargs={"float_format": "%.6g"})


if __name__ == "__main__":
    main()
