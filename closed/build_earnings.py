#!/usr/bin/env python3
"""Rebuild the closed block `earnings` -> closed/out/earnings.csv  (requires WRDS: Compustat, I/B/E/S, CRSP).

Daily earnings-announcement intensity on the NYSE trading-day spine: realized ea_* columns (actual
announcements) and ex-ante eax_* columns (announcements expected from the prior year's dates).

Sources (all licensed, via WRDS; CLOSED tier, never redistributed)
  * Compustat comp.fundq.rdq (primary)           -- linked to CRSP via crsp.ccmxpf_linktable
  * I/B/E/S ibes.actu_epsus anndats/anntims (2nd) -- linked to CRSP via wrdsapps.ibcrsphist
  * CRSP daily/monthly stock files (universe, market-cap weights)
      legacy SIZ (crsp.dsf/msf + dsenames/msenames) through 2024-12-31,
      CIZ (crsp.dsf_v2/msf_v2, inline flags) for 2025 (legacy files end 2024-12-31).

Credentials come ONLY from the environment or your own configuration, never from this repository:
  WRDS_USER  (required)  your WRDS username
  WRDS_PASS  (optional)  password; if unset, the wrds package uses ~/.pgpass or prompts (Duo 2FA applies)

Construction (deterministic; every WRDS pull is cached as parquet under <raw-dir> (default closed/raw/earnings/),
so a re-run is resumable and makes no WRDS call once the cache is complete):
  1. Compustat fiscal quarters with rdq -> one row per gvkey x (fyearq, fqtr) -> CCM permno at rdq.
  2. I/B/E/S quarterly EPS actuals (US firms) -> one row per ticker x pends -> ICLINK permno at anndats.
  3. permno -> permco; both sources deduplicated to one row per permco x fiscal-period end.
  4. Firm-quarter match of the two sources: same permco, period ends within +-7 days (nearest, 1:1).
  5. Announcement date = earlier of rdq and anndats. The I/B/E/S time is used only when the chosen
     date is anndats (anndats <= rdq, or no rdq); anntims == 00:00:00 means "no time".
  6. Trading day: time known and >= 16:00 ET -> first session strictly after the date;
     otherwise the first session on or after the date (weekend/holiday -> next session).
  7. Firm-day unit = permco x trading day. Universe and weights use the PRIOR trading day t-1:
     CRSP common shares (shrcd 10/11), NYSE/AMEX/Nasdaq (exchcd 1/2/3), with valid price and shares;
     firm cap = sum of |prc|*shrout over the permco's universe securities on t-1.
  8. Top-500: permcos ranked by universe market cap at the end of the month before t's month.
  9. Expected dates (eax_*): the firm's final actual trading date for the same fiscal quarter one year
     earlier + 364 days (Frazzini-Lamont 2007), next session if non-trading.

Usage: python3 closed/build_earnings.py [--raw-dir DIR] [--offline] [--out-dir DIR] [--validate]
  --validate also writes validation tables and a figure to <raw-dir>/diagnostics/ (needs matplotlib).
WRDS data change over time (restatements, CRSP format changes), so a fresh pull can differ from the
authors' vintage; closed/verify.py reports which columns match expected_sha256.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "open" / "code"))
from common import SPINE, on_or_after, strictly_after, PANEL_PATH  # noqa: E402  (open/code/common.py)

_closed = __import__("importlib").util.spec_from_file_location("closed_common", REPO / "closed" / "common.py")
CC = __import__("importlib").util.module_from_spec(_closed)
_closed.loader.exec_module(CC)

_args = CC.parser(__doc__)
_args.add_argument("--validate", action="store_true", help="write validation tables and a figure")
ARGS = _args.parse_args()
CACHE = str(CC.raw_dir(ARGS, "earnings"))
OUT = str(Path(CACHE) / "diagnostics")
OFFLINE = ARGS.offline

SIZ_END = pd.Timestamp("2024-12-31")      # last date of legacy crsp.dsf / msf / dsenames
PERIOD_TOL_DAYS = 7                       # fiscal-period-end match tolerance (Compustat vs I/B/E/S)
COV_MCAP = 0.85                           # coverage rule thresholds (see closed/README.md)
COV_COUNT = 0.5
NEAR_DUP_DAYS = 5                         # single-source event within 5 days of another source = same release
MAX_RDQ_LAG = 365                         # rdq - datadate must lie in (0, 365] days
CLOSE = pd.Timedelta(hours=16)
VALUES_CHUNK = 10_000

_wrds = None


def wq(sql: str) -> pd.DataFrame:
    """One WRDS query over a single reused connection (credentials from the environment only)."""
    global _wrds
    if OFFLINE:
        raise SystemExit("--offline: a WRDS pull is needed but not cached in " + CACHE)
    if _wrds is None:
        user = os.environ.get("WRDS_USER", "").strip()
        if not user:
            raise SystemExit("set WRDS_USER (and optionally WRDS_PASS, or use ~/.pgpass)")
        import wrds
        kw = {"wrds_username": user}
        if os.environ.get("WRDS_PASS"):
            kw["wrds_password"] = os.environ["WRDS_PASS"]
        _wrds = wrds.Connection(**kw)
    return _wrds.raw_sql(sql)


def cached(name: str, sql_fn) -> pd.DataFrame:
    path = f"{CACHE}/{name}.parquet"
    if os.path.exists(path):
        return pd.read_parquet(path)
    sql = sql_fn()
    if OFFLINE:
        raise SystemExit(f"--offline: {name} is not cached in {CACHE}")
    print(f"  WRDS pull -> {name}", flush=True)
    df = wq(sql)
    assert len(df) < 1_000_000, f"{name}: {len(df)} rows hits the per-query budget; narrow the window"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    log = f"{CACHE}/_pull_log.jsonl"
    with open(log, "a") as f:
        f.write(json.dumps({"name": name, "rows": len(df),
                            "pulled_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "sql_md5": hashlib.md5(sql.encode()).hexdigest()}) + "\n")
    return df


def windows(y0: int, y1: int, step: int):
    for a in range(y0, y1 + 1, step):
        yield a, min(a + step - 1, y1)


# =========================================================================== 1. pulls
def pull_fundq() -> pd.DataFrame:
    parts = []
    for a, b in windows(1960, 2026, 5):
        parts.append(cached(f"fundq_{a}_{b}", lambda a=a, b=b: f"""
            SELECT gvkey, datadate, fyearq, fqtr, fyr, rdq
            FROM comp.fundq
            WHERE indfmt='INDL' AND datafmt='STD' AND popsrc='D' AND consol='C'
              AND datadate BETWEEN '{a}-01-01' AND '{b}-12-31'"""))
    return pd.concat(parts, ignore_index=True)


def pull_ccm() -> pd.DataFrame:
    return cached("ccm_link", lambda: """
        SELECT gvkey, lpermno AS permno, lpermco AS permco, linktype, linkprim, linkdt, linkenddt
        FROM crsp.ccmxpf_linktable
        WHERE linktype IN ('LU','LC') AND linkprim IN ('P','C') AND lpermno IS NOT NULL""")


def pull_ibes() -> pd.DataFrame:
    parts = []
    for a, b in windows(1976, 2026, 5):
        parts.append(cached(f"ibes_actu_qtr_{a}_{b}", lambda a=a, b=b: f"""
            SELECT ticker, cusip, pends, anndats, anntims::text AS anntims, curr_act
            FROM ibes.actu_epsus
            WHERE measure='EPS' AND pdicity='QTR' AND usfirm=1
              AND anndats BETWEEN '{a}-01-01' AND '{b}-12-31'"""))
    return pd.concat(parts, ignore_index=True)


def pull_iclink() -> pd.DataFrame:
    return cached("iclink", lambda: """
        SELECT ticker, permno, ncusip, sdate, edate, score
        FROM wrdsapps.ibcrsphist WHERE score <= 2""")


def pull_permco_map() -> pd.DataFrame:
    siz = cached("dsenames_permco", lambda: """
        SELECT DISTINCT permno, permco, namedt, nameendt FROM crsp.dsenames""")
    ciz = cached("ciz_permco", lambda: """
        SELECT DISTINCT permno, permco FROM crsp.stksecurityinfohist""")
    return siz, ciz


UNIV_SIZ = """b.shrcd IN (10,11) AND b.exchcd IN (1,2,3)
              AND a.prc IS NOT NULL AND a.prc <> 0 AND a.shrout > 0"""
UNIV_CIZ = """a.sharetype='NS' AND a.securitytype='EQTY' AND a.securitysubtype='COM'
              AND a.usincflg='Y' AND a.issuertype IN ('ACOR','CORP')
              AND a.primaryexch IN ('N','A','Q') AND a.conditionaltype='RW' AND a.tradingstatusflg='A'
              AND a.dlyprc IS NOT NULL AND a.dlyprc <> 0 AND a.shrout > 0"""
UNIV_CIZ_M = UNIV_CIZ.replace("dlyprc", "mthprc")


def pull_universe_daily() -> pd.DataFrame:
    parts = []
    for y in range(1960, 2025):
        parts.append(cached(f"univ_siz_{y}", lambda y=y: f"""
            SELECT a.date, COUNT(*) AS n_sec, COUNT(DISTINCT a.permco) AS n_firm,
                   SUM(ABS(a.prc)*a.shrout) AS cap
            FROM crsp.dsf a JOIN crsp.dsenames b
              ON a.permno=b.permno AND a.date BETWEEN b.namedt AND b.nameendt
            WHERE a.date BETWEEN '{y}-01-01' AND '{y}-12-31' AND {UNIV_SIZ}
            GROUP BY a.date""").assign(src="SIZ"))
    for y in (2024, 2025):   # 2024 = overlap for the SIZ/CIZ splice check
        parts.append(cached(f"univ_ciz_{y}", lambda y=y: f"""
            SELECT a.dlycaldt AS date, COUNT(*) AS n_sec, COUNT(DISTINCT a.permco) AS n_firm,
                   SUM(ABS(a.dlyprc)*a.shrout) AS cap
            FROM crsp.dsf_v2 a
            WHERE a.dlycaldt BETWEEN '{y}-01-01' AND '{y}-12-31' AND {UNIV_CIZ}
            GROUP BY a.dlycaldt""").assign(src="CIZ"))
    u = pd.concat(parts, ignore_index=True)
    u["date"] = pd.to_datetime(u["date"])
    return u


def pull_top500() -> pd.DataFrame:
    parts = []
    for a, b in windows(1960, 2024, 10):
        parts.append(cached(f"top500_siz_{a}_{b}", lambda a=a, b=b: f"""
            WITH c AS (
              SELECT a.permco, a.date, SUM(ABS(a.prc)*a.shrout) AS cap
              FROM crsp.msf a JOIN crsp.msenames b
                ON a.permno=b.permno AND a.date BETWEEN b.namedt AND b.nameendt
              WHERE a.date BETWEEN '{a}-01-01' AND '{b}-12-31' AND {UNIV_SIZ}
              GROUP BY a.permco, a.date),
            r AS (SELECT permco, date, cap, RANK() OVER (PARTITION BY date ORDER BY cap DESC) AS rk FROM c)
            SELECT permco, date, cap, rk FROM r WHERE rk <= 500""").assign(src="SIZ"))
    parts.append(cached("top500_ciz_2024_2025", lambda: f"""
        WITH c AS (
          SELECT a.permco, a.mthcaldt AS date, SUM(ABS(a.mthprc)*a.shrout) AS cap
          FROM crsp.msf_v2 a
          WHERE a.mthcaldt BETWEEN '2024-01-01' AND '2025-12-31' AND {UNIV_CIZ_M}
          GROUP BY a.permco, a.mthcaldt),
        r AS (SELECT permco, date, cap, RANK() OVER (PARTITION BY date ORDER BY cap DESC) AS rk FROM c)
        SELECT permco, date, cap, rk FROM r WHERE rk <= 500""").assign(src="CIZ"))
    t = pd.concat(parts, ignore_index=True)
    t["date"] = pd.to_datetime(t["date"])
    return t


def pull_firm_caps(pairs: pd.DataFrame) -> pd.DataFrame:
    """Universe market cap on date d (= t-1) for each (permco, d), via VALUES joins in chunks."""
    pairs = pairs.drop_duplicates().sort_values(["d", "permco"]).reset_index(drop=True)
    out = []
    # chunks = calendar quarter of d (split further at VALUES_CHUNK); the file name carries a hash of the
    # chunk content, so a changed event set re-pulls only the quarters it touches
    for q, g in pairs.groupby(pairs["d"].dt.to_period("Q")):
        yr = q.year
        g = g.reset_index(drop=True)
        for k in range(0, len(g), VALUES_CHUNK):
            c = g.iloc[k:k + VALUES_CHUNK]
            vals = ",".join(f"({int(p)},DATE '{d:%Y-%m-%d}')" for p, d in zip(c.permco, c.d))
            h = hashlib.md5(vals.encode()).hexdigest()[:10]
            if yr <= SIZ_END.year:
                sql = f"""WITH v(permco, d) AS (VALUES {vals})
                    SELECT v.permco, v.d, COUNT(*) AS n_sec, SUM(ABS(a.prc)*a.shrout) AS cap
                    FROM v JOIN crsp.dsf a ON a.permco=v.permco AND a.date=v.d
                    JOIN crsp.dsenames b ON a.permno=b.permno AND a.date BETWEEN b.namedt AND b.nameendt
                    WHERE {UNIV_SIZ} GROUP BY v.permco, v.d"""
            else:
                sql = f"""WITH v(permco, d) AS (VALUES {vals})
                    SELECT v.permco, v.d, COUNT(*) AS n_sec, SUM(ABS(a.dlyprc)*a.shrout) AS cap
                    FROM v JOIN crsp.dsf_v2 a ON a.permco=v.permco AND a.dlycaldt=v.d
                    WHERE {UNIV_CIZ} GROUP BY v.permco, v.d"""
            out.append(cached(f"caps/caps_{q}_{k // VALUES_CHUNK:02d}_{h}", lambda sql=sql: sql))
    caps = pd.concat(out, ignore_index=True)
    caps["d"] = pd.to_datetime(caps["d"])
    return caps


# =========================================================================== 2. events
def link_compustat(fq: pd.DataFrame, ccm: pd.DataFrame, log: dict) -> pd.DataFrame:
    fq = fq.copy()
    for c in ("datadate", "rdq"):
        fq[c] = pd.to_datetime(fq[c])
    log["fundq_rows"] = len(fq)
    fq = fq.dropna(subset=["rdq"])
    log["fundq_rows_with_rdq"] = len(fq)
    lag = (fq["rdq"] - fq["datadate"]).dt.days
    log["rdq_dropped_lag_le0"] = int((lag <= 0).sum())
    log["rdq_dropped_lag_gt365"] = int((lag > MAX_RDQ_LAG).sum())
    fq = fq[(lag > 0) & (lag <= MAX_RDQ_LAG)]
    # one announcement per gvkey x fiscal quarter; a fiscal-year-end change can leave two
    # datadates for one (fyearq, fqtr): keep the later datadate (current fiscal calendar),
    # then earliest rdq as a deterministic tie-break.
    fq = fq.sort_values(["gvkey", "fyearq", "fqtr", "datadate", "rdq"], ascending=[True, True, True, False, True])
    nq = fq["fyearq"].isna() | fq["fqtr"].isna()
    a = fq[~nq].drop_duplicates(["gvkey", "fyearq", "fqtr"])
    b = fq[nq].drop_duplicates(["gvkey", "datadate"])
    fq = pd.concat([a, b]).drop_duplicates(["gvkey", "datadate"])
    log["compustat_firm_quarters"] = len(fq)
    # CCM link valid on rdq
    ccm = ccm.copy()
    ccm["linkdt"] = pd.to_datetime(ccm["linkdt"])
    ccm["linkenddt"] = pd.to_datetime(ccm["linkenddt"]).fillna(pd.Timestamp("2099-12-31"))
    m = fq.merge(ccm, on="gvkey", how="inner")
    m = m[(m["rdq"] >= m["linkdt"]) & (m["rdq"] <= m["linkenddt"])]
    m["_p"] = (m["linkprim"] != "P").astype(int)   # prefer primary link
    m["_t"] = (m["linktype"] != "LC").astype(int)   # then LC over LU
    m = m.sort_values(["gvkey", "datadate", "_p", "_t", "permno"]).drop_duplicates(["gvkey", "datadate"])
    log["compustat_linked"] = len(m)
    return m[["gvkey", "permno", "datadate", "rdq"]].rename(columns={"datadate": "pend_c"})


def link_ibes(ib: pd.DataFrame, icl: pd.DataFrame, log: dict) -> pd.DataFrame:
    ib = ib.copy()
    ib["pends"] = pd.to_datetime(ib["pends"])
    ib["anndats"] = pd.to_datetime(ib["anndats"])
    ib = ib.dropna(subset=["ticker", "pends", "anndats"])
    log["ibes_rows"] = len(ib)
    t = pd.to_timedelta(ib["anntims"].fillna("00:00:00"))
    ib["time_known"] = t > pd.Timedelta(0)
    ib["anntime"] = t.where(ib["time_known"])
    # one announcement per ticker x period end (currencies collapse): earliest date, then earliest known time
    ib = ib.sort_values(["ticker", "pends", "anndats", "time_known", "anntime"],
                        ascending=[True, True, True, False, True])
    ib = ib.drop_duplicates(["ticker", "pends"])
    log["ibes_firm_quarters"] = len(ib)
    icl = icl.copy()
    icl["sdate"] = pd.to_datetime(icl["sdate"])
    icl["edate"] = pd.to_datetime(icl["edate"])
    m = ib.merge(icl[["ticker", "permno", "sdate", "edate", "score"]], on="ticker", how="inner")
    m = m[(m["anndats"] >= m["sdate"]) & (m["anndats"] <= m["edate"])]
    m = m.sort_values(["ticker", "pends", "score", "permno"]).drop_duplicates(["ticker", "pends"])
    log["ibes_linked"] = len(m)
    return m[["ticker", "permno", "pends", "anndats", "time_known", "anntime"]].rename(columns={"pends": "pend_i"})


def add_permco(df: pd.DataFrame, datecol: str, siz: pd.DataFrame, ciz: pd.DataFrame) -> pd.DataFrame:
    siz = siz.copy()
    siz["namedt"] = pd.to_datetime(siz["namedt"])
    siz["nameendt"] = pd.to_datetime(siz["nameendt"])
    df = df.reset_index(drop=True).copy()
    df["_row"] = np.arange(len(df))
    m = df[["_row", "permno", datecol]].merge(siz, on="permno", how="left")
    m["_in"] = (m[datecol] >= m["namedt"]) & (m[datecol] <= m["nameendt"])
    m["_gap"] = np.where(m["_in"], 0, np.minimum((m[datecol] - m["nameendt"]).abs().dt.days,
                                                (m[datecol] - m["namedt"]).abs().dt.days))
    m = m.sort_values(["_row", "_gap"]).drop_duplicates("_row")
    df["permco"] = df["_row"].map(m.set_index("_row")["permco"])
    # permnos first listed after the legacy files end: CIZ header map (unique permno->permco required)
    cz = ciz.drop_duplicates("permno", keep=False).set_index("permno")["permco"]
    miss = df["permco"].isna()
    df.loc[miss, "permco"] = df.loc[miss, "permno"].map(cz)
    return df.drop(columns="_row")


def match_sources(c: pd.DataFrame, i: pd.DataFrame, log: dict) -> pd.DataFrame:
    """1:1 nearest match on permco and fiscal-period end within +-PERIOD_TOL_DAYS."""
    c = c.dropna(subset=["permco"]).copy()
    i = i.dropna(subset=["permco"]).copy()
    c["permco"] = c["permco"].astype("int64")
    i["permco"] = i["permco"].astype("int64")
    # a permco can carry two gvkeys / two tickers for one period: keep the earliest announcement
    c = c.sort_values(["permco", "pend_c", "rdq", "gvkey"]).drop_duplicates(["permco", "pend_c"])
    i = i.sort_values(["permco", "pend_i", "anndats", "ticker"]).drop_duplicates(["permco", "pend_i"])
    log["compustat_permco_quarters"] = len(c)
    log["ibes_permco_quarters"] = len(i)
    c["cid"] = np.arange(len(c))
    i["iid"] = np.arange(len(i))
    # all candidate pairs within tolerance (merge on permco and a week bucket, then filter)
    cand = []
    for off in range(-PERIOD_TOL_DAYS, PERIOD_TOL_DAYS + 1):
        k = c[["cid", "permco", "pend_c"]].assign(pend_i=c["pend_c"] + pd.Timedelta(days=off))
        cand.append(k.merge(i[["iid", "permco", "pend_i"]], on=["permco", "pend_i"]))
    cand = pd.concat(cand, ignore_index=True)
    cand["dist"] = (cand["pend_i"] - cand["pend_c"]).dt.days.abs()
    # greedy 1:1 by distance (deterministic tie-breaks)
    cand = cand.sort_values(["dist", "cid", "iid"])
    used_c, used_i, keep = set(), set(), []
    for cid, iid in zip(cand["cid"].to_numpy(), cand["iid"].to_numpy()):
        if cid in used_c or iid in used_i:
            continue
        used_c.add(cid); used_i.add(iid); keep.append((cid, iid))
    pairs = pd.DataFrame(keep, columns=["cid", "iid"])
    both = pairs.merge(c, on="cid").merge(i.drop(columns="permco"), on="iid")
    both["period_gap_days"] = (both["pend_i"] - both["pend_c"]).dt.days
    c_only = c[~c["cid"].isin(pairs["cid"])]
    i_only = i[~i["iid"].isin(pairs["iid"])]
    log["matched_firm_quarters"] = len(both)
    log["compustat_only"] = len(c_only)
    log["ibes_only"] = len(i_only)
    ev = pd.concat([both.assign(src="both"), c_only.assign(src="compustat"), i_only.assign(src="ibes")],
                   ignore_index=True)
    ev["time_known"] = ev["time_known"].astype("boolean").fillna(False).astype(bool)
    return ev


def date_events(ev: pd.DataFrame, log: dict) -> pd.DataFrame:
    ev = ev.copy()
    use_i = ev["anndats"].notna() & (ev["rdq"].isna() | (ev["anndats"] <= ev["rdq"]))
    ev["ann_date"] = np.where(use_i, ev["anndats"], ev["rdq"])
    ev["ann_date"] = pd.to_datetime(ev["ann_date"])
    ev["date_from"] = np.where(use_i, np.where(ev["rdq"].notna() & (ev["anndats"] == ev["rdq"]), "both_equal", "ibes"),
                               "compustat")
    # the I/B/E/S time applies only when the chosen date is the I/B/E/S date
    # near-duplicates: a single-source event (I/B/E/S-only or Compustat-only) whose date lies within
    # NEAR_DUP_DAYS calendar days of an event of the same permco from a different source is the same
    # announcement recorded under another fiscal period (typically I/B/E/S logging a prior/other-quarter
    # actual at the same release). It is dropped so the firm is not counted on two nearby days.
    # Anchor = a matched ("both") event, which always wins. When the neighbour is itself single-source
    # (I/B/E/S-only vs Compustat-only), only one of the pair is dropped: the later-dated one, or the
    # I/B/E/S one on a same-day tie (consistent with the earlier-of rule).
    ev["_eid"] = np.arange(len(ev))
    single = ev[ev["src"] != "both"][["_eid", "permco", "ann_date", "src"]]
    other = ev[["permco", "ann_date", "src"]].rename(columns={"ann_date": "d2", "src": "src2"})
    mm = single.merge(other, on="permco")
    mm = mm[(mm["src2"] != mm["src"]) & ((mm["d2"] - mm["ann_date"]).dt.days.abs() <= NEAR_DUP_DAYS)]
    loses = (mm["src2"] == "both") | (mm["d2"] < mm["ann_date"]) | \
            ((mm["d2"] == mm["ann_date"]) & (mm["src"] == "ibes"))
    drop = set(mm.loc[loses, "_eid"])
    log["near_duplicate_single_source_dropped"] = {s: int(ev.loc[ev["_eid"].isin(drop), "src"].eq(s).sum())
                                                   for s in ("ibes", "compustat")}
    ev = ev[~ev["_eid"].isin(drop)].drop(columns="_eid").copy()
    use_i = use_i.loc[ev.index]
    ev["time_known"] = use_i & ev["time_known"]
    ev["anntime"] = ev["anntime"].where(ev["time_known"])
    ev["after_close"] = ev["time_known"] & (ev["anntime"] >= CLOSE)
    d_on = on_or_after(ev["ann_date"]).to_numpy()
    d_af = strictly_after(ev["ann_date"]).to_numpy()
    ev["trading_date"] = np.where(ev["after_close"], d_af, d_on)
    ev["trading_date"] = pd.to_datetime(ev["trading_date"])
    ev["trading_date_noshift"] = pd.to_datetime(d_on)
    ev["shifted_after_close"] = ev["trading_date"] != ev["trading_date_noshift"]
    ev["nontrading_date"] = pd.to_datetime(d_on) != ev["ann_date"]
    log["events_total"] = len(ev)
    log["events_beyond_spine"] = int(ev["trading_date"].isna().sum())
    ev = ev.dropna(subset=["trading_date"])
    ev = ev[ev["trading_date"] >= SPINE[1]]
    pos = SPINE.searchsorted(ev["trading_date"])
    ev["prev_date"] = SPINE[pos - 1]
    return ev


# =========================================================================== 3. main
def main() -> None:
    log: dict = {}
    print("pulling / loading cache ...", flush=True)
    fq, ccm, ib, icl = pull_fundq(), pull_ccm(), pull_ibes(), pull_iclink()
    siz_pc, ciz_pc = pull_permco_map()
    univ = pull_universe_daily()
    top = pull_top500()

    c = link_compustat(fq, ccm, log)
    i = link_ibes(ib, icl, log)
    c = add_permco(c, "rdq", siz_pc, ciz_pc)
    i = add_permco(i, "anndats", siz_pc, ciz_pc)
    ev = match_sources(c, i, log)
    ev = date_events(ev, log)

    caps = pull_firm_caps(ev[["permco", "prev_date"]].rename(columns={"prev_date": "d"})
                          .astype({"permco": "int64"}))
    ev = ev.merge(caps.rename(columns={"d": "prev_date", "cap": "cap_prev"})[["permco", "prev_date", "cap_prev"]],
                  on=["permco", "prev_date"], how="left")
    ev["in_universe"] = ev["cap_prev"].notna()

    # top-500 at the end of the month preceding the trading date's month
    top_all = top.copy()
    top = top.copy()
    top["ym"] = top["date"].dt.to_period("M")
    top = top[(top["src"] == "SIZ") | (top["date"] > SIZ_END)]
    top_set = set(zip(top["permco"].astype("int64"), top["ym"]))
    ym_prev = ev["trading_date"].dt.to_period("M") - 1
    ev["top500"] = [(p, y) in top_set for p, y in zip(ev["permco"].astype("int64"), ym_prev)]

    # firm-day (permco x trading day) unit
    ev = ev.sort_values(["permco", "trading_date", "ann_date"])
    fd = ev.groupby(["permco", "trading_date"], as_index=False).agg(
        cap_prev=("cap_prev", "first"), in_universe=("in_universe", "max"), top500=("top500", "max"),
        time_known=("time_known", "max"), shifted=("shifted_after_close", "max"),
        nontrading=("nontrading_date", "max"), n_events=("src", "size"))
    log["firm_days"] = len(fd)
    log["firm_days_multi_event"] = int((fd["n_events"] > 1).sum())
    log["firm_days_not_in_universe"] = int((~fd["in_universe"]).sum())
    fu = fd[fd["in_universe"]]

    # universe totals on t-1 (SIZ through 2024-12-31, CIZ afterwards)
    u = univ[((univ["src"] == "SIZ") & (univ["date"] <= SIZ_END)) | ((univ["src"] == "CIZ") & (univ["date"] > SIZ_END))]
    u = u.set_index("date").sort_index()
    assert u.index.is_unique
    prev = pd.Series(SPINE[:-1], index=SPINE[1:])
    tot_prev = prev.map(u["cap"]).reindex(SPINE)
    nfirm_prev = prev.map(u["n_firm"]).reindex(SPINE)

    g = fu.groupby("trading_date")
    day = pd.DataFrame(index=SPINE)
    day["ea_count"] = g.size().reindex(SPINE).fillna(0)
    day["ea_mcap_share"] = g["cap_prev"].sum().reindex(SPINE).fillna(0) / tot_prev
    day["ea_count_top500"] = g["top500"].sum().reindex(SPINE).fillna(0)
    day["ea_share_time_known"] = g["time_known"].mean().reindex(SPINE)
    day["ea_n_shifted_after_close"] = g["shifted"].sum().reindex(SPINE).fillna(0)
    day["ea_universe_n_prev"] = nfirm_prev

    # coverage rules (documented in closed/README.md), both on calendar quarters of the trading date:
    #  * mcap coverage = sum of announcers' t-1 caps in the quarter / quarter-average universe cap
    #    (each firm announces about once a quarter); ea_cov_mcap = 1 from the first quarter after
    #    which it stays >= COV_MCAP for every later quarter.
    #  * count coverage = distinct announcing permcos / quarter-average universe firms; ea_cov_count = 1
    #    from the first quarter after which it stays >= COV_COUNT.
    qkey = fu["trading_date"].dt.to_period("Q")
    tot_q = tot_prev.groupby(SPINE.to_period("Q")).mean()
    uq = nfirm_prev.groupby(SPINE.to_period("Q")).mean()
    cov_tab = pd.DataFrame({"announcing_firms": fu.groupby(qkey)["permco"].nunique(),
                            "universe_firms_avg": uq,
                            "mcap_coverage": fu.groupby(qkey)["cap_prev"].sum() / tot_q})
    cov_tab["announcing_firms"] = cov_tab["announcing_firms"].fillna(0)
    cov_tab["count_coverage"] = cov_tab["announcing_firms"] / cov_tab["universe_firms_avg"]
    cov_tab = cov_tab.dropna(subset=["universe_firms_avg"])

    def stays_above(r: pd.Series, thr: float) -> pd.Timestamp:
        r = r.fillna(0)
        bad = r[r < thr]
        return (r.index[r.index > bad.index.max()][0] if len(bad) else r.index[0]).start_time

    cov_start = stays_above(cov_tab["mcap_coverage"], COV_MCAP)
    cnt_start = stays_above(cov_tab["count_coverage"], COV_COUNT)
    first_data = fu["trading_date"].min()
    ibes_start = pd.Timestamp("1983-01-03")
    # time-stamp coverage: first calendar year in which >= 50% of IBES-dated events carry a time
    tk = ev[ev["date_from"] != "compustat"].groupby(ev["ann_date"].dt.year)["time_known"].mean()
    time_year = int(tk[tk >= 0.5].index.min())
    time_start = pd.Timestamp(f"{time_year}-01-01")
    log.update(coverage_start_mcap=str(cov_start.date()), coverage_start_count=str(cnt_start.date()), first_data=str(first_data.date()),
               time_coverage_start=str(time_start.date()))

    pre = day.index < first_data
    for col in ["ea_count", "ea_mcap_share", "ea_count_top500", "ea_share_time_known", "ea_n_shifted_after_close"]:
        day.loc[pre, col] = np.nan
    day["ea_cov_mcap"] = (day.index >= cov_start).astype(float)
    day["ea_cov_count"] = (day.index >= cnt_start).astype(float)
    day["ea_cov_ibes"] = (day.index >= ibes_start).astype(float)
    day["ea_cov_times"] = (day.index >= time_start).astype(float)
    day["ea_crsp_ciz"] = (prev.reindex(SPINE) > SIZ_END).astype(float)  # t-1 after 2024-12-31 -> CIZ

    # ---------------------------------------------------------------- ex-ante expected intensity (eax_*)
    proj, eax_start = build_expected(ev, top_set, tot_prev, day, cov_start, first_data, log)

    # ---------------------------------------------------------------- meta
    src_ea = ("Compustat comp.fundq.rdq + I/B/E/S ibes.actu_epsus anndats/anntims (earlier date); "
              "CCM / ICLINK links; CRSP universe")
    cs, fdd = str(cov_start.date()), str(first_data.date())
    common_note = (f"values from {fdd}; ea_cov_mcap=1 from {cs}, ea_cov_count=1 from {cnt_start.date()}. Firm = CRSP permco; universe on t-1 = "
                   "shrcd 10/11, exchcd 1/2/3 (CIZ equivalents in 2025)")
    meta = [
        dict(column="ea_count", source=src_ea, coverage_start=fdd, quality="exact-source",
             note="number of announcing firms (permco) in the CRSP universe on t-1; " + common_note),
        dict(column="ea_mcap_share", source=src_ea + "; CRSP dsf |prc|*shrout on t-1", coverage_start=fdd,
             quality="exact-source",
             note="sum of t-1 market cap of announcers / total t-1 universe market cap; " + common_note),
        dict(column="ea_count_top500", source=src_ea + "; CRSP msf rank", coverage_start=fdd, quality="exact-source",
             note="announcers among the 500 largest permcos by universe market cap at the end of the previous "
                  "calendar month; " + common_note),
        dict(column="ea_share_time_known", source="I/B/E/S anntims", coverage_start=fdd, quality="exact-source",
             note=f"share of the day's announcing firms with a known I/B/E/S time (anntims != 00:00) on the "
                  f"chosen date; blank on days with no announcer; times effectively start {time_year}"),
        dict(column="ea_n_shifted_after_close", source="I/B/E/S anntims", coverage_start=fdd, quality="exact-source",
             note="announcing firms moved to this day from the prior calendar day's after-close (>=16:00 ET) release"),
        dict(column="ea_universe_n_prev", source="CRSP dsf/dsenames (SIZ) to 2024-12-31; dsf_v2 (CIZ) 2025",
             coverage_start="1960-01-05", quality="exact-source",
             note="number of permcos in the CRSP universe on t-1 (denominator context)"),
        dict(column="ea_cov_mcap", source="rule", coverage_start="1960-01-04", quality="rule",
             note=f"1 from {cs}: first quarter after which the quarterly market-cap share of the universe that "
                  f"announces stays >= {COV_MCAP}"),
        dict(column="ea_cov_count", source="rule", coverage_start="1960-01-04", quality="rule",
             note=f"1 from {cnt_start.date()}: first quarter after which announcing firms / universe firms per "
                  f"quarter stays >= {COV_COUNT}; before it ea_count under-covers small (mostly Nasdaq) firms"),
        dict(column="ea_cov_ibes", source="rule", coverage_start="1960-01-04", quality="rule",
             note="1 from 1983-01-03: I/B/E/S quarterly actuals (second source) available"),
        dict(column="ea_cov_times", source="rule", coverage_start="1960-01-04", quality="rule",
             note=f"1 from {time_start.date()}: first year with >=50% of I/B/E/S-dated announcements time-stamped; "
                  "before this the after-close shift is effectively inactive"),
        dict(column="ea_crsp_ciz", source="rule", coverage_start="1960-01-04", quality="rule",
             note="1 when t-1 weights/universe come from CRSP CIZ (dsf_v2), i.e. trading dates in 2025"),
    ]
    src_eax = ("prior-year actual announcement dates (this block's ea_* event file) + 364 days "
               "(Frazzini-Lamont 2007); CRSP t-1 caps")
    eax_note = (f"values from {(first_data + pd.Timedelta(days=364)).date()}; eax_cov=1 from {eax_start.date()}. "
                "Expected date = the firm's final (after-close-shifted) actual trading date for the same fiscal "
                "quarter one year earlier + 364 days, next session if non-trading; only information known before t")
    meta += [
        dict(column="eax_count", source=src_eax, coverage_start=str((first_data + pd.Timedelta(days=364)).date()),
             quality="rule", note="number of firms (permco, in universe on t-1) EXPECTED to announce on t; " + eax_note),
        dict(column="eax_mcap_share", source=src_eax, coverage_start=str((first_data + pd.Timedelta(days=364)).date()),
             quality="rule", note="t-1 cap of expected announcers / total t-1 universe cap; " + eax_note),
        dict(column="eax_count_top500", source=src_eax + "; CRSP msf rank",
             coverage_start=str((first_data + pd.Timedelta(days=364)).date()), quality="rule",
             note="expected announcers in the top 500 permcos by universe cap at the end of the month before t's "
                  "month (the same pre-t ranking as ea_count_top500); " + eax_note),
        dict(column="eax_cov", source="rule", coverage_start="1960-01-04", quality="rule",
             note=f"1 from {eax_start.date()} = ea_cov_mcap start + 1 year (a full prior year of actual dates exists)"),
    ]
    realized = {"ea_count", "ea_mcap_share", "ea_count_top500", "ea_share_time_known", "ea_n_shifted_after_close"}
    for m in meta:
        tag = "realized" if m["column"] in realized else "ex_ante"
        m.update(rights_tier="closed", license="WRDS subscription (CRSP, Compustat, I/B/E/S); not redistributable",
                 timing=tag)
    write_earnings_block(day[[m["column"] for m in meta]])

    # ---------------------------------------------------------------- validation (optional)
    if ARGS.validate:
        os.makedirs(OUT, exist_ok=True)
        pd.DataFrame(meta).to_csv(f"{OUT}/columns_earnings.csv", index=False)
        validate(ev, fd, day, univ, top_all, cov_tab, log)
        validate_expected(ev, proj, day, log)
        with open(f"{OUT}/build_log.json", "w") as f:
            json.dump(log, f, indent=1, default=str)
    print(json.dumps(log, indent=1, default=str))


def write_earnings_block(df: pd.DataFrame) -> None:
    """closed/out/earnings.csv in the authors' cell format (floats written with '%.6g')."""
    cols = CC.blocks()["earnings"]
    assert list(df.columns) == cols, (list(df.columns), cols)
    assert df.index.equals(SPINE)
    out = df.copy()
    out.index.name = "trading_date"
    out = out.reset_index()
    out["trading_date"] = out["trading_date"].dt.strftime("%Y-%m-%d")
    assert list(out["trading_date"]) == list(CC.spine()["trading_date"])
    ARGS.out_dir.mkdir(parents=True, exist_ok=True)
    dst = ARGS.out_dir / "earnings.csv"
    out.to_csv(dst, index=False, float_format="%.6g", lineterminator="\n")
    print(f"wrote {dst} ({len(out)} rows, {len(cols)} columns)")


