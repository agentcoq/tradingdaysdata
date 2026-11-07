#!/usr/bin/env python3
"""Build the static website (GitHub Pages, served from docs/) from the public data files of this repository.

    python3 site/build_site.py

Inputs: site/config.json (release, DOI, links), the data dictionaries open/columns.csv and
open/monthly/columns_monthly.csv, the attribution notice NOTICE.md, and, if present, release/v<version>/manifest.json
written by make_release.py (file sizes and checksums). Standard library only, so the site builds anywhere.
Every page is regenerated on each run; nothing under docs/ is edited by hand.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE, OUT = ROOT / "site", ROOT / "docs"
NAV = [("index.html", "Home"), ("data.html", "Data"), ("codebook.html", "Codebook"),
       ("documentation.html", "Documentation"), ("sources.html", "Sources"), ("rebuild.html", "Licensed columns")]
E = html.escape


# --------------------------------------------------------------------------- helpers
def read_csv(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fmt_bytes(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB"


def inline_md(s: str) -> str:
    """Escape, then render `code`, **bold**, *italic* and [text](url)."""
    s = E(s, quote=False)
    codes = []                                # protect code spans, whose text may contain '*'

    def keep(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"
    s = re.sub(r"`([^`]+)`", keep, s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", s)


def md_table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [c for c in cells[1:] if not all(re.fullmatch(r":?-{3,}:?", x) for x in c)]
    th = "".join(f"<th>{inline_md(c)}</th>" for c in head)
    tb = "".join("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def md_to_html(text: str, shift: int = 0) -> str:
    """Small Markdown subset used by NOTICE.md: headings, paragraphs, nested '-' lists (two-space indents),
    '>' block quotes and pipe tables."""
    out, para, stack, quote, table = [], [], [], [], []      # stack of open list indents

    def close_para():
        if para:
            out.append(f"<p>{inline_md(' '.join(para))}</p>")
            para.clear()
        if quote:
            out.append(f"<blockquote><p>{inline_md(' '.join(quote))}</p></blockquote>")
            quote.clear()
        if table:
            out.append(md_table(table))
            table.clear()

    def close_lists(to: int = -1):
        while stack and stack[-1] > to:
            out.append("</li></ul>")
            stack.pop()

    merged = []        # join each indented continuation line onto the list item it belongs to, by indentation
    for raw in text.splitlines():
        cont = raw.startswith(" ") and raw.strip() and not re.match(r"^\s*-\s", raw)
        target = None
        if cont:
            c = len(raw) - len(raw.lstrip())
            for j in range(len(merged) - 1, -1, -1):
                m = re.match(r"^(\s*)-\s", merged[j])
                if m:
                    if len(m.group(1)) + 2 <= c:          # the item whose text starts at this indentation
                        target = j
                        break
                elif merged[j].strip() and not merged[j].startswith(" "):
                    break                                   # left the list
        if target is not None:
            merged[target] += " " + raw.strip()
        else:
            merged.append(raw)
    for raw in merged:
        line = raw.rstrip()
        m_h = re.match(r"^(#{1,6})\s+(.*)", line)
        m_li = re.match(r"^(\s*)-\s+(.*)", line)
        if not line.strip():
            close_para()
            continue
        if line.lstrip().startswith("|"):
            if not table:
                close_para(); close_lists()
            table.append(line)
        elif line.startswith(">"):
            if not quote:
                close_para(); close_lists()
            quote.append(line[1:].strip())
        elif m_h:
            close_para(); close_lists()
            level = min(len(m_h.group(1)) + shift, 6)
            out.append(f"<h{level}>{inline_md(m_h.group(2))}</h{level}>")
        elif m_li:
            close_para()
            ind = len(m_li.group(1))
            if not stack or ind > stack[-1]:
                out.append("<ul><li>")
                stack.append(ind)
            else:
                close_lists(ind)
                out.append("</li><li>")
            out.append(inline_md(m_li.group(2)))
        elif stack and raw.startswith(" "):
            out.append(" " + inline_md(line.strip()))      # continuation of a list item
        else:
            if quote or table:
                close_para()
            close_lists()
            para.append(line.strip())
    close_para(); close_lists()
    return "\n".join(out)


def page(cfg: dict, fname: str, title: str, body: str, scripts: str = "", wide: bool = False) -> str:
    cur = ' aria-current="page"'
    body_cls = ' class="wide"' if wide else ""
    nav = "".join(f'<a href="{f}"{cur if f == fname else ""}>{E(t)}</a>' for f, t in NAV)
    authors = " and ".join(E(a["name"]) for a in cfg["authors"])
    full_title = f"{E(title)} · {E(cfg['site_name'])}" if fname != "index.html" else E(cfg["site_name"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{full_title}</title>
<meta name="description" content="Open dataset of {E(cfg['paper_title'])}: characteristics of every NYSE trading day since 1960.">
<link rel="stylesheet" href="assets/style.css">
</head>
<body{body_cls}>
<header class="site-header">
  <div class="wrap header-row">
    <a class="brand" href="index.html">{E(cfg['site_name'])}</a>
    <nav class="nav" aria-label="Main">{nav}</nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>Data and documentation for <em>{E(cfg['paper_title'])}</em>, by {authors}.
    Open data under CC&nbsp;BY&nbsp;4.0 or CC&nbsp;BY-SA&nbsp;4.0, column by column; code under the MIT license.</p>
  </div>
</footer>
{scripts}
</body>
</html>
"""


