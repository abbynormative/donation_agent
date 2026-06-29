const $ = (id) => document.getElementById(id);
const askBtn = $("ask-btn");
const questionEl = $("question");
const showSqlEl = $("show-sql");
const chartTypeEl = $("chart-type");
const statusEl = $("status");
const sqlBox = $("sql-box");
const sqlText = $("sql-text");
const resultMeta = $("result-meta");
const tableWrap = $("table-wrap");
const chartWrap = $("chart-wrap");
const chartTitle = $("chart-title");
const chartCanvas = $("chart-canvas");
const taskList = $("task-list");

let currentChart = null;

function setStatus(kind, msg) {
  if (!msg) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    return;
  }
  statusEl.hidden = false;
  statusEl.className = `status ${kind}`;
  statusEl.textContent = msg;
}

function clearResults() {
  sqlBox.hidden = true;
  sqlText.textContent = "";
  resultMeta.hidden = true;
  resultMeta.textContent = "";
  tableWrap.innerHTML = "";
  if (currentChart) {
    currentChart.destroy();
    currentChart = null;
  }
  chartWrap.hidden = true;
}

function detectChartIntent(q) {
  if (!q) return null;
  if (/\bbar\s*(chart|graph|plot)?\b/i.test(q)) return "bar";
  if (/\bline\s*(chart|graph|plot)?\b|\btime\s*series\b|\btrend\b|\bover time\b/i.test(q)) return "line";
  if (/\bpie\s*(chart|graph)?\b|\bdonut\b|\bdoughnut\b/i.test(q)) return "pie";
  if (/\bchart\b|\bgraph\b|\bplot\b|\bvisuali[sz]e\b/i.test(q)) return "auto";
  return null;
}

const CHART_PALETTE = [
  "54, 162, 235", "255, 99, 132", "75, 192, 192", "255, 159, 64",
  "153, 102, 255", "255, 205, 86", "201, 203, 207", "100, 181, 246",
];
const paletteColor = (i, alpha) => `rgba(${CHART_PALETTE[i % CHART_PALETTE.length]}, ${alpha})`;

const looksLikeDate = (v) => {
  if (v == null) return false;
  if (typeof v !== "string" && typeof v !== "number") return false;
  const s = String(v);
  if (!/\d{4}/.test(s)) return false;
  const d = Date.parse(s);
  return !Number.isNaN(d);
};

function renderChart(records, type, spec) {
  if (currentChart) { currentChart.destroy(); currentChart = null; }
  chartWrap.hidden = true;
  chartTitle.textContent = "";
  if (!records || records.length === 0 || type === "none") return;
  if (typeof Chart === "undefined") return;

  const cols = Object.keys(records[0]);
  const isNum = (v) => typeof v === "number";
  const numCols = cols.filter((c) => records.some((r) => isNum(r[c])) && records.every((r) => r[c] === null || isNum(r[c])));
  const labelCols = cols.filter((c) => !numCols.includes(c));

  const specX = spec && cols.includes(spec.x) ? spec.x : null;
  const specY = spec && Array.isArray(spec.y) ? spec.y.filter((c) => numCols.includes(c)) : null;

  const labelCol = specX || labelCols[0] || cols[0];
  const valueCols = (specY && specY.length) ? specY : numCols;
  if (!labelCol || valueCols.length === 0) return;

  const labels = records.map((r) => String(r[labelCol]));

  let resolved = type;
  if (resolved === "auto") {
    resolved = looksLikeDate(records[0][labelCol]) ? "line" : "bar";
  }

  let datasets;
  if (resolved === "pie") {
    const valueCol = valueCols[0];
    datasets = [{
      label: valueCol,
      data: records.map((r) => r[valueCol]),
      backgroundColor: labels.map((_, i) => paletteColor(i, 0.75)),
      borderColor: "#fff",
      borderWidth: 1,
    }];
  } else {
    const dense = resolved === "line" && records.length > 50;
    datasets = valueCols.map((c, i) => ({
      label: c,
      data: records.map((r) => r[c]),
      backgroundColor: paletteColor(i, resolved === "line" ? 0.25 : 0.65),
      borderColor: paletteColor(i, 1),
      borderWidth: 2,
      fill: resolved === "line" ? false : undefined,
      tension: resolved === "line" ? 0.25 : undefined,
      pointRadius: dense ? 0 : 3,
      pointHoverRadius: dense ? 3 : 5,
    }));
  }

  if (spec && spec.title) chartTitle.textContent = spec.title;
  chartWrap.hidden = false;
  currentChart = new Chart(chartCanvas.getContext("2d"), {
    type: resolved,
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: resolved === "pie" || datasets.length > 1 },
      },
      scales: resolved === "pie" ? {} : {
        x: { title: { display: true, text: labelCol } },
        y: { beginAtZero: true },
      },
    },
  });
}

