#!/usr/bin/env python3
"""Check rebuilt closed blocks (closed/out/<block>.csv) against the authors' vintage.

For every block present in closed/out/: SHA-256 of the block file and of each column versus
closed/expected_sha256.json, plus coverage (non-missing count, first and last date) versus the
recorded coverage. A column whose SHA-256 matches is byte-identical to the authors' panel.

With --reference PATH (a full panel CSV with every release column, if you have one)
it also reports value-level differences per column: rows that differ, max |difference| and
correlation on the common non-missing rows.

With --monthly it checks the closed monthly blocks (closed/out/monthly/<block>.csv, built by
closed/build_monthly.py) against closed/expected_sha256_monthly.json instead.

Usage: python3 closed/verify.py [--monthly] [--blocks crsp french ...] [--reference PATH/panel.csv]
Exit status 0 iff every checked block matches its expected SHA-256.
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

CLOSED = Path(__file__).resolve().parent


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_cols(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    h = rows[0]
    return h, {c: [r[i] for r in rows[1:]] for i, c in enumerate(h)}


def num(v):
    out = np.full(len(v), np.nan)
    for i, x in enumerate(v):
        try:
            out[i] = float(x) if x != "" else np.nan
        except ValueError:
            out[i] = np.nan
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monthly", action="store_true")
    ap.add_argument("--blocks", nargs="*", default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--reference", type=Path, default=None)
    a = ap.parse_args()
    key = "month" if a.monthly else "trading_date"
    a.out_dir = a.out_dir or (CLOSED / "out" / "monthly" if a.monthly else CLOSED / "out")
    exp = json.loads((CLOSED / ("expected_sha256_monthly.json" if a.monthly else "expected_sha256.json")).read_text())
    exp = exp["blocks"]
    names = a.blocks or [b for b in exp if (a.out_dir / f"{b}.csv").exists()]
    if not names:
        sys.exit(f"no rebuilt blocks found in {a.out_dir}")
    ref = read_cols(a.reference)[1] if a.reference else None
    all_ok = True
    for b in names:
        p = a.out_dir / f"{b}.csv"
        if not p.exists():
            print(f"[{b}] MISSING {p}")
            all_ok = False
            continue
        text = p.read_bytes().decode("utf-8")
        ok = sha(text) == exp[b]["sha256"]
        all_ok &= ok
        print(f"[{b}] block sha256 {'MATCH' if ok else 'DIFFERS'}")
        h, cols = read_cols(p)
        assert h == [key] + exp[b]["columns"], f"{b}: header differs from the block list"
        dates = cols[key]
        for c in exp[b]["columns"]:
            e = exp[b]["column_sha256"][c]
            v = cols[c]
            nn = [d for d, x in zip(dates, v) if x != ""]
            cov = (len(nn), nn[0] if nn else "", nn[-1] if nn else "")
            m = sha("\n".join(v) + "\n") == e["sha256"]
            line = f"   {c:28s} {'exact' if m else 'DIFF '}  n={cov[0]} ({cov[1]}..{cov[2]})"
            if cov != (e["n_nonmissing"], e["first"], e["last"]):
                line += f"  expected n={e['n_nonmissing']} ({e['first']}..{e['last']})"
            if ref is not None and not m:
                r, x = ref[c], v
                ndiff = sum(1 for p1, p2 in zip(r, x) if p1 != p2)
                rn, xn = num(r), num(x)
                both = ~np.isnan(rn) & ~np.isnan(xn)
                if both.any():
                    d = np.abs(rn[both] - xn[both])
                    cor = np.corrcoef(rn[both], xn[both])[0, 1] if both.sum() > 2 else float("nan")
                    n_val = int((d > 1e-12).sum())
                    line += (f"  | vs reference: {ndiff} cells differ; {n_val} values differ on {int(both.sum())} "
                             f"common rows, max|d|={d.max():.3g}, corr={cor:.6f}")
                else:
                    line += f"  | vs reference: {ndiff} cells differ (non-numeric)"
            print(line)
    print("ALL MATCH" if all_ok else "NOT ALL BLOCKS MATCH the authors' vintage (expected if sources were revised)")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