def button(label: str, href: str | None, primary: bool = False) -> str:
    cls = "btn primary" if primary else "btn"
    if not href:
        return f'<span class="{cls} disabled" aria-disabled="true">{E(label)}</span>'
    return f'<a class="{cls}" href="{E(href)}">{E(label)}</a>'


def citation(cfg: dict) -> tuple[str, str]:
    a = cfg["authors"]
    names = " and ".join(f"{x['name'].split()[-1]}, {' '.join(x['name'].split()[:-1])}" for x in a)
    paper = (f"@unpublished{{coqueret2026tradingdays,\n  author = {{{names}}},\n"
             f"  title  = {{{cfg['paper_title']}}},\n  year   = {{2026}},\n  note   = {{Working paper}}\n}}")
    rel = cfg["release"]
    doi = f",\n  doi       = {{{rel['doi']}}}" if rel["doi"] else ""
    data = (f"@misc{{coqueret2026tradingdaysdata,\n  author    = {{{names}}},\n"
            f"  title     = {{Trading Days Data, version {rel['version']}}},\n  year      = {{2026}}{doi},\n"
            f"  howpublished = {{\\url{{https://{cfg['domain']}}}}}\n}}")
    return paper, data


# --------------------------------------------------------------------------- pages
def page_index(cfg, daily, monthly, man) -> str:
    n_cols = len(daily) - 1
    n_open = sum(r["rights_tier"] == "open" for r in daily) - 1
    n_closed = n_cols - n_open
    n_sessions = man["daily"]["rows"] if man else 16610
    n_months = man["monthly"]["rows"] if man else 792
    rel = cfg["release"]
    paper_bib, data_bib = citation(cfg)
    news = "".join(f'<li><span class="date">{E(n["date"])}</span> {E(n["text"])}</li>' for n in cfg["news"])
    return f"""
<section class="hero">
  <h1>Characteristics of every NYSE trading day since 1960</h1>
  <p class="lede">This website hosts a dataset of {n_cols} day characteristics for each of the {n_sessions:,} NYSE sessions from
  1960 to 2025: the calendar, scheduled macroeconomic and monetary-policy announcements, political, sports and
  natural events, weather and astronomy, attention, and market conditions. Every event is placed on the first
  session in which the market could react to it, and every column records where its dates come from.</p>
  <div class="actions">
    {button("Download the data", "data.html", primary=True)}
    {button("Browse the codebook", "codebook.html")}
    {button("Read the paper", cfg.get("paper_url"))}
  </div>
</section>

<section class="stats" aria-label="The dataset in numbers">
  <div class="stat"><span class="num">{n_cols}</span><span class="label">day characteristics</span></div>
  <div class="stat"><span class="num">{n_sessions:,}</span><span class="label">NYSE sessions, 1960–2025</span></div>
  <div class="stat"><span class="num">{n_open}</span><span class="label">open columns, released as data</span></div>
  <div class="stat"><span class="num">{n_months}</span><span class="label">months in the monthly version</span></div>
</section>

<section>
  <h2>What is in the dataset</h2>
  <p>The {n_open} open columns are released as data, under CC&nbsp;BY&nbsp;4.0 or, for the columns derived from
  Wikipedia, CC&nbsp;BY-SA&nbsp;4.0. The {n_closed} columns built from licensed sources (CRSP, Compustat, I/B/E/S,
  and a few third-party series) are not redistributed: <a href="rebuild.html">scripts rebuild them</a> from your
  own access and check the result against our checksums. For each column, the <a href="codebook.html">codebook</a>
  gives its source, the first date with data, a quality grade, whether its value is known before the open, and its
  license. A <a href="data.html#monthly">monthly version</a> aggregates the daily data into {n_months} months.</p>
</section>

<section class="two-col">
  <div>
    <h2>Cite</h2>
    <p>Please cite the paper, and the version of the data that you use.</p>
    <pre class="cite"><code>{E(paper_bib)}</code></pre>
    <pre class="cite"><code>{E(data_bib)}</code></pre>
  </div>
  <div>
    <h2>News</h2>
    <ul class="news">{news}</ul>
    <h2>Updates</h2>
    <p>The data are updated once a year, in the first quarter, when the year-end data are available. Each update is
    a new version with its own DOI; earlier versions stay available unchanged.</p>
  </div>
</section>
"""


