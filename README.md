# Trading Days Data

Characteristics of every NYSE trading session from 1960 to 2025, one row per session: the calendar, scheduled
macroeconomic and monetary-policy announcements, political, sports and natural events, weather and astronomy,
attention, and market conditions. This is the dataset of *The Cross-Section of Trading Days* (Guillaume Coqueret
and Alejandro Lopez-Lira).

Website, searchable codebook and documentation: <https://www.tradingdaysdata.com>

## What this repository contains

The dataset has 408 day characteristics. The 356 columns whose sources allow it are released here as data. The
52 columns that come from licensed or third-party sources (CRSP, Compustat, I/B/E/S, the Ken French Data Library,
FRED series owned by third parties, and the EPU and GPR indices) are **not** redistributed: the scripts in
`closed/` rebuild them from your own access, and `closed/verify.py` checks your rebuild against our checksums.

```
open/
  panel_open.csv                  daily panel: trading_date + 356 open columns, 16,610 sessions, 1960-01-04 to 2025-12-31
  columns.csv                     daily codebook: every column, open and licensed (source, first date, quality,
                                  timing, license)
  monthly/panel_monthly_open.csv  monthly panel: month + 528 open columns, 792 months, 1960-01 to 2025-12
  monthly/columns_monthly.csv     monthly codebook, with the aggregation rule of each column
  supporting/wikipedia_sources.csv  the Wikipedia articles behind the CC BY-SA columns (attribution record)
closed/                           scripts that rebuild the licensed columns (code only, no data)
build_full.py                     merges the open panel with your rebuilt blocks into the full panel
NOTICE.md                         sources and the attribution each one asks for
site/, docs/                      the website and the scripts that build it and the release files
```

Each release is also published as a GitHub release and on Zenodo, with a DOI, as CSV and parquet files, and
mirrored on Hugging Face.

## Using the data

The return of session *t* runs from the close of session *t*−1 to the close of session *t*, so every event is
placed on the first session whose close comes at or after it. Columns tagged `ex_ante` in the codebook are known
before the session opens; columns tagged `realized` should be lagged by one session in forecasts. The
documentation page of the website gives the dating rules, the quality grades and the monthly aggregation.

To rebuild the full panel with the licensed columns:

```bash
pip install -r requirements.txt
python3 closed/build_french.py && python3 closed/build_epu.py && python3 closed/build_gpr.py
python3 closed/build_fred_thirdparty.py
WRDS_USER=your_username python3 closed/build_crsp.py       # needs a WRDS subscription
WRDS_USER=your_username python3 closed/build_earnings.py   # needs Compustat and I/B/E/S on WRDS
python3 closed/verify.py && python3 build_full.py
```

`closed/README.md` describes each script and its credentials, which are read from environment variables only.

## Licenses

- **Data**: per column, as recorded in the codebook (`license`). 309 open daily columns are under CC BY 4.0
  (`LICENSE-DATA-CC-BY-4.0.txt`) and the 47 columns derived from English Wikipedia under CC BY-SA 4.0
  (`LICENSE-DATA-CC-BY-SA-4.0.txt`). If you redistribute the whole open file, CC BY-SA 4.0 satisfies both.
- **Code**: MIT (`LICENSE`).
- The licensed columns that you rebuild stay under their providers' terms.

## Citation

Please cite the paper and the version of the data that you use (see `CITATION.cff` and the website).

## Updates

The data are updated once a year, in the first quarter, once the year-end data are available. Each update is a
new version with its own DOI; earlier versions are never overwritten.

## Maintaining the website and the releases

```bash
python3 site/sync_public.py --data ../tradingdays-data   # copy the public files from the authors' data repository, and check them
python3 site/make_release.py                             # release/v<version>/: CSV, parquet, codebooks, SHA256SUMS (needs pandas, pyarrow)
python3 site/build_site.py                               # regenerate docs/ (standard library only)
python3 site/make_huggingface.py                         # stage the Hugging Face mirror in release/huggingface/
HF_TOKEN=... python3 site/make_huggingface.py --push --repo OWNER/NAME   # upload it and tag v<version>
```

`sync_public.py` copies only the files on its public list and stops if a licensed column, a data file under
`closed/`, a local path, an email address or a credential would be published. `docs/` is generated; do not edit it
by hand. The site is served by GitHub Pages from `docs/` at <https://www.tradingdaysdata.com>. To publish a
release, attach the files of `release/v<version>/` to a GitHub release tagged `v<version>` (Zenodo archives it
and mints the DOI), then fill in `release` in `site/config.json`, add a line to `news`, and rebuild the site.
