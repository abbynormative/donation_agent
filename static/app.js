const $ = (id) => document.getElementById(id);

// ── DOM refs ──────────────────────────────────────────────────
const askBtn       = $("ask-btn");
const questionEl   = $("question");
const showSqlEl    = $("show-sql");
const chartTypeEl  = $("chart-type");
const statusEl     = $("status");
const sqlBox       = $("sql-box");
const sqlText      = $("sql-text");
const resultMeta   = $("result-meta");
const tableWrap    = $("table-wrap");
const chartWrap    = $("chart-wrap");
const chartTitle   = $("chart-title");
const chartCanvas  = $("chart-canvas");
const taskList     = $("task-list");

const clusterBtn             = $("cluster-btn");
const clusterCountEl         = $("cluster-count");
const clusterStatusEl        = $("cluster-status");
const clusterOutputEl        = $("cluster-output");
const clusterSummaryEl       = $("cluster-summary");
const clusterSegmentsTableEl = $("cluster-segments-table");
const clusterFactorsEl       = $("cluster-factors");
const clusterTopDonorsTableEl = $("cluster-top-donors-table");
const clusterNoteEl          = $("cluster-note");

let currentChart = null;

// ── Status helper (shared by query and cluster panels) ────────
function setStatus(el, kind, msg) {
  if (!msg) { el.hidden = true; el.textContent = ""; return; }
  el.hidden = false;
  el.className = `status ${kind}`;
  el.textContent = msg;
}

// ── Chart palette & column-type heuristics ────────────────────
const CHART_PALETTE = [
  "30, 138, 101",  // teal-green
  "52, 152, 200",  // sky blue
  "225, 120, 45",  // warm orange
  "145, 90, 180",  // soft purple
  "210, 65, 95",   // rose
  "55, 175, 100",  // leaf green
  "195, 155, 35",  // golden amber
  "80, 110, 200",  // slate blue
];
const paletteColor = (i, a) => `rgba(${CHART_PALETTE[i % CHART_PALETTE.length]}, ${a})`;

const CURRENCY_RE   = /amount|revenue|cost|price|usd|dollars?|donation|contribution|payment|gift|fee|balance|monetary/i;
const COUNT_RE      = /(^|_)(count|n|num|qty|number)(_|$)|_count$|_n$/i;
const PERCENT_RE    = /(^|_)pct(_|$)|percent/i;

const isNum         = (v)   => typeof v === "number";
const isCountCol    = (col) => COUNT_RE.test(col);
const isPercentCol  = (col) => PERCENT_RE.test(col);
const isCurrencyCol = (col) => CURRENCY_RE.test(col) && !isCountCol(col) && !isPercentCol(col);
// Right-align if count, percent, currency, or other numeric-quantity name
const isQuantityCol = (col) => isCountCol(col) || isPercentCol(col) || isCurrencyCol(col)
                             || /total|sum|avg|mean|ratio/i.test(col);