def page_data(cfg, daily, monthly, man) -> str:
    rel = cfg["release"]
    base = rel.get("download_base")
    doi = (f'<a href="https://doi.org/{E(rel["doi"])}">doi:{E(rel["doi"])}</a>' if rel["doi"]
           else "assigned on Zenodo at publication")
    if rel.get("concept_doi"):
        doi += (f'; all versions: <a href="https://doi.org/{E(rel["concept_doi"])}">'
                f'doi:{E(rel["concept_doi"])}</a>')
    desc = {
        "trading_days_daily_open.csv": "Daily panel: <code>trading_date</code> and the open columns",
        "trading_days_daily_open.parquet": "Daily panel, parquet (typed)",
        "trading_days_monthly_open.csv": "Monthly panel: <code>month</code> and the open monthly columns",
        "trading_days_monthly_open.parquet": "Monthly panel, parquet (typed)",
        "codebook_daily.csv": "Daily codebook: every column, open and licensed",
        "codebook_monthly.csv": "Monthly codebook: every column, with its aggregation rule",
    }
    order = list(desc)
    rows = ""
    files = {f["file"]: f for f in man["files"]} if man else {}
    for name in order:
        f = files.get(name)
        size = fmt_bytes(f["bytes"]) if f else ""
        link = f'<a href="{E(base)}/{E(name)}">{E(name)}</a>' if base else f"<code>{E(name)}</code>"
        rows += f"<tr><td>{link}</td><td>{desc[name]}</td><td class='num'>{size}</td></tr>\n"
    sums = ""
    if man:
        sums = "\n".join(f"{f['sha256']}  {f['file']}" for f in man["files"])
        sums = f"""<details><summary>SHA-256 checksums</summary><pre class="sums"><code>{E(sums)}</code></pre></details>"""
    status = ("" if base else
              '<p class="note">The files are published with the release. Until then, the links below are inactive.</p>')
    d, m = (man["daily"], man["monthly"]) if man else ({}, {})
    hf = (f' The same files are mirrored on <a href="{E(cfg["huggingface_url"])}">Hugging Face</a>, where they '
          f'load directly with the <code>datasets</code> library.' if cfg.get("huggingface_url") else "")
    return f"""
<h1>Data</h1>
<section>
  <h2>Version {E(rel['version'])}</h2>
  <dl class="facts">
    <dt>Sample</dt><dd>{E(d.get('first', '1960-01-04'))} to {E(d.get('last', '2025-12-31'))}, {d.get('rows', 16610):,} NYSE sessions;
      monthly: {E(m.get('first', '1960-01'))} to {E(m.get('last', '2025-12'))}, {m.get('rows', 792)} months</dd>
    <dt>Open columns</dt><dd>{d.get('open_columns', 356)} daily, {m.get('open_columns', 528)} monthly</dd>
    <dt>DOI</dt><dd>{doi}</dd>
    <dt>Released</dt><dd>{E(rel['date'] or 'forthcoming')}</dd>
  </dl>
  <p>This version matches the paper. The CSV files are the reference; the parquet files hold the same data with
  numeric and date types.{hf}</p>
  {status}
  <div class="table-wrap"><table class="files">
    <thead><tr><th>File</th><th>Contents</th><th class="num">Size</th></tr></thead>
    <tbody>
{rows}    </tbody>
  </table></div>
  {sums}
</section>

<section>
  <h2>Reading the data</h2>
  <p>Each row of the daily panel is one NYSE session, keyed by <code>trading_date</code>. The return of session
  <i>t</i> runs from the close of session <i>t</i>&minus;1 to the close of session <i>t</i>, so an event belongs to
  the first session whose close comes at or after it. Columns tagged <code>ex_ante</code> in the codebook are known
  before the session opens; columns tagged <code>realized</code> become known during or after the session and
  should be lagged by one session in forecasts. The <a href="documentation.html">documentation</a> gives the
  dating rules, the quality grades and the licenses.</p>
<pre><code>import pandas as pd
daily = pd.read_parquet("trading_days_daily_open.parquet")
codebook = pd.read_csv("codebook_daily.csv")
ex_ante = codebook.loc[codebook.timing == "ex_ante", "column"]</code></pre>
</section>

<section id="monthly">
  <h2>Monthly version</h2>
  <p>The monthly panel aggregates the daily data by calendar month: event flags become counts and shares of the
  month's sessions, continuous series become monthly means, extremes and month-end values, daily returns are
  compounded, and the calendar gives the number of sessions, weekdays, closures and early closes. Each monthly
  column is tagged <code>known_at_start</code> if its value is fixed before the month begins, as for the number of
  scheduled FOMC meetings, and <code>realized_in_month</code> otherwise.</p>
</section>

<section>
  <h2>Licensed columns</h2>
  <p>{sum(r['rights_tier'] == 'closed' for r in daily)} daily columns come from licensed or third-party sources and
  are not in these files. <a href="rebuild.html">Scripts rebuild them</a> with your own access and merge them with
  the open panel into the full panel.</p>
</section>

<section>
  <h2>Earlier versions</h2>
  <p>None yet. Each annual update will be listed here with its DOI, and every earlier version will stay
  available unchanged.</p>
</section>
"""


