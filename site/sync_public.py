#!/usr/bin/env python3
"""Copy the public portion of the data repository into this repository, and check it.

    python3 site/sync_public.py --data ../tradingdays-data

Only the files listed in PUBLIC are copied, never a folder: the open daily and monthly panels, their codebooks,
the Wikipedia attribution record, the licences and attribution notice, and the code that rebuilds the licensed
columns from the user's own access (scripts only, no data). Nothing under closed/out/ or any other data of the
licensed tier is ever copied. After copying, the script checks that
  - every column of the open panels is marked open in its codebook, and none is marked licensed;
  - no CSV, parquet or other data file sits under closed/;
  - no copied text file contains an absolute local path, an email address or a credential.
It stops at the first failure.
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = [
    # open data (CC BY 4.0 or CC BY-SA 4.0, per column)
    "open/panel_open.csv", "open/columns.csv",
    "open/monthly/panel_monthly_open.csv", "open/monthly/columns_monthly.csv",
    "open/supporting/wikipedia_sources.csv",          # attribution record required by CC BY-SA
    # licences and attribution
    "LICENSE-DATA-CC-BY-4.0.txt", "LICENSE-DATA-CC-BY-SA-4.0.txt", "NOTICE.md",
    # code that rebuilds the licensed columns from the user's own access (no data)
    "build_full.py", "requirements.txt",
    "closed/README.md", "closed/common.py", "closed/verify.py", "closed/build_monthly.py",
    "closed/build_crsp.py", "closed/build_earnings.py", "closed/build_french.py",
    "closed/build_fred_thirdparty.py", "closed/build_epu.py", "closed/build_gpr.py",
    "closed/blocks.json", "closed/blocks_monthly.json",
    "closed/expected_sha256.json", "closed/expected_sha256_monthly.json",
]
TEXT = (".py", ".md", ".json", ".txt")
SUSPECT = [(r"/Users/|/home/[a-z]", "absolute local path"),
           (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "email address"),
           (r"(api_key|password|passwd|secret|token)\s*[=:]\s*['\"][^'\"\s*]{6,}", "credential")]


def header(p: Path) -> list[str]:
    with open(p, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def tiers(p: Path) -> tuple[set, set]:
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return ({r["column"] for r in rows if r["rights_tier"] == "open"},
            {r["column"] for r in rows if r["rights_tier"] == "closed"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT.parent / "tradingdays-data"))
    data = Path(ap.parse_args().data)

    for rel in PUBLIC:
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(data / rel, dst)

    for panel, book in [("open/panel_open.csv", "open/columns.csv"),
                        ("open/monthly/panel_monthly_open.csv", "open/monthly/columns_monthly.csv")]:
        cols, (open_set, closed_set) = header(ROOT / panel), tiers(ROOT / book)
        leak, unknown = set(cols) & closed_set, set(cols) - open_set
        assert not leak, f"licensed columns in {panel}: {sorted(leak)}"
        assert not unknown, f"columns of {panel} not marked open in {book}: {sorted(unknown)}"
        assert len(cols) == len(open_set), f"{panel}: {len(cols)} columns, {len(open_set)} open in {book}"

    stray = [p for p in (ROOT / "closed").rglob("*") if p.is_file() and p.suffix not in (".py", ".md", ".json")]
    assert not stray, f"data files under closed/: {stray}"
    extra = sorted(str(p.relative_to(ROOT)) for d in ("open", "closed") for p in (ROOT / d).rglob("*")
                   if p.is_file() and str(p.relative_to(ROOT)) not in PUBLIC)
    assert not extra, f"files in open/ or closed/ that are not on the public list: {extra}"

    for rel in PUBLIC:
        if not rel.endswith(TEXT) or rel.startswith("LICENSE-DATA"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for pat, what in SUSPECT:
            m = re.search(pat, text, flags=re.I)
            assert not m, f"{rel}: {what}: {m.group(0)!r}"
    print(f"copied and checked {len(PUBLIC)} public files from {data}")


if __name__ == "__main__":
    main()
