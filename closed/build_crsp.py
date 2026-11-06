#!/usr/bin/env python3
"""Rebuild the closed block `crsp` -> closed/out/crsp.csv  (requires a CRSP subscription via WRDS).

Columns: crsp_vwretd, crsp_ewretd, crsp_sprtrn (CRSP daily stock index file, same day t);
mkt_ret (= crsp_vwretd, spliced with Ken French Mkt-RF+RF where CRSP is
missing, i.e. 2025 at the authors' vintage) and mkt_ret_source_ff (1 on spliced days); and the ex-ante
state variables derived from mkt_ret: mkt_ret_prev, mkt_ret_prev5, mkt_rvol_5d, mkt_rvol_21d,
mkt_consecutive_up, mkt_consecutive_down, mkt_dist_52w_high, mkt_dist_52w_low.

CRSP input (one of):
  * WRDS (default): `SELECT date, vwretd, vwretx, ewretd, sprtrn FROM crsp.dsi` via the `wrds` Python
    package. Credentials come ONLY from the environment / your own config, never from this repo:
      WRDS_USER  (required)  your WRDS username
      WRDS_PASS  (optional)  password; if unset, the wrds package uses ~/.pgpass or prompts
    (WRDS enforces Duo two-factor authentication on first connection.)
  * --crsp-csv PATH: a CSV you exported yourself with columns date, vwretd, ewretd, sprtrn
    (vwretx optional), e.g. from the WRDS web query form for "CRSP Daily Stock Market Indexes".
The pulled CRSP extract is cached as <raw-dir>/crsp_dsi.csv (gitignored: never commit it).

--crsp-end (default 2024-12-31, the last date of legacy crsp.dsi at the authors' vintage) truncates
CRSP so mkt_ret switches to Ken French after it, reproducing the released splice. Pass a later date
to use a newer CRSP vintage (the result will then differ from expected_sha256.json by design).
The Ken French daily zips are downloaded as for build_french.py (needed for the splice).

Usage: python3 closed/build_crsp.py [--crsp-csv PATH] [--crsp-end YYYY-MM-DD] [--raw-dir DIR] [--offline]
"""
import os

import numpy as np
import pandas as pd

from common import french_frame, parser, raw_dir, round8, spine, write_block

START = "1960-01-01"


def pull_wrds(dst, end):
    user = os.environ.get("WRDS_USER", "").strip()
    if not user:
        raise SystemExit("set WRDS_USER (and optionally WRDS_PASS, or use ~/.pgpass), or pass --crsp-csv")
    import wrds

    kw = {"wrds_username": user}
    if os.environ.get("WRDS_PASS"):
        kw["wrds_password"] = os.environ["WRDS_PASS"]
    db = wrds.Connection(**kw)
    try:
        df = db.raw_sql("SELECT date, vwretd, vwretx, ewretd, sprtrn FROM crsp.dsi "
                        f"WHERE date >= '{START}' AND date <= '{end}' ORDER BY date")
    finally:
        db.close()
    df.to_csv(dst, index=False)
    print(f"  pulled crsp.dsi: {len(df)} rows -> {dst}")


def consecutive_runs(ret):
    up = np.zeros(len(ret), dtype=float)
    down = np.zeros(len(ret), dtype=float)
    u = d = 0
    for i, r in enumerate(ret):
        if np.isnan(r):
            u = d = 0
            up[i] = down[i] = np.nan
            continue
        if r > 0:
            u += 1
            d = 0
        elif r < 0:
            d += 1
            u = 0
        else:
            u = d = 0
        up[i], down[i] = u, d
    return up, down


def main():
    ap = parser(__doc__)
    ap.add_argument("--crsp-csv", default=None, help="use this CRSP daily index export instead of querying WRDS")
    ap.add_argument("--crsp-end", default="2024-12-31", help="last CRSP date used (default 2024-12-31)")
    a = ap.parse_args()
    a.crsp_end = pd.Timestamp(a.crsp_end).strftime("%Y-%m-%d")  # validate: must parse as a date
    raw = raw_dir(a, "crsp")
    src = a.crsp_csv or (raw / "crsp_dsi.csv")
    if not a.crsp_csv and not src.exists():
        if a.offline:
            raise SystemExit(f"--offline and missing {src}")
        pull_wrds(src, a.crsp_end)
    crsp = pd.read_csv(src, dtype={"date": str}).rename(columns={"date": "trading_date"})
    crsp["trading_date"] = crsp["trading_date"].str[:10]
    crsp = crsp[(crsp["trading_date"] >= START) & (crsp["trading_date"] <= a.crsp_end)]

    out = spine()
    for s, d in [("vwretd", "crsp_vwretd"), ("ewretd", "crsp_ewretd"), ("sprtrn", "crsp_sprtrn")]:
        out = out.merge(crsp[["trading_date", s]].rename(columns={s: d}), on="trading_date", how="left")
    ff = french_frame(raw, a.offline)
    out = out.merge(ff[["trading_date", "ff_mkt"]], on="trading_date", how="left")

    out["mkt_ret"] = out["crsp_vwretd"].fillna(out["ff_mkt"])
    out["mkt_ret_source_ff"] = (out["crsp_vwretd"].isna() & out["ff_mkt"].notna()).astype(int)
    r = out["mkt_ret"].astype(float)
    out["mkt_ret_prev"] = r.shift(1)
    out["mkt_ret_prev5"] = (1 + r).rolling(5).apply(np.prod, raw=True).shift(1) - 1
    out["mkt_rvol_5d"] = r.rolling(5).std().shift(1)
    out["mkt_rvol_21d"] = r.rolling(21).std().shift(1)
    up, down = consecutive_runs(r.values)
    out["mkt_consecutive_up"] = pd.Series(up).shift(1).values
    out["mkt_consecutive_down"] = pd.Series(down).shift(1).values
    level = (1 + r.fillna(0)).cumprod().where(r.notna())
    hi = level.rolling(252, min_periods=50).max()
    lo = level.rolling(252, min_periods=50).min()
    out["mkt_dist_52w_high"] = (level / hi - 1).shift(1)
    out["mkt_dist_52w_low"] = (level / lo - 1).shift(1)
    last = out.loc[out["crsp_vwretd"].notna(), "trading_date"].max()
    print(f"  CRSP vwretd last date {last}; spliced (Ken French) days: {int(out['mkt_ret_source_ff'].sum())}")
    write_block("crsp", round8(out), a.out_dir)


if __name__ == "__main__":
    main()
