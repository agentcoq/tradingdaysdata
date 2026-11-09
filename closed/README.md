# Closed tier: rebuild scripts

These 52 columns are not redistributed. Each script below downloads (or queries) its source, rebuilds one block
with exactly the construction the authors used, and writes `closed/out/<block>.csv`:

- the header is `trading_date,<block columns in panel order>`
- there is one row per trading date in `open/panel_open.csv`

Raw downloads are cached in `closed/raw/<block>/`, and an existing file there is reused rather than downloaded
again. Both `closed/out/` and `closed/raw/` are gitignored, and **must never be committed**.

Run every command from the repository root. Each script takes the same options:

- `--raw-dir DIR` uses or receives raw files in DIR
- `--offline` never downloads (or queries WRDS)
- `--out-dir DIR` writes the block to DIR (the default is `closed/out/`)

| script | block (columns) | source | credentials |
|---|---|---|---|
| `build_crsp.py` | `crsp` (13) | CRSP `crsp.dsi` via WRDS, plus the Ken French daily zips for the 2025 splice | `WRDS_USER` (required); `WRDS_PASS` (optional, otherwise `~/.pgpass` or a prompt); Duo 2FA. Or pass `--crsp-csv FILE` |
| `build_earnings.py` | `earnings` (15) | Compustat `comp.fundq`, CRSP/Compustat link table, I/B/E/S `ibes.actu_epsus`, WRDS I/B/E/S-CRSP link, CRSP daily and monthly stock files, via WRDS | `WRDS_USER` (required); `WRDS_PASS` (optional); Duo 2FA |
| `build_french.py` | `french` (7) | Ken French Data Library daily 3-factor and 5-factor (2x3) zips | none |
| `build_fred_thirdparty.py` | `fred_thirdparty` (10) | FRED VIXCLS, BAA10Y, AAA10Y, DBAA, DAAA, DGS10, SP500, TEDRATE | `FRED_API_KEY` (optional; without it, the keyless `fredgraph.csv` download is used, with identical values) |
| `build_epu.py` | `epu` (3) | FRED USEPUINDXD and USEPUINDXM | `FRED_API_KEY` (optional, as above) |
| `build_gpr.py` | `gpr` (4) | matteoiacoviello.com `data_gpr_daily_recent.dta` and `data_gpr_export.dta` | none |