function tableHtml(records) {
  if (!records || records.length === 0) {
    return "<p class='hint'>No rows returned.</p>";
  }
  const allObjects = records.every((r) => r && typeof r === "object" && !Array.isArray(r));
  if (!allObjects) {
    const items = records.map((r) => `<li>${String(r)}</li>`).join("");
    return `<ul>${items}</ul>`;
  }
  const cols = Object.keys(records[0]);
  const isNum = (v) => typeof v === "number";
  const numCols = new Set(cols.filter((c) => records.every((r) => r[c] === null || isNum(r[c]))));
  const QUANTITY_RE = /count|amount|total|sum|avg|average|mean|pct|percent|ratio/i;
  const CURRENCY_RE = /amount|revenue|cost|price|usd|dollars?|donation|contribution|payment|gift|fee|balance/i;
  const COUNT_RE = /(^|_)(count|n|num|qty|number)(_|$)|_count$|_n$/i;
  const isCount = (col) => COUNT_RE.test(col);
  const isCurrency = (col) => numCols.has(col) && CURRENCY_RE.test(col) && !isCount(col);
  const isQuantity = (col) => numCols.has(col) && QUANTITY_RE.test(col);

  const currencyFmt = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const fmt = (v, col) => {
    if (v === null || v === undefined) return "";
    if (typeof v === "number" && isCurrency(col)) {
      return currencyFmt.format(v);
    }
    if (typeof v === "number" && isQuantity(col)) {
      return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(v);
  };

  const head = cols.map((c) => `<th class="${isQuantity(c) ? "num" : ""}">${c}</th>`).join("");
  const body = records
    .map(
      (r) =>
        "<tr>" +
        cols.map((c) => `<td class="${isQuantity(c) ? "num" : ""}">${fmt(r[c], c)}</td>`).join("") +
        "</tr>"
    )
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderTable(records) {
  tableWrap.innerHTML = tableHtml(records);
}

function showMeta(records, extra) {
  const parts = [`${records.length} row${records.length === 1 ? "" : "s"}`];
  if (extra) parts.push(extra);
  resultMeta.textContent = parts.join(" · ");
  resultMeta.hidden = false;
}

async function ask() {
  const q = questionEl.value.trim();
  if (!q) {
    setStatus("error", "Type a question first.");
    return;
  }
  clearResults();
  setStatus("loading", "Thinking…");
  askBtn.disabled = true;
  try {
    const res = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, explain_sql: showSqlEl.checked }),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus("error", data.detail || "Something went wrong.");
      return;
    }
    setStatus("ok", "Done.");
    if (showSqlEl.checked && data.sql) {
      sqlText.textContent = data.sql;
      sqlBox.hidden = false;
    }
    showMeta(data.records, data.s3_url ? `Saved to ${data.s3_url}` : null);
    renderTable(data.records);
    const intent = detectChartIntent(q);
    const chartType = (data.chart && data.chart.type) || intent || chartTypeEl.value;
    renderChart(data.records, chartType, data.chart);
  } catch (err) {
    setStatus("error", `Network error: ${err.message}`);
  } finally {
    askBtn.disabled = false;
  }
}

