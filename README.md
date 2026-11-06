# Trading Days Data

Website and release files for the dataset of *The Cross-Section of Trading Days* (Guillaume Coqueret and
Alejandro Lopez-Lira): characteristics of every NYSE trading session from 1960, one row per session.

The site is served by GitHub Pages from `docs/`, at <https://agentcoq.github.io/tradingdaysdata/> until the domain
<https://tradingdaysdata.com> points to GitHub Pages; then set `domain_live` to `true` in `site/config.json` and rebuild,
which writes `docs/CNAME`. Every page is generated; do not edit `docs/` by hand.

## Layout

```
site/
  config.json        release version, date, DOI, download location, paper link, news
  make_release.py    builds release/v<version>/ from the data repository: daily and monthly open panels
                     (CSV and parquet), the two codebooks, SHA256SUMS and manifest.json
  build_site.py      builds docs/ from the data repository's metadata and the release manifest
  assets/            style.css and codebook.js, copied to docs/assets/
docs/                the generated website (GitHub Pages source)
release/             release files (not committed: they are attached to the GitHub release and deposited on Zenodo)
```

## Publishing a release

```bash
python3 site/make_release.py --data ../tradingdays-data   # needs pandas and pyarrow
python3 site/build_site.py --data ../tradingdays-data     # standard library only
```

Then attach the files of `release/v<version>/` to a GitHub release tagged `v<version>`, deposit the same files on
Zenodo to obtain the DOI, fill in `release.date`, `release.doi` and `release.download_base` in
`site/config.json`, add a line to `news`, and rebuild the site. A version is never overwritten: each annual
update gets a new version number and a new DOI.

`make_release.py` writes only open-tier columns and stops if a licensed column appears in the open files. The
licensed columns are rebuilt by users with the scripts of the data repository (see the site's "Licensed columns"
page).

## Licenses

Code in this repository: MIT (`LICENSE`). Data: per column, CC BY 4.0 or CC BY-SA 4.0, as recorded in the
codebook.
