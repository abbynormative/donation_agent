# Skill: SQL Author

## Purpose
Guide the agent in writing **correct, executable** SQL for analytics requests against the donation database. This skill targets the most common LLM SQL failure modes — unbalanced parentheses, missing commas, ambiguous columns, GROUP BY mismatches — and gives a pre-flight self-check the model must run before responding.

Load this skill on every SQL-generation call. When also producing a chart, this skill works alongside `chart-maker` (sql-author owns correctness; chart-maker owns shape and presentation).

## Dialect
The target dialect is **SQLite**. Use SQLite-specific syntax where it differs from Postgres/MySQL.

## Output rules (hard requirements)
1. **One** SQL statement only. No multi-statement scripts.
2. **SELECT only.** No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `REPLACE`, `PRAGMA`, `ATTACH`, `EXEC`.
3. **No trailing semicolon.** The host strips one if present, but don't rely on it.
4. **No SQL comments** (`--` or `/* */`) in the output.
5. **No prose** around the SQL. If you also need to emit a chart spec, follow the `chart-maker` skill's JSON envelope; otherwise emit bare SQL.
6. **Use only columns and tables that appear in the provided schema.** If something the user asked for isn't in the schema, pick the closest available column rather than invent one.

## Author the query (chain of thought)
Work through these steps internally before writing the final SQL:

1. **Restate the question** in one sentence. What entity is the user asking about? What's the unit of analysis (a donor, a donation, a day, a state)?
2. **Identify the columns you need.** For each, confirm it exists in the schema.
3. **Decide on aggregation.** If the answer is a single number per group → `GROUP BY` that group. If the answer is a list of raw rows → no aggregation, just `WHERE`/`ORDER BY`/`LIMIT`.
4. **Decide on filtering.** Time window? Status filter? Express it in `WHERE`.
5. **Decide on ordering and limiting.** Top-N questions always need both `ORDER BY` and `LIMIT`. Time-series always orders by the date ASC.
6. **Write the SQL.** Use clear aliases (`AS total_amount`, `AS donation_count`, `AS donor_count`) — these names appear in the UI table headers and chart legends.

## Syntax checklist (run BEFORE responding)
Mentally parse the SQL you just wrote and verify each item:

### Brackets and quotes
- [ ] Every `(` has a matching `)`. Count them: the totals must be equal. This applies to function calls, subqueries, CTEs, `IN (...)` lists, and `CASE WHEN ... END` expressions.
- [ ] Every `CASE` has a matching `END`. (Note: `END`, not `END CASE`.)
- [ ] Every single-quoted string literal closes on the same line: `'2025-01-01'`, never `'2025-01-01` followed by a newline before the closing quote.
- [ ] Every double-quoted or backtick-quoted identifier closes properly.

### Commas
- [ ] No trailing comma after the last item in a `SELECT` list, `GROUP BY` list, `ORDER BY` list, or function argument list. `SELECT a, b, FROM t` and `GROUP BY a, b,` are both invalid.
- [ ] Every adjacent pair of expressions in those same lists is separated by exactly one comma.

### Clause order and presence
- [ ] Clauses appear in the order: `WITH ... SELECT ... FROM ... [JOIN ...] [WHERE ...] [GROUP BY ...] [HAVING ...] [ORDER BY ...] [LIMIT ...]`.
- [ ] `WHERE` filters rows. `HAVING` filters groups. Don't put aggregates in `WHERE` — use `HAVING`.
- [ ] If you use any aggregate function (`SUM`, `COUNT`, `AVG`, `MIN`, `MAX`), **every** non-aggregated column in `SELECT` must also be in `GROUP BY`. SQLite tolerates violations of this rule with silently-wrong results — don't rely on its tolerance.

### Aliases and references
- [ ] Every alias defined with `AS` in `SELECT` can be referenced in `ORDER BY` and `GROUP BY`, but **not** in `WHERE` or `HAVING` (use the expression there, or wrap in a subquery / CTE).
- [ ] If you join multiple tables, **qualify every column** with its table or table-alias to avoid ambiguity: `d.amount`, not just `amount`.
- [ ] Table aliases are defined in `FROM` / `JOIN` and used everywhere else.

### Joins
- [ ] Every `JOIN` has an `ON` clause (or `USING`).
- [ ] Use `LEFT JOIN` if rows from the left table should be preserved when there's no match on the right. Use `INNER JOIN` (or plain `JOIN`) when both sides are required.

## SQLite-specific patterns

### Dates and times
- Date truncation uses `strftime`, not `DATE_TRUNC`:
  - Day: `strftime('%Y-%m-%d', donated_at)`
  - Week: `strftime('%Y-W%W', donated_at)`
  - Month: `strftime('%Y-%m', donated_at)`
  - Year: `strftime('%Y', donated_at)`
- Relative dates: `DATE('now', '-30 days')`, `DATETIME('now', '-1 hour')`.
- Comparing date columns: SQLite stores dates as TEXT in ISO 8601 — string comparison works (`donated_at >= '2025-01-01'`).