def page_codebook(cfg, daily, monthly, man) -> str:
    return f"""
<h1>Codebook</h1>
<p>Every column of the daily and monthly panels, open and licensed. Search by name, source or note, and filter by
block, timing, quality or license. Click a row to show its full source and note. The codebook can also be downloaded as CSV from the <a href="data.html">data
page</a>.</p>
<div class="tabs" role="tablist" aria-label="Panel">
  <button role="tab" id="tab-daily" aria-selected="true" aria-controls="cb-panel" data-set="daily">Daily ({len(daily) - 1} columns)</button>
  <button role="tab" id="tab-monthly" aria-selected="false" aria-controls="cb-panel" tabindex="-1" data-set="monthly">Monthly ({len(monthly) - 1} columns)</button>
</div>
<form class="filters" id="filters">
  <label>Search <input type="search" id="q" placeholder="e.g. fomc, cpi, holiday" autocomplete="off"></label>
  <label>Block <select id="f-block"></select></label>
  <label>Timing <select id="f-timing"></select></label>
  <label>Quality <select id="f-quality"></select></label>
  <label>License <select id="f-license"></select></label>
</form>
<p class="count" id="count" aria-live="polite"></p>
<div class="table-wrap" id="cb-panel" role="tabpanel" aria-labelledby="tab-daily"><table class="codebook" id="cb"><thead></thead><tbody></tbody></table></div>
<noscript><p>The codebook needs JavaScript. The same information is in <code>codebook_daily.csv</code> and
<code>codebook_monthly.csv</code>.</p></noscript>
"""