const currencyFmt = new Intl.NumberFormat(undefined, {
  style: "currency", currency: "USD",
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

// Columns whose values are all numeric (or null) across the dataset.
function numericCols(records) {
  if (!records.length) return [];
  return Object.keys(records[0]).filter(
    (c) => records.some((r) => isNum(r[c])) && records.every((r) => r[c] === null || isNum(r[c]))
  );
}

// ── Misc helpers ──────────────────────────────────────────────
const looksLikeDate = (v) => {
  if (v == null || (typeof v !== "string" && typeof v !== "number")) return false;
  const s = String(v);
  return /\d{4}/.test(s) && !Number.isNaN(Date.parse(s));
};

function detectChartIntent(q) {
  if (!q) return null;
  if (/\bbar\s*(chart|graph|plot)?\b/i.test(q)) return "bar";
  if (/\bline\s*(chart|graph|plot)?\b|\btime\s*series\b|\btrend\b|\bover time\b/i.test(q)) return "line";
  if (/\bpie\s*(chart|graph)?\b|\bdonut\b|\bdoughnut\b/i.test(q)) return "pie";
  if (/\bchart\b|\bgraph\b|\bplot\b|\bvisuali[sz]e\b/i.test(q)) return "auto";
  return null;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ── Rendering ─────────────────────────────────────────────────
function clearResults() {
  sqlBox.hidden = true;
  sqlText.textContent = "";
  resultMeta.hidden = true;
  resultMeta.textContent = "";
  tableWrap.innerHTML = "";
  if (currentChart) { currentChart.destroy(); currentChart = null; }
  chartWrap.hidden = true;
}

function showMeta(records, extra) {
  const parts = [`${records.length} row${records.length === 1 ? "" : "s"}`];
  if (extra) parts.push(extra);
  resultMeta.textContent = parts.join(" · ");
  resultMeta.hidden = false;
}

function renderChart(records, type, spec) {
  if (currentChart) { currentChart.destroy(); currentChart = null; }
  chartWrap.hidden = true;
  chartTitle.textContent = "";
  if (!records || records.length === 0 || type === "none") return;
  if (typeof Chart === "undefined") return;

  const cols     = Object.keys(records[0]);
  const numCols  = numericCols(records);
  const labelCols = cols.filter((c) => !numCols.includes(c));

  const specX    = spec && cols.includes(spec.x) ? spec.x : null;
  const specY    = spec && Array.isArray(spec.y) ? spec.y.filter((c) => numCols.includes(c)) : null;
  const labelCol = specX || labelCols[0] || cols[0];
  const valueCols = (specY && specY.length) ? specY : numCols;
  if (!labelCol || valueCols.length === 0) return;

  const labels = records.map((r) => String(r[labelCol]));
  let resolved = type === "auto"
    ? (looksLikeDate(records[0][labelCol]) ? "line" : "bar")
    : type;

  const currencyCols = valueCols.filter(isCurrencyCol);
  const otherCols    = valueCols.filter((c) => !isCurrencyCol(c));
  const useDualAxis  = resolved !== "pie" && currencyCols.length > 0 && otherCols.length > 0;
  const allCurrency  = !useDualAxis && currencyCols.length === valueCols.length;
  const fmtValue     = (col, v) =>
    (v == null) ? "" : isCurrencyCol(col) ? currencyFmt.format(v) : Number(v).toLocaleString();

  let datasets;
  if (resolved === "pie") {
    const vc = valueCols[0];
    datasets = [{ label: vc, data: records.map((r) => r[vc]),
      backgroundColor: labels.map((_, i) => paletteColor(i, 0.75)),
      borderColor: "#fff", borderWidth: 1 }];
  } else {
    const dense = resolved === "line" && records.length > 50;
    datasets = valueCols.map((c, i) => ({
      label: c, data: records.map((r) => r[c]),
      backgroundColor: paletteColor(i, resolved === "line" ? 0.25 : 0.65),
      borderColor: paletteColor(i, 1), borderWidth: 2,
      fill: resolved === "line" ? false : undefined,
      tension: resolved === "line" ? 0.25 : undefined,
      pointRadius: dense ? 0 : 3, pointHoverRadius: dense ? 3 : 5,
      yAxisID: useDualAxis && isCurrencyCol(c) ? "y1" : "y",
    }));
  }

  let scales = {};
  if (resolved !== "pie") {
    scales.x = { title: { display: true, text: labelCol } };
    scales.y = {
      beginAtZero: true, position: "left",
      ...(useDualAxis ? { title: { display: true, text: otherCols.length === 1 ? otherCols[0] : "Count" } } : {}),
      ...(allCurrency ? { ticks: { callback: (v) => currencyFmt.format(v) } } : {}),
    };
    if (useDualAxis) {
      scales.y1 = {
        beginAtZero: true, position: "right",
        grid: { drawOnChartArea: false },
        title: { display: true, text: currencyCols.length === 1 ? currencyCols[0] : "Amount ($)" },
        ticks: { callback: (v) => currencyFmt.format(v) },
      };
    }
  }

  if (spec && spec.title) chartTitle.textContent = spec.title;
  chartWrap.hidden = false;
  currentChart = new Chart(chartCanvas.getContext("2d"), {
    type: resolved, data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: resolved === "pie" || datasets.length > 1 },
        tooltip: {
          callbacks: {
            label: (ctx) => resolved === "pie"
              ? `${ctx.label}: ${fmtValue(valueCols[0], ctx.parsed)}`
              : `${ctx.dataset.label}: ${fmtValue(ctx.dataset.label, ctx.parsed.y)}`,
          },
        },
      },
      scales,
    },
  });
}