### Strings and nulls
- Concatenation is `||`, not `CONCAT(...)`: `first || ' ' || last`.
- Pattern match: `LIKE 'CA%'`, case-insensitive on ASCII.
- Null-safe equality: `IS NULL`, `IS NOT NULL`. `= NULL` is always false.
- Fallback values: `COALESCE(x, 0)` or `IFNULL(x, 0)`.

### Conditionals
- Prefer `CASE WHEN ... THEN ... ELSE ... END` for portability.
- `IIF(cond, a, b)` is shorter for two-way conditionals and works in SQLite.

### Window functions
SQLite ≥ 3.25 supports window functions. Common shape:
```
SELECT zip,
       donation_count,
       ROUND(100.0 * donation_count / SUM(donation_count) OVER (), 2) AS pct_of_total
FROM (SELECT zip, COUNT(*) AS donation_count FROM donations GROUP BY zip) s
ORDER BY donation_count DESC
LIMIT 20
```

### CTEs over deep nesting
For anything more complex than two levels of subquery, use a CTE — it's easier to write, easier for a parser to validate, and easier for a reader to follow:
```
WITH monthly AS (
  SELECT strftime('%Y-%m', donated_at) AS month, SUM(amount) AS total_amount
  FROM donations
  GROUP BY month
)
SELECT month, total_amount,
       total_amount - LAG(total_amount) OVER (ORDER BY month) AS mom_change
FROM monthly
ORDER BY month
```

## Common pitfalls (with fixes)

### Pitfall: missing GROUP BY column
```
-- BAD: state is selected but not aggregated or grouped
SELECT state, donor_name, SUM(amount) AS total
FROM donations
GROUP BY state

-- GOOD: include all non-aggregated SELECT columns in GROUP BY
SELECT state, donor_name, SUM(amount) AS total
FROM donations
GROUP BY state, donor_name
```

### Pitfall: aggregate in WHERE
```
-- BAD
SELECT state, SUM(amount) AS total FROM donations WHERE SUM(amount) > 1000 GROUP BY state

-- GOOD: filter groups in HAVING
SELECT state, SUM(amount) AS total
FROM donations
GROUP BY state
HAVING SUM(amount) > 1000
```

### Pitfall: alias in WHERE
```
-- BAD: total_amount alias not visible in WHERE
SELECT zip, SUM(amount) AS total_amount FROM donations WHERE total_amount > 500 GROUP BY zip

-- GOOD: use HAVING (it's a group filter), or repeat the expression
SELECT zip, SUM(amount) AS total_amount
FROM donations
GROUP BY zip
HAVING SUM(amount) > 500
```

### Pitfall: forgetting LIMIT on top-N
```
-- BAD: returns everything
SELECT zip, COUNT(*) AS donation_count FROM donations GROUP BY zip ORDER BY donation_count DESC

-- GOOD
SELECT zip, COUNT(*) AS donation_count
FROM donations
GROUP BY zip
ORDER BY donation_count DESC
LIMIT 10
```

### Pitfall: unbalanced parens in nested expression
```
-- BAD: ROUND( ... has 2 '(' but only 1 ')'
SELECT zip, ROUND(100.0 * COUNT(*) / SUM(COUNT(*) OVER ()), 2 AS pct
FROM donations
GROUP BY zip

-- GOOD
SELECT zip, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM donations
GROUP BY zip
```
Always count `(` and `)` after writing nested function calls.

### Pitfall: trailing comma after last column
```
-- BAD
SELECT zip, state, COUNT(*) AS donation_count,
FROM donations
GROUP BY zip, state

-- GOOD: no comma before FROM
SELECT zip, state, COUNT(*) AS donation_count
FROM donations
GROUP BY zip, state
```

### Pitfall: returning raw rows when a trend was asked
```
-- BAD for "donations over time": one row per donation, hundreds of rows
SELECT donated_at, amount FROM donations ORDER BY donated_at

-- GOOD: aggregate by a date bucket
SELECT strftime('%Y-%m', donated_at) AS month, SUM(amount) AS total_amount
FROM donations
GROUP BY month
ORDER BY month
```

## Final self-check (do this before emitting the SQL)
Run this end-to-end:

1. **Paren count.** Scan the statement once and count `(` and `)`. Equal? If no — fix and re-scan.
2. **Quote count.** Every `'` paired with another `'`? Same for `"` and `` ` ``? If no — fix.
3. **CASE/END.** Every `CASE` paired with `END`? If no — fix.
4. **Trailing comma?** Look at the token just before every `FROM`, `WHERE`, `GROUP`, `ORDER`, `LIMIT`, and `)`. If it's a comma, remove it.
5. **Aggregation check.** If any aggregate appears: do all non-aggregated SELECT columns appear in GROUP BY? If no — add them or remove from SELECT.
6. **Single-statement, SELECT-only.** No `;` inside the body, no DML/DDL keywords.
7. **All identifiers exist in schema.** If anything references a column not in the supplied schema, swap it for the right one or remove it.
8. **Top-N has both ORDER BY and LIMIT.** Time-series has ORDER BY ASC on the bucket.

If any check fails, fix the SQL and re-run the entire checklist. Do not emit SQL that fails any check.
