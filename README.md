Donation agent: runs SQL queries and exports top zip/state reports, with optional S3 upload.

Quick local run:

1. Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r donation-agent/requirements.txt
```

2. Set environment variables:
```bash
export DATABASE_URL=sqlite:///donations.db
export OUTDIR=outputs
export S3_BUCKET=my-bucket          # optional
export S3_PREFIX=reports/donations  # optional
```

3. Run the agent:
```bash
python donation-agent/run_queries.py
```

GitHub Actions + MCP deployment

- Add the following repository secrets in GitHub:
  - `REGISTRY`
  - `REGISTRY_USERNAME`
  - `REGISTRY_PASSWORD`
  - `DATABASE_URL`
  - `MCP_CLI_TOKEN`
  - `MCP_HOST`
  - `AWS_ACCESS_KEY_ID` (if using S3 uploads)
  - `AWS_SECRET_ACCESS_KEY` (if using S3 uploads)

- The workflow builds and pushes a Docker image and contains a placeholder deploy step. Replace the placeholder with your MCP CLI deployment commands.

Dockerfile

- The provided `Dockerfile` installs dependencies and runs `run_queries.py`.
- Use your registry and deployment pipeline to run the container on your MCP server.

Notes

- If your dataset lacks a `state` column, create and load a `zip_state` mapping table and update queries accordingly.
- For persistent outputs, upload generated CSVs to S3 or use a mounted volume inside the MCP environment.

