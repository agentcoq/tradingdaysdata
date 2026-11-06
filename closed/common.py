"""Shared helpers for the closed-block rebuild scripts (closed/build_<block>.py).

Nothing here holds credentials. The FRED key is read from the FRED_API_KEY environment variable and is
never printed, logged or written to disk (downloaded payloads are stored without the request URL, and
error messages are scrubbed of the key).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

CLOSED = Path(__file__).resolve().parent
REPO = CLOSED.parent
OUT_DIR = CLOSED / "out"
RAW_DIR = CLOSED / "raw"
OPEN_PANEL = REPO / "open" / "panel_open.csv"
USER_AGENT = "tradingdays-data closed-block rebuild (python requests)"
N_ROWS = 16610

FF_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF3_ZIP = "F-F_Research_Data_Factors_daily_CSV.zip"
FF5_ZIP = "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"
FRED_GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"


# --------------------------------------------------------------------------- CLI / IO
def parser(doc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=None,
                    help="directory holding (or receiving) the raw downloads for this block "
                         "(default: closed/raw/<block>/). Existing files are reused, never re-downloaded.")
    ap.add_argument("--offline", action="store_true", help="never download; fail if a raw file is missing")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="where <block>.csv is written (default closed/out/)")
    return ap


def blocks() -> dict:
    return json.loads((CLOSED / "blocks.json").read_text())


def spine() -> pd.DataFrame:
    """The 16,610 trading dates, read from the first column of open/panel_open.csv."""
    with OPEN_PANEL.open(newline="") as f:
        r = csv.reader(f)
        assert next(r)[0] == "trading_date"
        dates = [row[0] for row in r]
    assert len(dates) == N_ROWS and len(set(dates)) == N_ROWS
    return pd.DataFrame({"trading_date": dates})


def write_block(name: str, df: pd.DataFrame, out_dir: Path, roundtrip_kwargs: dict | None = None) -> Path:
    """Write closed/out/<name>.csv in the canonical form used by build_full.py and expected_sha256.json.

    In the released panel, the cell text of each column is pandas' default float formatting of the block's
    values after one CSV round trip (written with `roundtrip_kwargs`, parsed with pandas). This function
    applies the same round trip and writes the block columns with pandas defaults.
    """
    cols = blocks()[name]
    missing = [c for c in cols if c not in df.columns]
    assert not missing, f"{name}: missing columns {missing}"
    part = io.StringIO()
    df[["trading_date"] + cols].to_csv(part, index=False, **(roundtrip_kwargs or {}))
    part.seek(0)
    back = pd.read_csv(part, low_memory=False)
    assert len(back) == N_ROWS
    assert list(back["trading_date"]) == list(spine()["trading_date"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{name}.csv"
    back.to_csv(dst, index=False, lineterminator="\n")
    print(f"wrote {dst} ({len(back)} rows, {len(cols)} columns)")
    return dst


def raw_dir(args, block: str) -> Path:
    d = args.raw_dir or (RAW_DIR / block)
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- downloads
def _scrub(msg: str) -> str:
    key = os.environ.get("FRED_API_KEY", "")
    msg = re.sub(r"(api_key=)[^&\s'\"]*", r"\1***", msg)
    return msg.replace(key, "***") if key else msg


def fetch_url(url: str, dst: Path, offline: bool) -> Path:
    if dst.exists():
        print(f"  reuse {dst.name}")
        return dst
    if offline:
        raise SystemExit(f"--offline and missing raw file {dst}")
    import requests

    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
    r.raise_for_status()
    dst.write_bytes(r.content)
    print(f"  downloaded {url} -> {dst.name} ({len(r.content) / 1024:.0f} KB)")
    return dst


def fetch_french(raw: Path, offline: bool) -> tuple[Path, Path]:
    return (fetch_url(FF_BASE + FF3_ZIP, raw / FF3_ZIP, offline),
            fetch_url(FF_BASE + FF5_ZIP, raw / FF5_ZIP, offline))


def fetch_fred(series_id: str, dst: Path, offline: bool, start: str, end: str | None = None) -> Path:
    """FRED observations -> JSON file {'observations': [{'date','value'}, ...]} (no URL, no key stored).

    Uses the FRED API when FRED_API_KEY is set; otherwise falls back to the keyless fredgraph.csv
    download of the same series (same values, converted to the API's JSON layout).
    """
    if dst.exists():
        print(f"  reuse {dst.name}")
        return dst
    if offline:
        raise SystemExit(f"--offline and missing raw file {dst}")
    import requests

    key = os.environ.get("FRED_API_KEY", "").strip()
    try:
        if key:
            params = {"series_id": series_id, "api_key": key, "file_type": "json", "observation_start": start}
            if end:
                params["observation_end"] = end
            r = requests.get(FRED_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            js = r.json()
            if "observations" not in js:
                raise RuntimeError(f"FRED {series_id}: unexpected response")
            js = {"source": "FRED API", "series_id": series_id,
                  "observations": [{"date": o["date"], "value": o["value"]} for o in js["observations"]]}
        else:
            params = {"id": series_id, "cosd": start}
            if end:
                params["coed"] = end
            r = requests.get(FRED_GRAPH, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text), dtype=str)
            dcol, vcol = df.columns[0], df.columns[1]
            obs = [{"date": d, "value": ("." if (not isinstance(v, str) or v.strip() == "") else v)}
                   for d, v in zip(df[dcol], df[vcol])]
            js = {"source": "FRED fredgraph.csv (keyless)", "series_id": series_id, "observations": obs}
    except Exception as e:  # noqa: BLE001 - never let the key leak through an exception message
        raise RuntimeError(_scrub(f"FRED download of {series_id} failed: {type(e).__name__}: {e}")) from None
    dst.write_text(json.dumps(js))
    print(f"  downloaded FRED {series_id} ({js['source']}): {len(js['observations'])} obs -> {dst.name}")
    return dst


# --------------------------------------------------------------------------- readers
def read_french_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        txt = z.read(name).decode("utf-8", errors="replace")
    lines = txt.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(","))
    rows = [lines[start]]
    for ln in lines[start + 1:]:
        if ln[:8].isdigit():
            rows.append(ln)
        elif ln.strip() == "" or ln.startswith("Copyright"):
            break
    df = pd.read_csv(io.StringIO("\n".join(rows)))
    df = df.rename(columns={df.columns[0]: "date"})
    df["trading_date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d")
    df = df.drop(columns="date")
    for c in df.columns:
        if c != "trading_date":
            df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0
    return df


def french_frame(raw: Path, offline: bool) -> pd.DataFrame:
    """Spine-aligned unrounded ff_* columns in the released construction (decimal, not percent)."""
    p3, p5 = fetch_french(raw, offline)
    ff3, ff5 = read_french_zip(p3), read_french_zip(p5)
    ff3["ff_mkt"] = ff3["Mkt-RF"] + ff3["RF"]
    out = spine()
    for df, src, dst in [(ff3, "Mkt-RF", "ff_mkt_rf"), (ff3, "SMB", "ff_smb"), (ff3, "HML", "ff_hml"),
                         (ff5, "RMW", "ff_rmw"), (ff5, "CMA", "ff_cma"), (ff3, "RF", "ff_rf"),
                         (ff3, "ff_mkt", "ff_mkt")]:
        out = out.merge(df[["trading_date", src]].rename(columns={src: dst}), on="trading_date", how="left")
    return out


def read_fred_json(path: Path) -> pd.DataFrame:
    js = json.loads(path.read_text())
    df = pd.DataFrame(js["observations"])[["date", "value"]]
    df["value"] = pd.to_numeric(df["value"].replace(".", np.nan), errors="coerce")
    return df.rename(columns={"date": "trading_date"}).dropna(subset=["value"])


def fred_series(path: Path) -> pd.Series:
    obs = json.loads(path.read_text())["observations"]
    s = pd.DataFrame(obs)[["date", "value"]]
    s["date"] = pd.to_datetime(s["date"])
    s["value"] = pd.to_numeric(s["value"].replace(".", np.nan), errors="coerce")
    return s.set_index("date")["value"].sort_index()


def round8(df: pd.DataFrame) -> pd.DataFrame:
    num = df.select_dtypes(include=[np.number]).columns
    df[num] = df[num].round(8)
    return df