function tableHtml(records) {
  if (!records || records.length === 0) return "<p class='hint'>No rows returned.</p>";
  if (!records.every((r) => r && typeof r === "object" && !Array.isArray(r)))
    return `<ul>${records.map((r) => `<li>${String(r)}</li>`).join("")}</ul>`;

  const cols   = Object.keys(records[0]);
  const numSet = new Set(numericCols(records));
  const isPercent  = (c) => numSet.has(c) && isPercentCol(c);
  const isCurrency = (c) => numSet.has(c) && isCurrencyCol(c);
  const isQuantity = (c) => numSet.has(c) && isQuantityCol(c);
  const cls        = (c) => isQuantity(c) ? ' class="num"' : "";

  const fmt = (v, col) => {
    if (v == null) return "";
    if (typeof v === "number" && isPercent(col))
      return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    if (typeof v === "number" && isCurrency(col)) return currencyFmt.format(v);
    if (typeof v === "number" && isQuantity(col))
      return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return escapeHtml(String(v));
  };

  const head = cols.map((c) => `<th${cls(c)}>${escapeHtml(c)}</th>`).join("");
  const body = records.map(
    (r) => `<tr>${cols.map((c) => `<td${cls(c)}>${fmt(r[c], c)}</td>`).join("")}</tr>`
  ).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderTable(records) {
  tableWrap.innerHTML = tableHtml(records);
}

function renderClarifyingQuestions(questions) {
  tableWrap.innerHTML = `
    <div class="clarify-box">
      <p class="hint">Your question could mean a few different things. Mind answering:</p>
      <ol class="clarify-list">${questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ol>
      <p class="hint">Add those details to your question above and ask again.</p>
    </div>`;
}

// ── Cluster analysis ──────────────────────────────────────────
function renderFactors(rows) {
  if (!rows || rows.length === 0) {
    clusterFactorsEl.innerHTML = "<p class='hint'>No factors to show.</p>";
    return;
  }
  const max = Math.max(...rows.map((r) => r.importance_pct), 1);
  clusterFactorsEl.innerHTML = rows.map((r) => `
    <div class="factor-row">
      <div class="factor-label">${escapeHtml(r.feature.replace(/_/g, " "))}</div>
      <div class="factor-bar"><div class="factor-fill" style="width:${(r.importance_pct / max) * 100}%"></div></div>
      <div class="factor-pct">${r.importance_pct}%</div>
    </div>`).join("");
}

function renderSegmentsTable(segments, nClusters) {
  if (!segments || segments.length === 0) {
    clusterSegmentsTableEl.innerHTML = "<p class='hint'>No segments to show.</p>";
    return;
  }
  const pctFmt = (v) => `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
  const head = ["segment", "donor count", "% of donors", "avg recency (days)", "avg frequency", "avg monetary", "% of total amount", ""]
    .map((c, i) => `<th${i > 0 && c ? ' class="num"' : ""}>${c}</th>`).join("");
  const body = segments.map((s) => {
    const url = `/cluster-analysis/download?segment=${encodeURIComponent(s.segment)}&n_clusters=${encodeURIComponent(nClusters)}`;
    return "<tr>" +
      `<td>${escapeHtml(s.segment)}</td>` +
      `<td class="num">${s.donor_count.toLocaleString()}</td>` +
      `<td class="num">${pctFmt(s.pct_of_donors)}</td>` +
      `<td class="num">${s.avg_recency_days}</td>` +
      `<td class="num">${s.avg_frequency}</td>` +
      `<td class="num">${currencyFmt.format(s.avg_monetary)}</td>` +
      `<td class="num">${pctFmt(s.pct_of_total_amount)}</td>` +
      `<td><a class="download-link" href="${url}" download>Download CSV</a></td>` +
      "</tr>";
  }).join("");
  clusterSegmentsTableEl.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function runClusterAnalysis() {
  clusterOutputEl.hidden = true;
  setStatus(clusterStatusEl, "loading", "Clustering donors…");
  clusterBtn.disabled = true;
  try {
    const n = clusterCountEl.value;
    const res = await fetch(`/cluster-analysis?n_clusters=${encodeURIComponent(n)}`);
    const data = await res.json();
    if (!res.ok) { setStatus(clusterStatusEl, "error", data.detail || "Something went wrong."); return; }
    setStatus(clusterStatusEl, "ok", "Done.");
    const likelyUrl = `/cluster-analysis/download-likely?n_clusters=${encodeURIComponent(n)}`;
    clusterSummaryEl.innerHTML =
      `${data.donor_count} donors · ${data.likely_donor_count ?? 0} likely donors (3+ gifts in last 90 days) ` +
      `<a class="download-link" href="${likelyUrl}" download>Download likely donors CSV</a>`;
    renderSegmentsTable(data.segments, data.n_clusters || n);
    renderFactors(data.feature_importance);
    clusterTopDonorsTableEl.innerHTML = tableHtml(data.top_donors);
    clusterNoteEl.textContent = data.note || "";
    clusterOutputEl.hidden = false;
  } catch (err) {
    setStatus(clusterStatusEl, "error", `Network error: ${err.message}`);
  } finally {
    clusterBtn.disabled = false;
  }
}

// ── Query ─────────────────────────────────────────────────────
async function ask() {
  const q = questionEl.value.trim();
  if (!q) { setStatus(statusEl, "error", "Type a question first."); return; }
  clearResults();
  setStatus(statusEl, "loading", "Thinking…");
  askBtn.disabled = true;
  try {
    const res = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, explain_sql: showSqlEl.checked }),
    });
    const data = await res.json();
    if (!res.ok) { setStatus(statusEl, "error", data.detail || "Something went wrong."); return; }
    if (Array.isArray(data.clarifying_questions) && data.clarifying_questions.length) {
      setStatus(statusEl, "ok", "I need a bit more detail before I can run that.");
      renderClarifyingQuestions(data.clarifying_questions);
      return;
    }
    setStatus(statusEl, "ok", "Done.");
    if (showSqlEl.checked && data.sql) { sqlText.textContent = data.sql; sqlBox.hidden = false; }
    showMeta(data.records, data.s3_url ? `Saved to ${data.s3_url}` : null);
    renderTable(data.records);
    const chartType = (data.chart && data.chart.type) || detectChartIntent(q) || chartTypeEl.value;
    renderChart(data.records, chartType, data.chart);
  } catch (err) {
    setStatus(statusEl, "error", `Network error: ${err.message}`);
  } finally {
    askBtn.disabled = false;
  }
}

async function runTask(name) {
  clearResults();
  setStatus(statusEl, "loading", `Running report: ${name}…`);
  try {
    const res = await fetch("/run-task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_name: name }),
    });
    const data = await res.json();
    if (!res.ok) { setStatus(statusEl, "error", data.detail || "Something went wrong."); return; }
    setStatus(statusEl, "ok", `Report '${name}' finished.`);
    let rows = null;
    if (Array.isArray(data.records)) {
      showMeta(data.records, data.output_path ? `Saved to ${data.output_path}` : null);
      renderTable(data.records);
      rows = data.records;
    } else {
      const result = Array.isArray(data.results) ? data.results[0] : data.results;
      if (typeof result === "string") {
        resultMeta.textContent = `Output saved to ${result}.`;
        resultMeta.hidden = false;
      } else if (Array.isArray(result)) {
        showMeta(result);
        renderTable(result);
        rows = result;
      }
    }
    if (rows) renderChart(rows, chartTypeEl.value === "auto" ? "bar" : chartTypeEl.value);
  } catch (err) {
    setStatus(statusEl, "error", `Network error: ${err.message}`);
  }
}

// ── Task list ─────────────────────────────────────────────────
async function loadTasks() {
  try {
    const res = await fetch("/tasks");
    const data = await res.json();
    const tasks = data.tasks || [];
    if (tasks.length === 0) { taskList.innerHTML = "<li class='muted'>No reports defined.</li>"; return; }
    taskList.innerHTML = "";
    for (const name of tasks) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.className = "task-btn";
      btn.type = "button";
      btn.textContent = name.replace(/_/g, " ");
      btn.title = name;
      btn.addEventListener("click", () => runTask(name));
      li.appendChild(btn);
      taskList.appendChild(li);
    }
  } catch (err) {
    taskList.innerHTML = `<li class='muted'>Couldn't load reports: ${err.message}</li>`;
  }
}

// ── Init ──────────────────────────────────────────────────────
askBtn.addEventListener("click", ask);
questionEl.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") ask(); });
clusterBtn.addEventListener("click", runClusterAnalysis);

loadTasks().then(() => {
  const params = new URLSearchParams(window.location.search);
  const initialChart = params.get("chart");
  if (initialChart) chartTypeEl.value = initialChart;
  const initialTask = params.get("task");
  if (initialTask) runTask(initialTask);
  const initialQ = params.get("q");
  if (initialQ) { questionEl.value = initialQ; ask(); }
});
