#!/usr/bin/env python3
"""Stage, and optionally upload, the Hugging Face mirror of one release.

    python3 site/make_huggingface.py                                  # stage release/huggingface/ only
    HF_TOKEN=... python3 site/make_huggingface.py --push --repo OWNER/NAME

Staging reads release/v<version>/ (written by make_release.py) and writes release/huggingface/:

    README.md                                  the dataset card (YAML header with the two configs, then the text)
    data/daily/trading_days_daily_open.parquet
    data/monthly/trading_days_monthly_open.parquet
    codebook_daily.csv, codebook_monthly.csv
    LICENSE-DATA-CC-BY-4.0.txt, LICENSE-DATA-CC-BY-SA-4.0.txt, NOTICE.md

Only the open files of the release are staged; the script stops if a staged panel holds a column that its codebook
does not mark as open. --push uploads the staged folder to a Hugging Face dataset repository (created if absent)
and tags the commit v<version>, so that every version stays available. It needs `pip install huggingface_hub` and
a write token in HF_TOKEN, which is read from the environment and never printed or written to disk.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "release" / "huggingface"


def open_columns(codebook: Path) -> set[str]:
    with open(codebook, newline="", encoding="utf-8") as f:
        return {r["column"] for r in csv.DictReader(f) if r["rights_tier"] == "open"}


def card(cfg: dict, man: dict, n_closed: int) -> str:
    rel, d, m = cfg["release"], man["daily"], man["monthly"]
    site = f"https://{cfg['domain']}"
    doi = f"https://doi.org/{rel['doi']}" if rel["doi"] else "assigned on Zenodo at publication"
    authors = " and ".join(a["name"] for a in cfg["authors"])
    names = " and ".join(f"{a['name'].split()[-1]}, {' '.join(a['name'].split()[:-1])}" for a in cfg["authors"])
    return f"""---
license: cc-by-sa-4.0
pretty_name: Trading Days Data
language:
- en
tags:
- finance
- asset-pricing
- calendar
- time-series
- tabular
size_categories:
- 10K<n<100K
configs:
- config_name: daily
  data_files: data/daily/trading_days_daily_open.parquet
  default: true
- config_name: monthly
  data_files: data/monthly/trading_days_monthly_open.parquet
---

# Trading Days Data

Characteristics of every NYSE trading session from {d['first'][:4]} to {d['last'][:4]}, one row per session: the
calendar, scheduled macroeconomic and monetary-policy announcements, political, sports and natural events, weather
and astronomy, attention, and market conditions. This is the dataset of *{cfg['paper_title']}* ({authors}).

Website, searchable codebook and documentation: <{site}>. Code and rebuild scripts: <{cfg['repo_url']}>.

## Version {rel['version']}

| Config | Rows | Key | Open columns | Coverage |
|---|---|---|---|---|
| `daily` | {d['rows']:,} NYSE sessions | `trading_date` | {d['open_columns']} | {d['first']} to {d['last']} |
| `monthly` | {m['rows']} months | `month` | {m['open_columns']} | {m['first']} to {m['last']} |

DOI: {doi}. This version matches the paper. Each annual update is a new version, tagged `v<version>` in this
repository, with its own DOI; earlier versions stay available.

```python
from datasets import load_dataset
daily = load_dataset("OWNER/NAME", "daily", split="train").to_pandas()
v1 = load_dataset("OWNER/NAME", "daily", split="train", revision="v{rel['version']}")   # a given version
monthly = load_dataset("OWNER/NAME", "monthly", split="train").to_pandas()

# or with pandas only
import pandas as pd
daily = pd.read_parquet("hf://datasets/OWNER/NAME/data/daily/trading_days_daily_open.parquet")
```

## Reading the data

The return of session *t* runs from the close of session *t*−1 to the close of session *t*, so every event is
placed on the first session whose close comes at or after it. The codebooks (`codebook_daily.csv`,
`codebook_monthly.csv`) give, for every column, its source, first date with data, quality grade, timing and license.
Columns tagged `ex_ante` are known before the session opens; columns tagged `realized` should be lagged by one
session in forecasts. Monthly columns are tagged `known_at_start` or `realized_in_month`.

## What is not here

The dataset has {d['open_columns'] + n_closed} day characteristics. The {n_closed} columns built from licensed or third-party
sources (CRSP, Compustat, I/B/E/S, the Ken French Data Library, FRED series owned by third parties, and the EPU
and GPR indices) are not redistributed. They are listed in the codebook, and the scripts of
<{cfg['repo_url']}> rebuild them from your own access.