Credentials are read **only from environment variables** (or the `wrds` package's own `~/.pgpass`). For
example, export them in your shell, or keep them in a local `.env` (which is gitignored) and load it yourself.
The scripts never print a credential or write one to disk. Downloaded FRED payloads are stored without the
request URL, and error messages are scrubbed of the key.

```bash
export FRED_API_KEY=...          # optional
export WRDS_USER=...             # CRSP and earnings only
python3 closed/build_french.py
python3 closed/build_fred_thirdparty.py
python3 closed/build_epu.py
python3 closed/build_gpr.py
python3 closed/build_crsp.py     # or: python3 closed/build_crsp.py --crsp-csv my_crsp_dsi.csv
python3 closed/build_earnings.py # add --validate for validation tables in closed/raw/earnings/diagnostics/
python3 closed/verify.py         # block/column SHA-256 vs expected_sha256.json
python3 build_full.py            # -> panel_full.csv
python3 closed/build_monthly.py  # monthly: panel_full.csv -> closed/out/monthly/<block>.csv (6 blocks, 64 columns)
python3 closed/verify.py --monthly
python3 build_full.py --monthly  # -> panel_monthly_full.csv
```

`build_monthly.py` aggregates the closed daily columns of `panel_full.csv` to calendar months with the rules in
`open/monthly/columns_monthly.csv`, using the same engine (`open/code/monthly/monthly_core.py`) that built the
authors' monthly panel. Given the authors' daily panel, it reproduces every closed monthly block byte for byte.
A different daily vintage gives different monthly blocks, and `verify.py --monthly` shows which columns differ.

## CRSP details

The script runs this query:

```sql
SELECT date, vwretd, vwretx, ewretd, sprtrn FROM crsp.dsi
WHERE date between 1960-01-01 and --crsp-end
```

- `--crsp-end` defaults to `2024-12-31`, the last date of the legacy `crsp.dsi` file at the authors' vintage.
  `mkt_ret` then switches to Ken French Mkt-RF + RF for the 250 sessions of 2025, and `mkt_ret_source_ff = 1` on
  those sessions. That reproduces the released splice.
- If your WRDS account no longer carries the legacy `crsp.dsi` file, export the same four fields (date, vwretd,
  ewretd, sprtrn) from the CRSP daily market index and pass them with `--crsp-csv`.
- A later CRSP vintage, or a later `--crsp-end`, gives a legitimately different block. `verify.py` will then show
  which columns differ.

## Earnings details

`build_earnings.py` pulls, in date windows, the Compustat fiscal quarters with a report date (`rdq`), the
CRSP/Compustat link table, the I/B/E/S quarterly EPS actuals with announcement dates and times, the WRDS
I/B/E/S-CRSP link, permco maps, the CRSP universe (common shares on NYSE/AMEX/Nasdaq) and market caps on t-1,
and the monthly top-500 ranking. Every pull is cached as parquet in `closed/raw/earnings/`, so an interrupted
run resumes and a complete cache makes no WRDS call (`--offline`). The construction is in the script's
docstring:

- the announcement date is the earlier of the Compustat and I/B/E/S dates;
- an announcement at or after 16:00 ET moves to the next session;
- intensity is measured over firms (CRSP permco) in the CRSP universe on the prior session;
- the coverage flags mark when the measure is reliable: `ea_cov_mcap` from the first quarter after which the
  announcing firms' share of universe market cap stays at or above 0.85, and `ea_cov_count` from the first quarter
  after which announcing firms per universe firm stay at or above 0.5;
- the ex-ante columns `eax_*` project each firm's announcement from its date for the same fiscal quarter one year
  earlier, plus 364 days (Frazzini and Lamont 2007).

The `ea_*` columns are realized (use them lagged one session in predictive work); the `eax_*` columns are known
before the session.

## What to expect relative to the authors' vintage (`expected_sha256.json`)

On 2026-09-30 every block was rebuilt with these scripts from the authors' raw inputs (for the WRDS blocks, the
authors' cached extracts, run with `--offline`). All six were byte-identical to the authors' panel, so the scripts
reproduce the construction exactly. Downloads of the public sources gave:

| block | result on 2026-09-30 | why it can drift later |
|---|---|---|
| `french` | byte-identical | The library serves only its current vintage. The files are rebuilt monthly from the latest CRSP, and past daily factor values are occasionally revised |
| `epu` | byte-identical | The daily EPU index is recomputed as newspaper archives change, and FRED mirrors the latest values |
| `gpr` | byte-identical | The GPR files are updated, and the most recent months of `gpr_monthly` are revised (a download on 2026-11-09 revised six months of 2025 by at most 1.5%) |
| `fred_thirdparty` | 9 of 10 columns byte-identical. `sp500_level_fred` has 2,326 non-missing values instead of 2,327: FRED's SP500 series keeps a rolling ten-year window, so 2016-09-29 has dropped out. Every remaining value is identical | SP500 loses a day each trading day. VIX, Moody's and TED are occasionally revised |
| `crsp` | byte-identical from the authors' CRSP extract (`--crsp-csv`) | CRSP makes annual corrections, and legacy-to-CIZ format changes may alter the last digits |
| `earnings` | byte-identical from the authors' cached WRDS pulls (`--offline`) | Compustat and I/B/E/S restate report dates and times, links change, and CRSP is revised |

On 2026-11-09 the scripts were also run on a clean machine (fresh clone, new Python 3.12 environment from
`requirements.txt`, fresh WRDS pulls). `crsp`, `earnings`, `french` and `epu` were byte-identical; `fred_thirdparty`
and `gpr` differed only in `sp500_level_fred` (ten-year window) and `gpr_monthly` (revised months).

When a block differs, `python3 closed/verify.py` reports, for each column, whether it is exact and what its
coverage is (the count of non-missing values and the first and last dates) against the expected coverage.
`build_full.py` works with any vintage. Only the final SHA-256 comparison will report "differs".
