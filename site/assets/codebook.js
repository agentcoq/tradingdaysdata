// Searchable, sortable codebook. Data: assets/codebook.json, written by site/build_site.py.
(function () {
  const COLS = {
    daily: [["column", "Column"], ["block", "Block"], ["timing", "Timing"], ["quality", "Quality"],
            ["coverage_start", "From"], ["license", "License"], ["note", "Source and note"]],
    monthly: [["column", "Column"], ["block", "Block"], ["timing", "Timing"], ["aggregation", "Aggregation"],
              ["first_month", "From"], ["license", "License"], ["note", "Daily source column and note"]],
  };
  const NOWRAP = new Set(["coverage_start", "first_month", "quality", "timing"]);
  const KEY = { daily: "trading_date", monthly: "month" };   // the date key of each panel
  const FILTERS = { "f-block": "block", "f-timing": "timing", "f-quality": "quality", "f-license": "license" };
  const state = { set: "daily", sort: "", dir: 1, data: null };
  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  function licenseValue(r, f) {
    return (f === "license" && r.rights_tier === "closed") ? "licensed source" : r[f];
  }
  function licenseLabel(r) {
    if (r.rights_tier === "closed") return '<span class="tag closed">licensed source</span>';
    return '<span class="tag open">' + esc(r.license) + "</span>";
  }
  function fillSelect(id, field, rows) {
    const sel = $(id);
    const vals = [...new Set(rows.map((r) => licenseValue(r, field)))].filter((v) => v !== undefined && v !== "").sort();
    sel.innerHTML = '<option value="">All</option>' + vals.map((v) => `<option>${esc(v)}</option>`).join("");
    sel.parentElement.style.display = vals.length ? "" : "none";
  }
  function setup() {
    const rows = state.data[state.set];
    Object.entries(FILTERS).forEach(([id, f]) => fillSelect(id, f, rows));
    const head = COLS[state.set].map(([k, label]) =>
      `<th scope="col" data-k="${k}"><button type="button">${label}</button></th>`).join("");
    document.querySelector("#cb thead").innerHTML = `<tr>${head}</tr>`;
    document.querySelectorAll("#cb th").forEach((th) => th.querySelector("button").addEventListener("click", () => {
      const k = th.dataset.k;
      state.dir = state.sort === k ? -state.dir : 1;
      state.sort = k;
      render();
    }));
    state.sort = "";
    render();
  }
  function cell(k, r) {
    if (k === "column") return `<td class="col"><button type="button" aria-expanded="false">${esc(r[k])}</button></td>`;
    if (k === "license") return `<td>${licenseLabel(r)}</td>`;
    if (k === "note") return `<td class="notes"><div><b>${esc(r.source)}</b>${r.note ? " · " + esc(r.note) : ""}</div></td>`;
    if (NOWRAP.has(k)) return `<td class="nowrap">${esc(r[k])}</td>`;
    return `<td>${esc(r[k])}</td>`;
  }
  function render() {
    const q = $("q").value.trim().toLowerCase();
    let rows = state.data[state.set].filter((r) => {
      for (const [id, f] of Object.entries(FILTERS)) {
        const v = $(id).value;
        if (v && licenseValue(r, f) !== v) return false;
      }
      if (!q) return true;
      return [r.column, r.source, r.note, r.block, r.aggregation].join(" ").toLowerCase().includes(q);
    });
    if (state.sort) {
      const k = state.sort;
      rows = rows.slice().sort((a, b) =>
        String(a[k] ?? "").localeCompare(String(b[k] ?? ""), undefined, { numeric: true }) * state.dir);
    }
    document.querySelectorAll("#cb th").forEach((th) => {
      if (th.dataset.k === state.sort) th.setAttribute("aria-sort", state.dir > 0 ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
    document.querySelector("#cb tbody").innerHTML = rows.map((r) =>
      "<tr>" + COLS[state.set].map(([k]) => cell(k, r)).join("") + "</tr>").join("");
    const isKey = (r) => r.column === KEY[state.set];          // the date key is listed but not counted as a column
    const total = state.data[state.set].filter((r) => !isKey(r)).length;
    const shown = rows.filter((r) => !isKey(r)).length;
    $("count").textContent = (shown === total ? `${total} columns` : `${shown} of ${total} columns`) + ", plus the date key";
  }
  function toggleRow(tr) {
    const open = tr.classList.toggle("open");          // show the full source and note
    tr.querySelector("td.col button").setAttribute("aria-expanded", String(open));
  }
  // a click anywhere on a row, or Enter/Space on its column-name button, expands it
  document.querySelector("#cb tbody").addEventListener("click", (e) => { const tr = e.target.closest("tr"); if (tr) toggleRow(tr); });

  const tabs = [...document.querySelectorAll(".tabs [role=tab]")];
  function selectTab(b) {
    tabs.forEach((x) => {
      const on = x === b;
      x.setAttribute("aria-selected", String(on));
      x.tabIndex = on ? 0 : -1;
    });
    state.set = b.dataset.set;
    $("cb-panel").setAttribute("aria-labelledby", b.id);
    $("q").value = "";
    setup();
  }
  tabs.forEach((b, i) => {
    b.addEventListener("click", () => selectTab(b));
    b.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      selectTab(next);
    });
  });
  $("filters").addEventListener("submit", (e) => e.preventDefault());
  $("q").addEventListener("input", render);
  Object.keys(FILTERS).forEach((id) => $(id).addEventListener("change", render));
  fetch("assets/codebook.json").then((r) => r.json()).then((d) => { state.data = d; setup(); })
    .catch(() => { $("count").textContent = "The codebook could not be loaded."; });
})();