def page_documentation(cfg, daily, monthly, man) -> str:
    chars = [r for r in daily if r["column"] != "trading_date"]      # the 408 characteristics, without the key
    q = {}
    for r in chars:
        q[r["quality"]] = q.get(r["quality"], 0) + 1
    t = {}
    for r in chars:
        t[r["timing"]] = t.get(r["timing"], 0) + 1
    blocks = {}
    for r in chars:
        blocks[r["block"]] = blocks.get(r["block"], 0) + 1
    block_rows = "".join(f"<tr><td><code>{E(b)}</code></td><td class='num'>{n}</td></tr>"
                         for b, n in sorted(blocks.items(), key=lambda x: -x[1]))
    lic = {}
    for r in chars:
        key = r["license"] if r["rights_tier"] == "open" else "licensed source, not redistributed"
        lic[key] = lic.get(key, 0) + 1
    return f"""
<h1>Documentation</h1>

<section>
  <h2>Unit of observation</h2>
  <p>One row per NYSE trading session, from 1960-01-04 to 2025-12-31. The session list follows the holiday and
  closure rules of the NYSE, and every closure is recorded with an identifier and a cause, including the Wednesday
  closures of the 1968 paperwork crisis and the closures after September 11, 2001. Scheduled opening and closing
  times are recorded for each session, so early closes are part of the data.</p>
</section>

<section>
  <h2>Dating rule</h2>
  <p>The return of session <i>t</i> runs from the close of session <i>t</i>&minus;1 to the close of session
  <i>t</i>. An event that occurs on a trading day, at or before the close, belongs to that day's session. Any other
  event belongs to the next session: events on weekends or holidays, earnings announced after the close, and
  sports finals played in the evening are assigned to the next session, the first one in which the market can react
  to them. A macroeconomic release with no recorded time is assigned its usual release time of 8:30. Whenever an
  official source exists, the date comes from it: the release calendar of the statistical agency, the Federal
  Reserve for FOMC decisions, the exchange for closures.</p>
</section>

<section>
  <h2>Timing</h2>
  <p>Each column is tagged <code>ex_ante</code> ({t.get('ex_ante', 0)} columns) if its value is known before the
  session opens, as for calendar positions and the dates of scheduled announcements, or <code>realized</code>
  ({t.get('realized', 0)} columns) if it becomes known only during or after the session, as for the weather, disasters
  or daily uncertainty indices. Realized columns should be lagged by one session in forecasts.</p>
</section>

<section>
  <h2>Quality grades</h2>
  <dl class="grades">
    <dt><code>verified</code> ({q.get('verified', 0)})</dt><dd>the audited base release of the dataset</dd>
    <dt><code>exact-source</code> ({q.get('exact-source', 0)})</dt><dd>dated from a primary source</dd>
    <dt><code>rule</code> ({q.get('rule', 0)})</dt><dd>a deterministic rule applied as written</dd>
    <dt><code>wiki-sourced</code> ({q.get('wiki-sourced', 0)})</dt><dd>dated from English Wikipedia articles</dd>
    <dt><code>approximate</code> ({q.get('approximate', 0)})</dt><dd>hand-listed windows or rules whose edges are
    judgement calls</dd>
  </dl>
</section>

<section>
  <h2>Blocks</h2>
  <p>The {len(chars)} characteristics, open and licensed, are grouped into blocks of related columns. The counts on
  this page exclude the date key <code>trading_date</code>.</p>
  <div class="table-wrap narrow"><table><thead><tr><th>Block</th><th class="num">Columns</th></tr></thead>
  <tbody>{block_rows}</tbody></table></div>
</section>

<section>
  <h2>Licenses</h2>
  <ul>{''.join(f"<li>{E(k)}: {n} columns</li>" for k, n in sorted(lic.items(), key=lambda x: -x[1]))}</ul>
  <p>The license of each column is in the codebook. The open daily file holds both CC&nbsp;BY&nbsp;4.0 and
  CC&nbsp;BY-SA&nbsp;4.0 columns: if you redistribute the whole file, CC&nbsp;BY-SA&nbsp;4.0 satisfies both; if you
  redistribute only CC&nbsp;BY columns, CC&nbsp;BY&nbsp;4.0 applies. Code is under the MIT license.</p>
</section>

<section>
  <h2>Using the columns as controls</h2>
  <p>Beyond day effects, the columns can serve as control variables: calendar and announcement indicators in
  daily return regressions, flags for FOMC or macroeconomic release days in event studies, scheduled releases,
  holidays and early closes in volatility and liquidity models, and monthly counts of sessions and announcements in
  monthly regressions. Several columns can describe the same event, so keep one of them in a regression, and use
  only <code>ex_ante</code> columns, or lagged <code>realized</code> ones, in forecasts.</p>
</section>

<section>
  <h2>Versions and updates</h2>
  <p>The data are updated once a year, in the first quarter, when the year-end data are available. Each update is a
  new version with its own DOI. A version is never overwritten, and the sources of each version are pinned: every
  raw download is recorded with its address, the time it was made and its checksum.</p>
</section>
"""


