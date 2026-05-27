# Skill: Chart Maker

## Purpose
Guide the SQL-generation agent when a user wants a chart. The agent must:
1. Pick the right chart type for the question and data
2. Shape the SQL so its result rows render cleanly in Chart.js (bar / line / pie)
3. Return a chart spec (type, x, y, title) alongside the SQL

This skill is loaded into the model's prompt whenever the user's question contains chart intent (e.g. "chart", "graph", "plot", "trend", "over time", "bar", "line", "pie", "visualize").

## Supported chart types
The UI renders charts with Chart.js. Three types are supported:
- `bar` — comparing values across categories (states, zip codes, segments).
- `line` — values over time (a date or month bucket on the x-axis).
- `pie` — share of a whole, ≤ 6 slices, single numeric metric.

## Choosing the chart type

| Signal in the question | Use |
|---|---|
| "over time", "trend", "by month/week/day", date axis | `line` |
| "top N", "compare", "by state/zip/category" | `bar` |
| "share", "breakdown", "percent of", "proportion" | `pie` |
| Generic "chart" / "graph" / "plot" with categorical data | `bar` |
| Generic "chart" / "graph" / "plot" with time axis | `line` |

If the user explicitly says "bar chart" / "line chart" / "pie chart", honor it.

## SQL shaping rules

**Always:**
- First selected column = the label / x-axis (categorical or date bucket).
- Remaining selected columns = numeric metrics on the y-axis.
- Use descriptive aliases (`total_amount`, `donation_count`, `avg_amount`) — the column name shows up in the chart legend and table header.
- One statement, SELECT only.

**Bar charts:**
- `ORDER BY <primary_metric> DESC`
- `LIMIT 20` at most (10 is usually better for readability)
- Categorical x; numeric y (one or two metrics max — more than two becomes hard to read).

**Line charts (time series):**
- Truncate the date column with `strftime`:
  - `strftime('%Y-%m-%d', col)` for ≤ 60-day ranges
  - `strftime('%Y-%m', col)` for ≤ 24-month ranges
  - `strftime('%Y', col)` for multi-year ranges
- `GROUP BY` the truncated column, `ORDER BY` it ASC.
- Aggregate values (`SUM`, `COUNT`, `AVG`) — never return raw rows for a time series.
- Cap output at ~500 buckets.

**Pie charts:**
- Single numeric column.
- `LIMIT 6` (or wrap the long tail as "Other" with a UNION if more granularity is needed).
- `ORDER BY <metric> DESC`.

## Chart spec output

Return a **single JSON object** with no prose, no code fences. Schema:

```
{
  "sql":   "SELECT ...",
  "chart": {
    "type":  "bar" | "line" | "pie",
    "x":     "<column name used on the x-axis>",
    "y":     ["<metric col 1>", "<metric col 2>"],
    "title": "<one-line takeaway, see rules below>"
  }
}
```

### Title rules
The title goes above the chart and is the headline a non-technical reader sees first. It must:
- State the **takeaway**, not describe the chart. Good: `"CA leads donation totals at $10.7K"`. Bad: `"Total amount by state"`.
- Be specific where possible — include the leader, the range, the trend direction, or the total. Use the SQL preview to fill in numbers if you can; otherwise stay descriptive but precise (e.g. `"Monthly donation totals over the past year"`).
- Stay under ~80 characters.

## Worked examples

### 1. Line chart, time series
**Question:** "please give me a line chart of all donations over time"
**Response:**
```json
{
  "sql": "SELECT strftime('%Y-%m', donated_at) AS month, SUM(amount) AS total_amount FROM donations GROUP BY month ORDER BY month",
  "chart": {
    "type": "line",
    "x": "month",
    "y": ["total_amount"],
    "title": "Monthly donation totals over the past year"
  }
}
```

### 2. Bar chart, top N
**Question:** "show me the top 5 states by donation amount"
**Response:**
```json
{
  "sql": "SELECT state, SUM(amount) AS total_amount FROM donations GROUP BY state ORDER BY total_amount DESC LIMIT 5",
  "chart": {
    "type": "bar",
    "x": "state",
    "y": ["total_amount"],
    "title": "Top 5 states by total donation amount"
  }
}
```

### 3. Pie chart, share of total
**Question:** "what share of donations comes from each state? show a pie chart"
**Response:**
```json
{
  "sql": "SELECT state, SUM(amount) AS total_amount FROM donations GROUP BY state ORDER BY total_amount DESC LIMIT 6",
  "chart": {
    "type": "pie",
    "x": "state",
    "y": ["total_amount"],
    "title": "Share of donation total by state (top 6)"
  }
}
```

## Validation
Before responding, self-check:
1. SQL is a single SELECT, no DML/DDL, no semicolons inside the statement.
2. The chart's `x` column is the first selected column.
3. Every name in `chart.y` is one of the remaining selected columns.
4. Row count is capped per the rules above.
5. The title states a takeaway, not "X by Y".

If the question doesn't actually call for a chart, omit the `chart` field and just return `{"sql": "..."}`.