async function runTask(name) {
  clearResults();
  setStatus("loading", `Running report: ${name}…`);
  try {
    const res = await fetch("/run-task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_name: name }),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus("error", data.detail || "Something went wrong.");
      return;
    }
    setStatus("ok", `Report '${name}' finished.`);
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
    if (rows) {
      const t = chartTypeEl.value === "auto" ? "bar" : chartTypeEl.value;
      renderChart(rows, t);
    }
  } catch (err) {
    setStatus("error", `Network error: ${err.message}`);
  }
}

const clusterBtn = $("cluster-btn");
const clusterCountEl = $("cluster-count");
const clusterStatusEl = $("cluster-status");
const clusterOutputEl = $("cluster-output");
const clusterSummaryEl = $("cluster-summary");
const clusterSegmentsTableEl = $("cluster-segments-table");
const clusterFactorsEl = $("cluster-factors");
const clusterTopDonorsTableEl = $("cluster-top-donors-table");
const clusterNoteEl = $("cluster-note");

function setClusterStatus(kind, msg) {
  if (!msg) {
    clusterStatusEl.hidden = true;
    clusterStatusEl.textContent = "";
    return;
  }
  clusterStatusEl.hidden = false;
  clusterStatusEl.className = `status ${kind}`;
  clusterStatusEl.textContent = msg;
}

function renderFactors(rows) {
  if (!rows || rows.length === 0) {
    clusterFactorsEl.innerHTML = "<p class='hint'>No factors to show.</p>";
    return;
  }
  const max = Math.max(...rows.map((r) => r.importance_pct), 1);
  clusterFactorsEl.innerHTML = rows
    .map(
      (r) => `
      <div class="factor-row">
        <div class="factor-label">${r.feature.replace(/_/g, " ")}</div>
        <div class="factor-bar"><div class="factor-fill" style="width:${(r.importance_pct / max) * 100}%"></div></div>
        <div class="factor-pct">${r.importance_pct}%</div>
      </div>`
    )
    .join("");
}

async function runClusterAnalysis() {
  clusterOutputEl.hidden = true;
  setClusterStatus("loading", "Clustering donors…");
  clusterBtn.disabled = true;
  try {
    const n = clusterCountEl.value;
    const res = await fetch(`/cluster-analysis?n_clusters=${encodeURIComponent(n)}`);
    const data = await res.json();
    if (!res.ok) {
      setClusterStatus("error", data.detail || "Something went wrong.");
      return;
    }
    setClusterStatus("ok", "Done.");
    clusterSummaryEl.textContent = `${data.donor_count} donors · likely-donor segment: ${data.likely_donor_segment}`;
    clusterSegmentsTableEl.innerHTML = tableHtml(data.segments);
    renderFactors(data.feature_importance);
    clusterTopDonorsTableEl.innerHTML = tableHtml(data.top_donors);
    clusterNoteEl.textContent = data.note || "";
    clusterOutputEl.hidden = false;
  } catch (err) {
    setClusterStatus("error", `Network error: ${err.message}`);
  } finally {
    clusterBtn.disabled = false;
  }
}

clusterBtn.addEventListener("click", runClusterAnalysis);

async function loadTasks() {
  try {
    const res = await fetch("/tasks");
    const data = await res.json();
    const tasks = data.tasks || [];
    if (tasks.length === 0) {
      taskList.innerHTML = "<li class='muted'>No reports defined.</li>";
      return;
    }
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

askBtn.addEventListener("click", ask);
questionEl.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") ask();
});

loadTasks().then(() => {
  const params = new URLSearchParams(window.location.search);
  const initialChart = params.get("chart");
  if (initialChart) chartTypeEl.value = initialChart;
  const initialTask = params.get("task");
  if (initialTask) runTask(initialTask);
  const initialQ = params.get("q");
  if (initialQ) {
    questionEl.value = initialQ;
    ask();
  }
});
