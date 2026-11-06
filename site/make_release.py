#!/usr/bin/env python3
"""Build the downloadable files of one release from the data repository.

    python3 site/make_release.py --data ../tradingdays-data

Reads the open tier of the data repository and writes release/v<version>/ (not committed; the files go to the
GitHub release and to Zenodo):

    trading_days_daily_open.csv / .parquet      trading_date + the open daily columns
    trading_days_monthly_open.csv / .parquet    month + the open monthly columns
    codebook_daily.csv, codebook_monthly.csv    the data dictionaries, all columns (open and licensed)
    SHA256SUMS, manifest.json                   checksums and sizes, read by build_site.py

The CSV files are byte copies of the data repository's files and are the reference. The parquet files hold the
same data with types inferred by pandas (numbers as numbers, the date key as a date, blank cells as missing).
Only open-tier columns are written: the script stops if a licensed column is found in the open files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FILES = {  # release name -> path in the data repository
    "trading_days_daily_open.csv": "open/panel_open.csv",
    "trading_days_monthly_open.csv": "open/monthly/panel_monthly_open.csv",
    "codebook_daily.csv": "open/columns.csv",
    "codebook_monthly.csv": "open/monthly/columns_monthly.csv",
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT.parent / "tradingdays-data"))
    a = ap.parse_args()
    data = Path(a.data)
    cfg = json.loads((ROOT / "site/config.json").read_text())
    out = ROOT / "release" / f"v{cfg['release']['version']}"
    out.mkdir(parents=True, exist_ok=True)

    # no licensed column may leave through the open files
    daily_cb = pd.read_csv(data / FILES["codebook_daily.csv"])
    monthly_cb = pd.read_csv(data / FILES["codebook_monthly.csv"])
    for name, cb in [("trading_days_daily_open.csv", daily_cb), ("trading_days_monthly_open.csv", monthly_cb)]:
        cols = list(pd.read_csv(data / FILES[name], nrows=0).columns)
        open_set = set(cb.loc[cb.rights_tier == "open", "column"])
        closed = set(cb.loc[cb.rights_tier == "closed", "column"])
        leak = sorted(set(cols) & closed)
        assert not leak, f"licensed columns in {name}: {leak}"
        unknown = sorted(set(cols) - open_set)
        assert not unknown, f"columns of {name} that the codebook does not mark as open: {unknown}"
        assert len(cols) == len(set(cols)) == len(open_set), f"{name}: {len(cols)} columns, codebook has {len(open_set)} open"

    for name, src in FILES.items():
        shutil.copyfile(data / src, out / name)
    for name in ["trading_days_daily_open.csv", "trading_days_monthly_open.csv"]:
        df = pd.read_csv(out / name, low_memory=False)
        key = df.columns[0]
        df[key] = pd.to_datetime(df[key], format="%Y-%m-%d" if key == "trading_date" else "%Y-%m")
        if key == "trading_date":
            df[key] = df[key].dt.date
        else:
            df[key] = df[key].dt.strftime("%Y-%m")
        df.to_parquet(out / name.replace(".csv", ".parquet"), index=False)
        back = pd.read_parquet(out / name.replace(".csv", ".parquet"))
        assert back.shape == df.shape and list(back.columns) == list(df.columns), name

    rows = []
    for p in sorted(out.iterdir()):
        if p.name in ("SHA256SUMS", "manifest.json"):
            continue
        rows.append(dict(file=p.name, bytes=p.stat().st_size, sha256=sha256(p)))
    (out / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['file']}\n" for r in rows))
    daily = pd.read_csv(out / "trading_days_daily_open.csv", usecols=[0], dtype=str)
    monthly = pd.read_csv(out / "trading_days_monthly_open.csv", usecols=[0], dtype=str)
    manifest = dict(version=cfg["release"]["version"], files=rows,
                    daily=dict(rows=len(daily), first=daily.iloc[0, 0], last=daily.iloc[-1, 0],
                               open_columns=len(pd.read_csv(out / "trading_days_daily_open.csv", nrows=0).columns) - 1),
                    monthly=dict(rows=len(monthly), first=monthly.iloc[0, 0], last=monthly.iloc[-1, 0],
                                 open_columns=len(pd.read_csv(out / "trading_days_monthly_open.csv", nrows=0).columns) - 1))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
