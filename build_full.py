#!/usr/bin/env python3
"""Assemble the full trading-days panel (409 columns) from the open tier and the rebuilt closed blocks, or, with
--monthly, the full monthly panel (593 columns) from the open monthly file and the rebuilt closed monthly blocks.

  open/panel_open.csv        357 columns (trading_date + 356 open columns), committed in this repository
  closed/out/<block>.csv     52 closed columns in 6 blocks, produced locally by closed/build_<block>.py
  open/columns.csv           data dictionary; its row order is the column order of the full panel

The merge works on cell text (no float re-formatting), so the output is byte-identical to the
authors' panel whenever the closed blocks are.

Monthly panel (one row per calendar month 1960-01..2025-12, key `month`):
  open/monthly/panel_monthly_open.csv   month + 528 open monthly columns, committed
  closed/out/monthly/<block>.csv        64 closed monthly columns in 6 blocks, produced locally by
                                        closed/build_monthly.py from panel_full.csv
  open/monthly/columns_monthly.csv      monthly data dictionary; its row order is the column order

Usage
  python3 build_full.py                            # merge closed/out/*.csv -> panel_full.csv
  python3 build_full.py --allow-missing            # leave columns of missing closed blocks empty
  python3 build_full.py --from-reference PANEL     # acceptance test: extract the closed blocks from an
                                                   # existing full panel.csv into a temporary closed dir,
                                                   # merge, and require a byte-for-byte SHA-256 match
  python3 build_full.py --monthly [...]            # the same three modes for the monthly panel
                                                   # (-> panel_monthly_full.csv; PANEL = a full monthly panel)
"""
import argparse
import csv
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
DAILY = dict(key="trading_date", rows=16610, open=REPO / "open" / "panel_open.csv",
             dictionary=REPO / "open" / "columns.csv", blocks=REPO / "closed" / "blocks.json",
             expected=REPO / "closed" / "expected_sha256.json", closed_dir=REPO / "closed" / "out",
             out=REPO / "panel_full.csv", builder="closed/build_{b}.py")
MONTHLY = dict(key="month", rows=792, open=REPO / "open" / "monthly" / "panel_monthly_open.csv",
               dictionary=REPO / "open" / "monthly" / "columns_monthly.csv",
               blocks=REPO / "closed" / "blocks_monthly.json",
               expected=REPO / "closed" / "expected_sha256_monthly.json",
               closed_dir=REPO / "closed" / "out" / "monthly", out=REPO / "panel_monthly_full.csv",
               builder="closed/build_monthly.py")


def read_csv_text(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def to_text(rows) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def extract_blocks(reference: Path, dst: Path, blocks: dict, key: str = "trading_date") -> None:
    h, body = read_csv_text(reference)
    idx = {c: i for i, c in enumerate(h)}
    assert h[0] == key, f"{reference}: first column {h[0]!r} != {key!r}"
    for b, cols in blocks.items():
        ci = [idx[c] for c in cols]
        (dst / f"{b}.csv").write_text(to_text([[key] + cols] + [[r[0]] + [r[i] for i in ci] for r in body]),
                                      encoding="utf-8")


def merge(closed_dir: Path, allow_missing: bool, cfg: dict = DAILY) -> str:
    key, n_rows = cfg["key"], cfg["rows"]
    order = [r["column"] for r in csv.DictReader(cfg["dictionary"].open(newline="", encoding="utf-8"))]
    blocks = json.loads(cfg["blocks"].read_text())
    oh, ob = read_csv_text(cfg["open"])
    assert len(ob) == n_rows and oh[0] == key
    dates = [r[0] for r in ob]
    data = {c: [r[i] for r in ob] for i, c in enumerate(oh)}
    for b, cols in blocks.items():
        p = closed_dir / f"{b}.csv"
        if not p.exists():
            if not allow_missing:
                sys.exit(f"missing closed block {p}; run {cfg['builder'].format(b=b)} (or pass --allow-missing)")
            print(f"[warn] {b}: {p} missing, its {len(cols)} columns are left empty")
            for c in cols:
                data[c] = [""] * n_rows
            continue
        h, body = read_csv_text(p)
        assert h == [key] + cols, f"{p}: header {h[:4]}... != {cfg['blocks'].name}"
        assert [r[0] for r in body] == dates, f"{p}: {key} values differ from {cfg['open'].name}"
        for i, c in enumerate(h[1:], start=1):
            data[c] = [r[i] for r in body]
    assert set(data) == set(order) and len(order) == len(set(order)), f"column sets differ from {cfg['dictionary']}"
    return to_text([order] + [[data[c][k] for c in order] for k in range(n_rows)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monthly", action="store_true", help="assemble the monthly panel instead of the daily one")
    ap.add_argument("--closed-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--from-reference", type=Path, default=None, metavar="PANEL")
    a = ap.parse_args()
    cfg = MONTHLY if a.monthly else DAILY
    closed_dir = a.closed_dir or cfg["closed_dir"]
    out = a.out or cfg["out"]
    exp = json.loads(cfg["expected"].read_text())
    blocks = json.loads(cfg["blocks"].read_text())

    if a.from_reference:
        with tempfile.TemporaryDirectory() as td:
            extract_blocks(a.from_reference, Path(td), blocks, cfg["key"])
            for b in blocks:
                s = hashlib.sha256((Path(td) / f"{b}.csv").read_bytes()).hexdigest()
                print(f"  extracted {b:24s} sha256 {'= expected' if s == exp['blocks'][b]['sha256'] else '!= expected'}")
            text = merge(Path(td), False, cfg)
    else:
        text = merge(closed_dir, a.allow_missing, cfg)

    data = text.encode("utf-8")
    out.write_bytes(data)
    got = hashlib.sha256(data).hexdigest()
    print(f"wrote {out}: {cfg['rows']} rows x {exp['full_panel']['columns']} columns, sha256 {got}")
    print(f"authors' vintage sha256    {exp['full_panel']['sha256']}  -> "
          f"{'MATCH (byte-identical)' if got == exp['full_panel']['sha256'] else 'differs'}")
    if a.from_reference:
        ref = hashlib.sha256(a.from_reference.read_bytes()).hexdigest()
        ok = got == ref
        print(f"reference file sha256      {ref}  -> {'MATCH' if ok else 'MISMATCH'}")
        print("ACCEPTANCE TEST " + ("PASSED" if ok else "FAILED"))
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