def page_sources(cfg, notice_md: str) -> str:
    body = md_to_html(notice_md)
    body = re.sub(r"^<h1>Sources, attribution and citation</h1>\n?", "", body)
    body = re.sub(r"^<p>The column-level source of every column.*?</p>\n?", "", body, flags=re.S)  # repo paths
    return f"""
<h1>Sources and attribution</h1>
<p>The source of every column is in the <a href="codebook.html">codebook</a>. This page lists the providers whose
data or dates enter the dataset, with the attribution each one asks for. File names such as
<code>open/columns.csv</code> refer to the <a href="{E(cfg['repo_url'])}">repository on GitHub</a>. Some of the
files that this notice mentions, such as the event lists and the download records of the authors' build, are not
part of the public release.</p>
<div class="prose">
{body}
</div>
"""


def page_rebuild(cfg, daily) -> str:
    blocks = {}
    for r in daily:
        if r["rights_tier"] == "closed":
            blocks.setdefault(r["closed_block"], []).append(r)
    info = {
        "crsp": ("CRSP daily index file via WRDS", "WRDS subscription (CRSP)", "build_crsp.py"),
        "earnings": ("Compustat, I/B/E/S and CRSP via WRDS", "WRDS subscriptions (Compustat, I/B/E/S, CRSP)", "build_earnings.py"),
        "french": ("Kenneth R. French Data Library", "none (public download)", "build_french.py"),
        "fred_thirdparty": ("FRED series owned by third parties (CBOE, Moody's, S&amp;P DJI, ICE)", "none; a FRED API key is optional", "build_fred_thirdparty.py"),
        "epu": ("Baker, Bloom and Davis, Economic Policy Uncertainty", "none; a FRED API key is optional", "build_epu.py"),
        "gpr": ("Caldara and Iacoviello, Geopolitical Risk index", "none (public download)", "build_gpr.py"),
    }
    rows = ""
    for b, cols in sorted(blocks.items(), key=lambda x: -len(x[1])):
        if b not in info:
            raise SystemExit(f"unknown licensed block {b!r}: describe it in page_rebuild")
        src, cred, script = info[b]
        names = ", ".join(f"<code>{E(c['column'])}</code>" for c in cols)
        rows += (f"<tr><td><code>{E(b)}</code></td><td class='num'>{len(cols)}</td><td>{src}</td><td>{cred}</td>"
                 f"<td><code>closed/{script}</code></td></tr>\n<tr class='sub'><td></td><td colspan='4'>{names}</td></tr>\n")
    n = sum(len(v) for v in blocks.values())
    return f"""
<h1>Licensed columns</h1>
<p>{n} columns come from sources whose terms do not allow us to redistribute them. We release, for each of these
columns, a script that rebuilds it from your own access, and the SHA-256 checksum of every block and column at our
vintage, so that you can check that your rebuild matches ours.</p>

<div class="table-wrap"><table class="rebuild">
  <thead><tr><th>Block</th><th class="num">Columns</th><th>Source</th><th>What you need</th><th>Script</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table></div>

<section>
  <h2>Rebuilding the full panel</h2>
  <p>Clone the <a href="{E(cfg['repo_url'])}">repository</a>, which holds the open panels and these scripts, and
  run, with Python 3.10 or later and the packages of <code>requirements.txt</code>:</p>
<pre><code># public downloads, no account needed
python3 closed/build_french.py
python3 closed/build_epu.py
python3 closed/build_gpr.py
python3 closed/build_fred_thirdparty.py
# licensed: your WRDS subscriptions (CRSP; Compustat and I/B/E/S for earnings)
WRDS_USER=your_username python3 closed/build_crsp.py
WRDS_USER=your_username python3 closed/build_earnings.py
python3 closed/verify.py          # which blocks and columns match our vintage
python3 build_full.py             # open panel + rebuilt blocks -> full daily panel
python3 closed/build_monthly.py   # licensed monthly blocks
python3 closed/verify.py --monthly
python3 build_full.py --monthly   # full monthly panel</code></pre>
  <p>Credentials are read from environment variables only and are never written to disk. Without WRDS access,
  <code>python3 build_full.py --allow-missing</code> builds the panel with the CRSP and earnings columns left empty;
  the Ken French market return <code>ff_mkt</code> is a close substitute for <code>mkt_ret</code>.</p>
</section>

<section>
  <h2>What to expect</h2>
  <p>Public sources are revised and extended over time, so a fresh download can differ from our vintage.
  <code>closed/verify.py</code> reports, for each block and column, whether your rebuild is byte-identical to ours,
  and compares the coverage. Each rebuilt column stays under its provider's terms.</p>
</section>
"""


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT))   # the public copy made by sync_public.py
    a = ap.parse_args()
    data = Path(a.data)
    cfg = json.loads((SITE / "config.json").read_text())
    daily = read_csv(data / "open/columns.csv")
    monthly = read_csv(data / "open/monthly/columns_monthly.csv")
    mp = ROOT / "release" / f"v{cfg['release']['version']}" / "manifest.json"
    man = json.loads(mp.read_text()) if mp.exists() else None
    notice = (data / "NOTICE.md").read_text()

    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    for f in ["style.css", "codebook.js"]:
        shutil.copyfile(SITE / "assets" / f, OUT / "assets" / f)
    keep_d = ["column", "block", "source", "coverage_start", "quality", "timing", "license", "rights_tier", "note"]
    keep_m = ["column", "block", "source", "aggregation", "timing", "first_month", "license", "rights_tier", "note"]
    cb = {"daily": [{k: r.get(k, "") for k in keep_d} for r in daily],
          "monthly": [{k: r.get(k, "") for k in keep_m} for r in monthly]}
    (OUT / "assets" / "codebook.json").write_text(json.dumps(cb, ensure_ascii=False, separators=(",", ":")))

    pages = {
        "index.html": ("Home", page_index(cfg, daily, monthly, man), ""),
        "data.html": ("Data", page_data(cfg, daily, monthly, man), ""),
        "codebook.html": ("Codebook", page_codebook(cfg, daily, monthly, man),
                          '<script src="assets/codebook.js"></script>'),
        "documentation.html": ("Documentation", page_documentation(cfg, daily, monthly, man), ""),
        "sources.html": ("Sources", page_sources(cfg, notice), ""),
        "rebuild.html": ("Licensed columns", page_rebuild(cfg, daily), ""),
    }
    for fname, (title, body, scripts) in pages.items():
        (OUT / fname).write_text(page(cfg, fname, title, body, scripts, wide=fname == "codebook.html"))
    (OUT / ".nojekyll").write_text("")
    cname = OUT / "CNAME"            # written only once the domain's DNS points to GitHub Pages
    if cfg.get("domain") and cfg.get("domain_live"):
        cname.write_text(cfg["domain"] + "\n")
    elif cname.exists():
        cname.unlink()
    print(f"site written to {OUT}: {', '.join(pages)}; manifest {'found' if man else 'absent'}")


if __name__ == "__main__":
    main()