EXP_PERIOD_TOL_DAYS = 10   # actual vs projected fiscal-period end (52/53-week years, Feb 29)


def build_expected(ev, top_set, tot_prev, day, cov_start, first_data, log):
    """Ex-ante expected announcements (Frazzini-Lamont 2007).

    Each actual firm-fiscal-quarter (permco, period end P, final trading date D) projects one expected
    announcement for fiscal period P + 1 year on the first session on or after D + 364 days. Only information
    dated D (one year before) is used; universe membership and weights come from t-1 of the expected day,
    and the top-500 set from the month-end before the expected day's month. A firm-quarter whose firm had no
    actual date for the same quarter a year earlier gets no expected date (first-year firms are excluded).
    """
    b = ev.copy()
    b["pend"] = b["pend_c"].fillna(b["pend_i"])
    b = b.sort_values(["permco", "pend", "trading_date"]).drop_duplicates(["permco", "pend"])
    proj = pd.DataFrame({"permco": b["permco"].astype("int64").to_numpy(),
                         "pend_next": (b["pend"] + pd.DateOffset(years=1)).to_numpy(),
                         "src_date": b["trading_date"].to_numpy()})
    proj["exp_td"] = on_or_after(proj["src_date"] + pd.Timedelta(days=364)).to_numpy()
    proj = proj.dropna(subset=["exp_td"])
    proj = proj[proj["exp_td"] >= SPINE[1]].copy()
    pos = SPINE.searchsorted(proj["exp_td"])
    proj["exp_prev"] = SPINE[pos - 1]
    assert (proj["exp_prev"] < proj["exp_td"]).all() and (proj["src_date"] < proj["exp_prev"]).all()
    caps = pull_firm_caps(proj[["permco", "exp_prev"]].rename(columns={"exp_prev": "d"}))
    proj = proj.merge(caps.rename(columns={"d": "exp_prev", "cap": "cap_prev"})[["permco", "exp_prev", "cap_prev"]],
                      on=["permco", "exp_prev"], how="left")
    proj["in_universe"] = proj["cap_prev"].notna()
    ym_prev = proj["exp_td"].dt.to_period("M") - 1
    proj["top500"] = [(p, y) in top_set for p, y in zip(proj["permco"], ym_prev)]
    log["eax_projections"] = len(proj)
    log["eax_projections_in_universe"] = int(proj["in_universe"].sum())

    pu = proj[proj["in_universe"]].sort_values(["permco", "exp_td"])
    pfd = pu.groupby(["permco", "exp_td"], as_index=False).agg(cap_prev=("cap_prev", "first"),
                                                                top500=("top500", "max"))
    log["eax_firm_days"] = len(pfd)
    g = pfd.groupby("exp_td")
    day["eax_count"] = g.size().reindex(SPINE).fillna(0)
    day["eax_mcap_share"] = g["cap_prev"].sum().reindex(SPINE).fillna(0) / tot_prev
    day["eax_count_top500"] = g["top500"].sum().reindex(SPINE).fillna(0)
    pre = day.index < first_data + pd.Timedelta(days=364)
    day.loc[pre, ["eax_count", "eax_mcap_share", "eax_count_top500"]] = np.nan
    eax_start = cov_start + pd.DateOffset(years=1)
    day["eax_cov"] = (day.index >= eax_start).astype(float)
    log["eax_cov_start"] = str(eax_start.date())
    return proj, eax_start


