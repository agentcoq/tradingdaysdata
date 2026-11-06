# Sources, attribution and citation

The column-level source of every column is in `open/columns.csv` (`source`, `rights_tier`, `license`,
`rights_note`). The per-file source IDs of the base release are in `open/release_v22_a18/manifest.json`, and the
pinned source vintages are in `open/release_v22_a18/BUILD_FROM_SOURCE.md`. Download provenance (URL, fetch time,
checksum, terms) of the other open-tier sources is in `open/provenance/`.

## Open tier

EventCal, named in several `source` fields, is the authors' event calendar (release v9_a18). It is a carrier of
primary-source dates, not a source in its own right: the dates it supplies here come from the Board of Governors
FOMC pages and the NY Fed target history, the BEA, BLS, Census and Treasury release and auction records, the
Congressional Research Service list of federal funding gaps, and OpenFEMA disaster declarations, each cited below.

### Base release `release_v22_a18` (55 columns, CC BY 4.0)

- NYSE session calendar: `pandas_market_calendars`, cross-checked against `exchange_calendars` and the SEC News
  Digest.
- US daylight-saving statutes, and the IANA time zone database (`tzdata`).
- Astronomy: sunrise and sunset, and lunar phase, computed with the `astral` / `ephem` Python packages.
- NOAA / NCEI:
  - Global Historical Climatology Network-Daily (Menne, M. J., I. Durre, R. S. Vose, B. E. Gleason and
    T. G. Houston, 2012, "An overview of the Global Historical Climatology Network-Daily database", *Journal of
    Atmospheric and Oceanic Technology* 29, 897-910)
  - Integrated Surface Database (ISD)
  - Historical Observing Metadata Repository (HOMR)

  These are US-government works.
- USGS ANSS Comprehensive Earthquake Catalog (ComCat), a US-government work. The reconciliation log also uses
  EMSC FDSN.
- Board of Governors of the Federal Reserve System: H.15 Selected Interest Rates (DGS10, DGS2, DTB3), and the G.17
  release dates.
- Macro release dates:
  - ALFRED, Federal Reserve Bank of St. Louis (release dates only)
  - the BLS news release archive
  - BLS, Release dates for the Producer Price Index, 1971-2025, and Historical release dates for selected BLS news
    releases (PPI release dates of 1971-1978)
  - FRASER (Federal Reserve Bank of St. Louis), for the BLS Employment Situation
  - Census Bureau MARTS release dates

### Other open columns (CC BY 4.0 unless listed under the Wikipedia section)

- **Calendar block.** Deterministic rules on the trading-day spine and closures. `is_mercury_retrograde` comes
  from a hand-listed table of Mercury-retrograde windows.
- **FOMC block.**
  - Board of Governors FOMC pages (federalreserve.gov `fomchistoricalYYYY.htm`, `fomccalendars.htm`), and the 1972
    Memoranda of Discussion and Minutes of Actions (decision days of February and April 1972)
  - the NY Fed federal funds target history
  - FRED DFEDTAR and DFEDTARU (Board of Governors)
  - the authors' EventCal release v9_a18
- **Macro block.**
  - ALFRED release and vintage dates
  - the federalreserve.gov Beige Book archive
  - U.S. Treasury FiscalData auction records
  - the EventCal release
  - rules and hand lists: ISM, Conference Board, existing home sales, and the Kansas City Fed Jackson Hole
    symposium

  Only release **dates** are used.
- **Events block, open columns.**
  - Hand-listed windows and dates compiled by the authors (war and crisis periods, major floods, pandemic
    windows) and the presidential-cycle rule.
  - EventCal release rows for US federal election days, the session on which the election result is known,
    Congressional Research Service federal funding-gap dates (government shutdowns, 1978-2024), and OpenFEMA
    major-disaster declarations (a US-government work).
  - FRED USREC (NBER recession months, `nber_recession_month`), from the NBER business-cycle reference dates.
- **Market block, open columns.** `fed_funds_eff` and `fed_funds_eff_prev` come from FRED DFF, the effective
  federal funds rate published by the Board of Governors (a US-government work).
