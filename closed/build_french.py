#!/usr/bin/env python3
"""Rebuild the closed block `french` -> closed/out/french.csv.

Columns: ff_mkt_rf, ff_smb, ff_hml, ff_rmw, ff_cma, ff_rf, ff_mkt (decimal returns, same day t;
ff_mkt = Mkt-RF + RF). Source: Kenneth R. French Data Library daily files
  F-F_Research_Data_Factors_daily_CSV.zip  and  F-F_Research_Data_5_Factors_2x3_daily_CSV.zip
(public download, no account). The library serves only its current vintage, so a fresh download is
expected to differ slightly from the authors' vintage (see closed/README.md and closed/verify.py).

Usage: python3 closed/build_french.py [--raw-dir DIR] [--offline]
"""
from common import french_frame, parser, raw_dir, round8, write_block

if __name__ == "__main__":
    a = parser(__doc__).parse_args()
    df = round8(french_frame(raw_dir(a, "french"), a.offline))
    write_block("french", df, a.out_dir)