## License

The data are licensed column by column, as recorded in the codebooks: CC BY 4.0 for most columns and CC BY-SA 4.0
for the columns derived from English Wikipedia. These files contain both, so they are distributed here under
CC BY-SA 4.0, which satisfies both licenses; columns used on their own keep their own license. `NOTICE.md` lists
the sources and the attribution each one asks for.

## Citation

```bibtex
@unpublished{{coqueret2026tradingdays,
  author = {{{names}}},
  title  = {{{cfg['paper_title']}}},
  year   = {{2026}},
  note   = {{Working paper}}
}}
```
"""


def stage() -> Path:
    cfg = json.loads((ROOT / "site/config.json").read_text(encoding="utf-8"))
    src = ROOT / "release" / f"v{cfg['release']['version']}"
    man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    if STAGE.exists():
        shutil.rmtree(STAGE)          # the staging folder is generated; it holds nothing else
    (STAGE / "data/daily").mkdir(parents=True)
    (STAGE / "data/monthly").mkdir(parents=True)
    shutil.copyfile(src / "trading_days_daily_open.parquet", STAGE / "data/daily/trading_days_daily_open.parquet")
    shutil.copyfile(src / "trading_days_monthly_open.parquet", STAGE / "data/monthly/trading_days_monthly_open.parquet")
    for f in ["codebook_daily.csv", "codebook_monthly.csv"]:
        shutil.copyfile(src / f, STAGE / f)
    for f in ["LICENSE-DATA-CC-BY-4.0.txt", "LICENSE-DATA-CC-BY-SA-4.0.txt", "NOTICE.md"]:
        shutil.copyfile(ROOT / f, STAGE / f)
    with open(src / "codebook_daily.csv", newline="", encoding="utf-8") as f:
        n_closed = sum(r["rights_tier"] == "closed" for r in csv.DictReader(f))
    (STAGE / "README.md").write_text(card(cfg, man, n_closed), encoding="utf-8")

    import pandas as pd                   # the guard reads the parquet schemas
    for sub, book in [("daily", "codebook_daily.csv"), ("monthly", "codebook_monthly.csv")]:
        cols = list(pd.read_parquet(STAGE / f"data/{sub}/trading_days_{sub}_open.parquet").columns)
        bad = set(cols) - open_columns(STAGE / book)
        if bad:
            raise SystemExit(f"{sub}: columns not marked open in {book}: {sorted(bad)}")
    files = sorted(str(p.relative_to(STAGE)) for p in STAGE.rglob("*") if p.is_file())
    print(f"staged {len(files)} files in {STAGE}:", ", ".join(files))
    return STAGE


def push(repo: str, version: str):
    from huggingface_hub import HfApi    # pip install huggingface_hub
    token = os.environ["HF_TOKEN"]          # checked in main() before anything is staged
    text = (STAGE / "README.md").read_text(encoding="utf-8").replace("OWNER/NAME", repo)
    (STAGE / "README.md").write_text(text, encoding="utf-8")
    api = HfApi(token=token)
    api.create_repo(repo, repo_type="dataset", exist_ok=True)
    info = api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=str(STAGE),
                             commit_message=f"Trading Days Data, version {version}",
                             ignore_patterns=[".DS_Store", "**/.DS_Store"])
    tags = {t.name for t in api.list_repo_refs(repo, repo_type="dataset").tags}
    if f"v{version}" in tags:
        print(f"tag v{version} already exists: files updated, tag left unchanged")
    else:
        api.create_tag(repo, repo_type="dataset", tag=f"v{version}", revision=info.oid,
                       tag_message=f"version {version}")
    print(f"uploaded and tagged v{version}: https://huggingface.co/datasets/{repo}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--repo", help="Hugging Face dataset repository, OWNER/NAME")
    a = ap.parse_args()
    if a.push and not a.repo:
        ap.error("--push needs --repo OWNER/NAME")
    if a.push and not os.environ.get("HF_TOKEN"):
        ap.error("--push needs a Hugging Face write token in HF_TOKEN")
    stage()
    if a.push:
        version = json.loads((ROOT / "site/config.json").read_text())["release"]["version"]
        push(a.repo, version)


if __name__ == "__main__":
    main()