- **Wikimedia attention block (`wpv_*`).** Wikimedia REST API pageviews and legacy pagecounts. The Wikimedia
  Foundation releases this data under CC0; the derived `wpv_*` columns are released here under CC BY 4.0.
- **ECB block (`ecb_*`).** Monetary-policy decision lists, press releases, press-conference lists and the key
  ECB interest rates table from ecb.europa.eu. Source: ECB (reuse permitted with source acknowledgement). The
  decision days were cross-checked against the Euro Area Monetary Policy Event-Study Database (Altavilla, C.,
  L. Brugnolini, R. S. Gurkaynak, R. Motto and G. Ragusa, 2019, "Measuring euro area monetary policy",
  *Journal of Monetary Economics* 108, 162-179).
- **Fed and Treasury communication block (`hh_testimony_*`, `treasury_*`).** Board of Governors testimony
  lists and pages (federalreserve.gov); FRASER, Federal Reserve Bank of St. Louis (Chair statements and
  Monetary Policy Oversight hearing records), under FRASER's terms of use; U.S. Treasury Quarterly Refunding
  archives (home.treasury.gov). US-government works.
- **FOMC cycle block (`fomc_cmvj_*`, `fomc_blackout*`).** The FOMC meeting list of the FOMC block; the FOMC
  Policy on External Communications of Committee Participants (federalreserve.gov); the cycle definition of
  Cieslak, A., A. Morse and A. Vissing-Jorgensen, 2019, "Stock returns over the FOMC cycle", *Journal of
  Finance* 74(5), 2201-2248.
- **Index rebalancing block.** FTSE Russell reconstitution notices and methodology documents; S&P Dow Jones
  Indices methodology (quarterly rebalancing rule); MSCI index-review press releases; Madhavan, A., 2003,
  "The Russell reconstitution effect", *Financial Analysts Journal* 59(4), 51-64, for the pre-2004 Russell
  dates. Only dates are used; no index data are included.
- **Market-structure block.** Presidential Task Force on Market Mechanisms (1988, "Brady Report"); CFTC-SEC
  (2010), "Findings regarding the market events of May 6, 2010"; SEC Office of Analytics and Research (2015),
  "Equity Market Volatility on August 24, 2015"; Chicago Fed Letter 131 (1998) for the circuit-breaker rules.
  English Wikipedia articles were used to cross-check the event dates, and `mwcb_regime` takes its 2013 regime
  date from Wikipedia 'Trading curb' (see the Wikipedia section).
- **Mood placebos block.**
  - Geomagnetic Kp and ap indices: GFZ German Research Centre for Geosciences, Potsdam (CC BY 4.0). Matzka, J.,
    C. Stolle, Y. Yamazaki, O. Bronkalla and A. Morschhauser, 2021, "The geomagnetic Kp index and derived
    indices of geomagnetic activity", *Space Weather* 19, e2020SW002641. Cross-checks: NOAA Space Weather
    Prediction Center daily geomagnetic data and the NOAA NGDC Kp archive (US-government works).
  - Air quality: US EPA AirData daily AQI by CBSA and county (a US-government work).
- **Payment days block.** Social Security Administration: SSA Handbook section 121 and the SSA Office of the
  Chief Actuary cyclical payment data (US-government works); federal holidays per 5 U.S.C. 6103.
- **Religious holidays block.** Dates computed with the open-source Python libraries `convertdate`, `pyluach`,
  `hijridate` (Umm al-Qura calendar), `lunardate` and `lunarcalendar`.
- **Earnings-season proxy and the other calendar-window flags** are rules stated in each column's note.

### Wikipedia-derived columns (CC BY-SA 4.0)

The 47 CC BY-SA columns (the `wiki_sports`, `wiki_political`, `wiki_disasters` and `sports_outcomes` blocks,
`pol_government_shutdown`, `pol_government_shutdown_src` and `mwcb_regime`; see `license` in
`open/columns.csv`) contain information derived from English Wikipedia articles:

> Source: Wikipedia, The Free Encyclopedia. Authors: Wikipedia contributors (see each article's history page).
> Licence: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0),
> https://creativecommons.org/licenses/by-sa/4.0/.
> Changes made: event dates and outcomes were extracted from article infoboxes, tables and text through the
> MediaWiki Action API (fetched 2026-09-29 and 2026-09-30), then mapped to NYSE trading days as described in
> each column's note.

`open/supporting/wikipedia_sources.csv` lists all 408 articles used. For each it gives the URL and history URL,
plus the revision IDs where they were recorded. The per-event records are in `open/supporting/wiki_*_events.csv`,
`open/supporting/sports_outcomes_events.csv` and `open/supporting/release_fixes_events.csv`;
`market_structure_events.csv` and `mwcb_regimes.csv` quote Wikipedia cross-check strings and are CC BY-SA 4.0
as well. If you redistribute
these columns or adaptations of them, you must keep this attribution and license the result under CC BY-SA 4.0.

The Super Bowl Indicator column `sport_sb_indicator_prev` follows Krueger, T. M. and W. F. Kennedy, 1990, "An
examination of the Super Bowl stock market predictor", *Journal of Finance* 45(2), 691-697.

## Closed tier (not redistributed; rebuilt by the user)

| source | cite / terms |
|---|---|
| CRSP daily stock index file (`crsp.dsi`) and daily/monthly stock files | Center for Research in Security Prices (CRSP), The University of Chicago Booth School of Business, accessed through Wharton Research Data Services (WRDS). Subscription required |
| Compustat quarterly fundamentals (`comp.fundq`) and the CRSP/Compustat Merged link table | S&P Global Market Intelligence, via WRDS. Subscription required |
| I/B/E/S actuals (`ibes.actu_epsus`) and the WRDS I/B/E/S-CRSP link | LSEG (Refinitiv) I/B/E/S, via WRDS. Subscription required |
| Expected announcement dates (`eax_*`) | Frazzini, A. and O. A. Lamont, 2007, "The earnings announcement premium and trading volume", NBER Working Paper 13090 |
| Kenneth R. French Data Library | https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html. Fama, E. F. and K. R. French, 1993, "Common risk factors in the returns on stocks and bonds", *Journal of Financial Economics* 33, 3-56. Fama, E. F. and K. R. French, 2015, "A five-factor asset pricing model", *Journal of Financial Economics* 116, 1-22 |
| VIX (FRED VIXCLS) | Chicago Board Options Exchange (Cboe), via FRED, Federal Reserve Bank of St. Louis. Copyrighted by Cboe |
| Moody's Baa/Aaa minus 10-year Treasury (FRED BAA10Y, AAA10Y; DBAA, DAAA) | Moody's, via FRED. Copyrighted by Moody's |
| S&P 500 index level (FRED SP500) | S&P Dow Jones Indices LLC, via FRED. Copyrighted; FRED keeps only about ten years |
| TED spread (FRED TEDRATE) | ICE Benchmark Administration (LIBOR), via FRED. Discontinued 2022-01-21 |
| Economic Policy Uncertainty (FRED USEPUINDXD, USEPUINDXM) | Baker, S. R., N. Bloom and S. J. Davis, 2016, "Measuring Economic Policy Uncertainty", *Quarterly Journal of Economics* 131(4), 1593-1636. https://www.policyuncertainty.com |
| Geopolitical Risk (GPRD, GPR, GPRH) | Caldara, D. and M. Iacoviello, 2022, "Measuring Geopolitical Risk", *American Economic Review* 112(4), 1194-1225. https://www.matteoiacoviello.com/gpr.htm |

FRED: Federal Reserve Bank of St. Louis, Federal Reserve Economic Data, https://fred.stlouisfed.org. FRED's
terms say that series owned by third parties may be subject to copyright. That is why the series above are
closed.

## Related

The two-tier layout (open data plus rebuild code for licensed inputs) follows Chen, A. Y. and T. Zimmermann, 2022,
"Open Source Cross-Sectional Asset Pricing", *Critical Finance Review* 11(2), 207-264.