def validate_expected(ev, proj, day, log) -> None:
    d = day[day["eax_cov"] == 1]
    dec = decade(pd.Series(d.index, index=d.index))
    rows = []
    for k, g in d.groupby(dec):
        rows.append(dict(decade=k, days=len(g),
                         corr_mcap_share=g["eax_mcap_share"].corr(g["ea_mcap_share"]),
                         corr_count=g["eax_count"].corr(g["ea_count"]),
                         corr_top500=g["eax_count_top500"].corr(g["ea_count_top500"]),
                         mean_ea_mcap_share=g["ea_mcap_share"].mean(), mean_eax_mcap_share=g["eax_mcap_share"].mean()))
    allr = dict(decade="all", days=len(d), corr_mcap_share=d["eax_mcap_share"].corr(d["ea_mcap_share"]),
                corr_count=d["eax_count"].corr(d["ea_count"]),
                corr_top500=d["eax_count_top500"].corr(d["ea_count_top500"]),
                mean_ea_mcap_share=d["ea_mcap_share"].mean(), mean_eax_mcap_share=d["eax_mcap_share"].mean())
    rows.append(allr)
    pd.DataFrame(rows).round(4).to_csv(f"{OUT}/validation_eax_correlation.csv", index=False)
    log["eax_corr_mcap_share_all"] = round(float(allr["corr_mcap_share"]), 4)

    # actual in-universe firm-quarters vs their own projected date (same permco, fiscal period within tol)
    a = ev[ev["in_universe"] & (ev["trading_date"] >= pd.Timestamp(log["eax_cov_start"]))].copy()
    a["pend"] = a["pend_c"].fillna(a["pend_i"])
    a["aid"] = np.arange(len(a))
    p = proj[["permco", "pend_next", "exp_td"]].copy()
    cand = []
    for off in range(-EXP_PERIOD_TOL_DAYS, EXP_PERIOD_TOL_DAYS + 1):
        k = a[["aid", "permco", "pend"]].assign(pend_next=a["pend"] + pd.Timedelta(days=off))
        cand.append(k.merge(p, on=["permco", "pend_next"]))
    cand = pd.concat(cand, ignore_index=True)
    cand["pdist"] = (cand["pend_next"] - cand["pend"]).dt.days.abs()
    cand = cand.sort_values(["aid", "pdist", "exp_td"]).drop_duplicates("aid")
    a = a.merge(cand[["aid", "exp_td"]], on="aid", how="left")
    a["has_prior"] = a["exp_td"].notna()
    ta = SPINE.searchsorted(a["trading_date"])
    te = np.where(a["has_prior"], SPINE.searchsorted(a["exp_td"].fillna(SPINE[0])), -10**6)
    a["tdist"] = np.where(a["has_prior"], ta - te, np.nan)
    rows = []
    for k, g in list(a.groupby(decade(a["trading_date"]))) + [("all", a)]:
        w = g["cap_prev"]
        r = dict(decade=k, actual_firm_quarters=len(g),
                 share_no_prior_year=(~g["has_prior"]).mean(),
                 capshare_no_prior_year=w[~g["has_prior"]].sum() / w.sum())
        for kk in (0, 1, 2):
            hit = g["tdist"].abs() <= kk
            r[f"share_within_{kk}"] = hit.mean()
            r[f"capshare_within_{kk}"] = w[hit].sum() / w.sum()
        hp = g[g["has_prior"]]
        r["median_abs_tdist_given_prior"] = hp["tdist"].abs().median()
        r["share_actual_earlier_than_expected_given_prior"] = (hp["tdist"] < 0).mean()
        rows.append(r)
    out = pd.DataFrame(rows).round(4)
    out.to_csv(f"{OUT}/validation_eax_proximity.csv", index=False)
    last = out.iloc[-1]
    log["eax_capshare_within_1_all"] = float(last["capshare_within_1"])
    log["eax_capshare_within_2_all"] = float(last["capshare_within_2"])
    log["eax_share_no_prior_year_all"] = float(last["share_no_prior_year"])
    log["eax_capshare_no_prior_year_all"] = float(last["capshare_no_prior_year"])


