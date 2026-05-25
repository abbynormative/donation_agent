const $ = (id) => document.getElementById(id);
const askBtn = $("ask-btn");
const questionEl = $("question");
const showSqlEl = $("show-sql");
const statusEl = $("status");
const sqlBox = $("sql-box");
const sqlText = $("sql-text");
const resultMeta = $("result-meta");
const tableWrap = $("table-wrap");
const taskList = $("task-list");

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
}

function renderTable(records) {
  if (!records || records.length === 0) {
    tableWrap.innerHTML = "<p class='hint'>No rows returned.</p>";
    return;
  }
  const allObjects = records.every((r) => r && typeof r === "object" && !Array.isArray(r));
  if (!allObjects) {
    const items = records.map((r) => `<li>${String(r)}</li>`).join("");
    tableWrap.innerHTML = `<ul>${items}</ul>`;
    return;
  }
  const cols = Object.keys(records[0]);
  const isNum = (v) => typeof v === "number";
  const numCols = new Set(cols.filter((c) => records.every((r) => r[c] === null || isNum(r[c]))));
  const QUANTITY_RE = /count|amount|total|sum|avg|average|mean|pct|percent|ratio/i;
  const CURRENCY_RE = /amount|revenue|cost|price|usd|dollars?/i;
  const isCurrency = (col) => numCols.has(col) && CURRENCY_RE.test(col);
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
  tableWrap.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
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
    if (Array.isArray(data.records)) {
      showMeta(data.records, data.output_path ? `Saved to ${data.output_path}` : null);
      renderTable(data.records);
    } else {
      const result = Array.isArray(data.results) ? data.results[0] : data.results;
      if (typeof result === "string") {
        resultMeta.textContent = `Output saved to ${result}.`;
        resultMeta.hidden = false;
      } else if (Array.isArray(result)) {
        showMeta(result);
        renderTable(result);
      }
    }
  } catch (err) {
    setStatus("error", `Network error: ${err.message}`);
  }
}

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

loadTasks();
