# Donation Agent

This project contains a conversational MCP-ready agent for donation analytics. It exposes a natural-language API that converts user questions into safe SQL, queries the database, returns results, and can optionally upload artifacts to S3.

## What’s included

- `conversational_agent.py` — a FastAPI service that accepts natural-language questions and returns query results, and also serves a simple web UI.
- `static/` — the browser UI (`index.html`, `styles.css`, `app.js`) for non-technical users.
- `mcp_agent.py` — a flexible command-line agent for direct SQL, CSV loading, and task execution.
- `agent_tasks.yaml` — built-in common analytics tasks such as top zip/state donation summaries.
- `seed_donations.py` — generates an example `donations` table for local development.
- `run_queries.py` — legacy batch query runner.
- `Dockerfile` — container image for the conversational service.
- GitHub Actions workflow for build and deploy.

## Local setup

```bash
cd /Users/heather/donation-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Required environment variables

```bash
export DATABASE_URL=sqlite:///donations.db
export OPENAI_API_KEY=your-openai-api-key
export OUTDIR=outputs
```

Optional environment variables:

```bash
export S3_BUCKET=my-bucket
export S3_PREFIX=reports/donations
export OPENAI_MODEL=gpt-4o-mini
export TASK_FILE=agent_tasks.yaml
```

## Run the conversational agent locally

```bash
uvicorn conversational_agent:app --host 0.0.0.0 --port 8080
```

The service will be available at `http://localhost:8080`.

## Web UI for non-technical users

Open `http://localhost:8080/` in a browser. The UI provides:

- A text box for plain-English questions, with an optional "Show the SQL" toggle.
- Buttons for every report defined in `agent_tasks.yaml` (loaded from `/tasks`).
- A results table rendered from the JSON response. CSV exports are still written to `OUTDIR` (or S3) by the backend.

The UI is plain HTML/CSS/JS served from `static/` — no build step required.

## Seed example data (local dev)

If you don't have a `donations` table yet, generate one with:

```bash
python seed_donations.py            # 1000 rows into $DATABASE_URL
python seed_donations.py --rows 5000
```

The table has columns `id, donor_name, amount, zip, state, donated_at` — matching the queries in `agent_tasks.yaml`.

## Conversational query examples

Use the `/query` endpoint for natural-language questions.

```bash
curl -X POST http://localhost:8080/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "What are the top 10 zip codes by donation count?", "explain_sql": true}'
```

Example response:

- `sql` — the generated SQL query
- `records` — query results as JSON rows
- `explanation` — optional SQL returned when `explain_sql` is true
- `s3_url` — optional CSV upload location

## Run existing task definitions

The agent can also execute predefined tasks from `agent_tasks.yaml`.

Run a single task by name:

```bash
python mcp_agent.py run-task --task-file agent_tasks.yaml --task-name top_10_zips_by_donation_count
```

Run all tasks in the file:

```bash
python mcp_agent.py run-tasks --task-file agent_tasks.yaml
```

List and inspect available tasks:

```bash
python mcp_agent.py list-tables
python mcp_agent.py describe-table --table donations
```

## Built-in common query tasks

The default `agent_tasks.yaml` includes these queries:

- `top_10_zips_by_donation_count`
  ```sql
  SELECT zip, COUNT(*) AS donation_count, SUM(amount) AS total_amount
  FROM donations
  GROUP BY zip
  ORDER BY donation_count DESC
  LIMIT 10;
  ```
- `top_10_states_by_donation_count`
  ```sql
  SELECT state, COUNT(*) AS donation_count, SUM(amount) AS total_amount
  FROM donations
  GROUP BY state
  ORDER BY donation_count DESC
  LIMIT 10;
  ```
- `top_10_zips_by_total_amount`
  ```sql
  SELECT zip, SUM(amount) AS total_amount, COUNT(*) AS donation_count
  FROM donations
  GROUP BY zip
  ORDER BY total_amount DESC
  LIMIT 10;
  ```
- `top_10_states_by_total_amount`
  ```sql
  SELECT state, SUM(amount) AS total_amount, COUNT(*) AS donation_count
  FROM donations
  GROUP BY state
  ORDER BY total_amount DESC
  LIMIT 10;
  ```
- `donation_summary_by_zip`
- `donation_summary_by_state`

## Docker / MCP deployment

Build the container locally:

```bash
docker build -t donation-agent:latest .
```

Run locally:

```bash
docker run --rm -p 8080:8080 \
  -e DATABASE_URL=sqlite:///donations.db \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e OUTDIR=/data/outputs \
  -e S3_BUCKET=my-bucket \
  -e S3_PREFIX=reports/donations \
  donation-agent:latest
```

Deploy with MCP:

- Set secrets: `REGISTRY`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`, `DATABASE_URL`, `OPENAI_API_KEY`, `MCP_CLI_TOKEN`, `MCP_HOST`, plus AWS secrets if using S3.
- The workflow in `.github/workflows/deploy_mcp.yml` builds and pushes the image and contains a placeholder MCP deploy command.
- Replace the placeholder with your actual MCP CLI command, for example:

```bash
mcpctl login --host $MCP_HOST --token $MCP_CLI_TOKEN
mcpctl deploy --image $IMAGE --name donations-agent --env DATABASE_URL=$DATABASE_URL --env OPENAI_API_KEY=$OPENAI_API_KEY
```

## How the conversational agent works

- `/query`: accepts a plain-English user prompt.
- Generates SQL using OpenAI with the current database schema.
- Validates the SQL to allow only safe `SELECT` statements.
- Executes the query and returns results as JSON.
- Saves query results to CSV in `OUTDIR` and uploads to S3 if configured.
- `/run-task`: runs a named task from `agent_tasks.yaml`.
- `/tasks`: lists available named tasks.

## Notes

- If your dataset does not have a `state` column, create a `zip_state` lookup table and update the SQL accordingly.
- For persistent results on MCP, use a mounted volume or S3 bucket rather than local disk.
- Avoid using the conversational endpoint without `OPENAI_API_KEY` configured.