def decade(s: pd.Series) -> pd.Series:
    return (s.dt.year // 10 * 10).astype(str) + "s"


def validate(ev, fd, day, univ, top, cov_tab, log) -> None:
    # (a) rdq vs anndats agreement, matched firm-quarters, 1983+
    b = ev[(ev["src"] == "both") & (ev["rdq"] >= "1983-01-01")].copy()
    diff = (b["anndats"] - b["rdq"]).dt.days
    b["cat"] = pd.cut(diff, [-10**6, -2, -1, 0, 1, 10**6],
                      labels=["ibes_earlier_2plus", "ibes_earlier_1", "same_day", "ibes_later_1", "ibes_later_2plus"])
    t = pd.crosstab(decade(b["rdq"]), b["cat"], normalize="index").round(4)
    t["within_1_day"] = t[["ibes_earlier_1", "same_day", "ibes_later_1"]].sum(axis=1)
    t["n"] = b.groupby(decade(b["rdq"])).size()
    t.index.name = "decade_of_rdq"
    t.to_csv(f"{OUT}/validation_rdq_vs_ibes.csv")
    allb = diff.value_counts(normalize=True)
    log["agree_same_day_1983plus"] = round(float(allb.get(0, 0)), 4)
    log["agree_within_1_1983plus"] = round(float(allb[allb.index.isin([-1, 0, 1])].sum()), 4)
    log["ibes_later_2plus_1983plus"] = round(float((diff >= 2).mean()), 4)
    log["ibes_earlier_2plus_1983plus"] = round(float((diff <= -2).mean()), 4)
    # disagreement log (|diff| >= 2 days), event level -- closed tier, gitignored
    b.loc[diff.abs() >= 2, ["permco", "gvkey", "ticker", "pend_c", "pend_i", "rdq", "anndats", "anntime"]] \
        .assign(diff_days=diff[diff.abs() >= 2]).to_csv(f"{OUT}/disagreements_rdq_vs_ibes.csv", index=False)
    # agreement by time-of-day where known (post-shift assigned day vs rdq)
    kk = b[b["time_known"]].copy()
    kk["tod"] = np.select([kk["anntime"] < pd.Timedelta(hours=9, minutes=30), kk["anntime"] < CLOSE],
                          ["pre_open", "intraday"], "after_close")
    kk["rdq_minus_anndats"] = (kk["rdq"] - kk["anndats"]).dt.days.clip(-2, 2)
    pd.crosstab(kk["tod"], kk["rdq_minus_anndats"], normalize="index").round(4) \
        .to_csv(f"{OUT}/validation_rdq_minus_anndats_by_time_of_day.csv")

    # (b) after-close shift
    e = ev[ev["in_universe"]]
    s = pd.DataFrame({
        "n_events": e.groupby(decade(e["trading_date"])).size(),
        "share_time_known": e.groupby(decade(e["trading_date"]))["time_known"].mean(),
        "share_shifted_after_close": e.groupby(decade(e["trading_date"]))["shifted_after_close"].mean(),
        "share_shifted_among_time_known": e[e["time_known"]].groupby(decade(e[e["time_known"]]["trading_date"]))
                                          ["shifted_after_close"].mean(),
        "share_nontrading_calendar_date": e.groupby(decade(e["trading_date"]))["nontrading_date"].mean(),
    }).round(4)
    s.index.name = "decade"
    s.to_csv(f"{OUT}/validation_after_close_shift.csv")
    log["share_shifted_after_close_all"] = round(float(e["shifted_after_close"].mean()), 4)
    log["share_shifted_after_close_2000plus"] = round(float(e.loc[e["trading_date"] >= "2000-01-01", "shifted_after_close"].mean()), 4)
    log["share_time_known_all"] = round(float(e["time_known"].mean()), 4)
    # daily-count effect of the shift: day-of-week distribution with / without
    dw = pd.DataFrame({
        "with_shift": e.groupby(e["trading_date"].dt.day_name()).size(),
        "without_shift": e.groupby(e["trading_date_noshift"].dt.day_name()).size()})
    dw = (dw / dw.sum()).round(4).reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    dw.index.name = "weekday"
    dw.to_csv(f"{OUT}/validation_shift_weekday.csv")

    # (c) versus the calendar-window column is_earnings_season
    p = pd.read_csv(PANEL_PATH, usecols=["trading_date", "is_earnings_season"], parse_dates=["trading_date"]) \
        .set_index("trading_date")["is_earnings_season"].reindex(day.index)
    d = day[day["ea_cov_mcap"] == 1].copy()
    d["season"] = p.reindex(d.index)
    d["dec"] = decade(pd.Series(d.index, index=d.index))
    rows = []
    for dec, g in d.groupby("dec"):
        tot = g["ea_count"].sum()
        rows.append(dict(decade=dec, days=len(g), season_day_share=g["season"].mean(),
                         share_of_announcements_in_season=g.loc[g["season"] == 1, "ea_count"].sum() / tot,
                         share_of_mcap_share_in_season=g.loc[g["season"] == 1, "ea_mcap_share"].sum() / g["ea_mcap_share"].sum(),
                         mean_count_in=g.loc[g["season"] == 1, "ea_count"].mean(),
                         mean_count_out=g.loc[g["season"] == 0, "ea_count"].mean(),
                         mean_mcap_share_in=g.loc[g["season"] == 1, "ea_mcap_share"].mean(),
                         mean_mcap_share_out=g.loc[g["season"] == 0, "ea_mcap_share"].mean(),
                         corr_count_season=np.corrcoef(g["ea_count"], g["season"])[0, 1]))
    pd.DataFrame(rows).round(4).to_csv(f"{OUT}/validation_vs_is_earnings_season.csv", index=False)

    # (d) sanity: seasonality by month-of-year / day-of-month and counts per quarter vs universe
    dd = day[day["ea_cov_mcap"] == 1]
    mo = dd.groupby(dd.index.month)[["ea_count", "ea_mcap_share", "ea_count_top500"]].mean().round(4)
    mo.index.name = "month"
    mo.to_csv(f"{OUT}/validation_seasonality_month.csv")
    qq = cov_tab.round(4)
    qq.index.name = "quarter"
    qq.to_csv(f"{OUT}/validation_quarterly_counts.csv")

    # (e) SIZ vs CIZ splice (2024 overlap)
    sz = univ[(univ["src"] == "SIZ") & (univ["date"].dt.year == 2024)].set_index("date")
    cz = univ[(univ["src"] == "CIZ") & (univ["date"].dt.year == 2024)].set_index("date")
    j = sz[["n_firm", "cap"]].join(cz[["n_firm", "cap"]], lsuffix="_siz", rsuffix="_ciz", how="outer")
    log["splice_2024_days_siz_ciz"] = [int(sz.shape[0]), int(cz.shape[0])]
    log["splice_2024_mean_nfirm_ratio_ciz_over_siz"] = round(float((j["n_firm_ciz"] / j["n_firm_siz"]).mean()), 4)
    log["splice_2024_mean_cap_ratio_ciz_over_siz"] = round(float((j["cap_ciz"] / j["cap_siz"]).mean()), 4)
    t5 = top[top["date"].dt.year == 2024]
    ov = []
    for ym, g in t5.groupby(t5["date"].dt.to_period("M")):
        a = set(g.loc[g["src"] == "SIZ", "permco"]); c = set(g.loc[g["src"] == "CIZ", "permco"])
        if a and c:
            ov.append(len(a & c) / 500)
    log["splice_2024_top500_overlap_mean"] = round(float(np.mean(ov)), 4) if ov else None
    # spine vs CRSP dates
    usiz = univ[univ["src"] == "SIZ"]["date"]
    sp = SPINE[(SPINE <= SIZ_END)]
    log["spine_dates_missing_in_crsp_siz"] = [str(x.date()) for x in sp.difference(pd.DatetimeIndex(usiz))][:20]
    log["crsp_siz_dates_not_in_spine"] = [str(x.date()) for x in pd.DatetimeIndex(usiz).difference(SPINE)][:20]
    sp25 = SPINE[SPINE > SIZ_END]
    uciz = univ[(univ["src"] == "CIZ") & (univ["date"] > SIZ_END)]["date"]
    log["spine_dates_missing_in_crsp_ciz_2025"] = [str(x.date()) for x in sp25.difference(pd.DatetimeIndex(uciz))][:20]

    figure(day)


def figure(day: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted, c1 = "#1f2328", "#6e7781", "#2a6fdb"
    d = day[day["ea_cov_mcap"] == 1]
    fig, ax = plt.subplots(2, 1, figsize=(10, 7.5))
    yr = d["ea_mcap_share"].groupby(d.index.year)
    a = ax[0]
    a.plot(yr.mean().index, 100 * yr.mean().values, color=c1, lw=2, label="mean")
    a.plot(yr.quantile(0.99).index, 100 * yr.quantile(0.99).values, color=muted, lw=1.2, ls="--", label="99th pct")
    a.set_title("Share of total CRSP market cap announcing earnings on the day (annual mean and 99th percentile of daily values)",
                fontsize=10, color=ink, loc="left")
    a.set_ylabel("% of market cap")
    a.legend(frameon=False, fontsize=9)
    doy = d.groupby([d.index.month, d.index.day])["ea_mcap_share"].mean()
    b = ax[1]
    x = np.arange(len(doy))
    b.bar(x, 100 * doy.values, color=c1, width=0.9)
    months = np.array([m for m, _ in doy.index])
    starts = [int(np.argmax(months == m)) for m in range(1, 13)]
    b.set_xticks(starts)
    b.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    b.set_title("Seasonality: mean daily market-cap share announcing, by calendar day", fontsize=10, color=ink, loc="left")
    b.set_ylabel("% of market cap")
    for a in ax:
        a.spines[["top", "right"]].set_visible(False)
        a.grid(axis="y", color="#d0d7de", lw=0.6)
        a.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_ea_mcap_share.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
