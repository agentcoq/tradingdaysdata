#!/usr/bin/env python3
"""Rebuild the closed monthly blocks from the full daily panel.

  input   panel_full.csv (output of build_full.py, which needs the closed daily blocks in closed/out/)
          open/monthly/columns_monthly.csv (aggregation of each monthly column) and closed/blocks_monthly.json
  output  closed/out/monthly/<block>.csv, one per closed monthly block: header 'month,<columns>', one row per
          calendar month 1960-01..2025-12

The aggregation engine is open/code/monthly/monthly_core.py, the same file that built the authors' panel, so daily
input identical to the authors' gives byte-identical blocks (check with `python3 closed/verify.py --monthly`).
Closed data stay under their providers' terms: closed/out/ is gitignored and must never be committed.

Usage: python3 closed/build_monthly.py [--daily panel_full.csv] [--out-dir closed/out/monthly] [--blocks B ...]
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

CLOSED = Path(__file__).resolve().parent
REPO = CLOSED.parent
sys.path.insert(0, str(REPO / "open" / "code" / "monthly"))
import monthly_core as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily", type=Path, default=REPO / "panel_full.csv")
    ap.add_argument("--out-dir", type=Path, default=CLOSED / "out" / "monthly")
    ap.add_argument("--blocks", nargs="*", default=None)
    a = ap.parse_args()
    if not a.daily.exists():
        sys.exit(f"{a.daily} not found: rebuild the closed daily blocks and run `python3 build_full.py` first")
    spec = pd.read_csv(REPO / "open" / "monthly" / "columns_monthly.csv", keep_default_na=False)
    spec = spec[spec["aggregation"] != "key"]
    blocks = json.loads((CLOSED / "blocks_monthly.json").read_text())
    a.out_dir.mkdir(parents=True, exist_ok=True)
    for b in a.blocks or list(blocks):
        sb = spec.set_index("column").loc[blocks[b]].reset_index()
        assert (sb["closed_block"] == b).all(), f"{b}: dictionary and blocks_monthly.json disagree"
        need = sorted(set(sb["source"]) | {p.split(":", 1)[1] for p in sb["aggregation"] if p.startswith("wmean:")})
        daily = C.read_daily(a.daily, columns=need)
        empty = [c for c in need if daily[c].isna().all()]
        if empty:
            print(f"[skip] {b}: daily columns {empty} are empty (closed daily block not rebuilt?)")
            continue
        m = C.build_monthly(daily, sb[["column", "source", "aggregation"]])
        p = a.out_dir / f"{b}.csv"
        p.write_text(C.to_csv_text(m), encoding="utf-8")
        print(f"wrote {p}: {len(m)} months x {len(blocks[b])} columns")


if __name__ == "__main__":
    main()
