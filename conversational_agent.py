import os
import re
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, inspect, text
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///donations.db")
OUTDIR = os.getenv("OUTDIR", "outputs")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_PREFIX", "")

engine = create_engine(DATABASE_URL, future=True)
app = FastAPI(title="Donation DB Conversational Agent")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="UI not found")
    css = STATIC_DIR / "styles.css"
    js = STATIC_DIR / "app.js"
    css_v = int(css.stat().st_mtime) if css.is_file() else 0
    js_v = int(js.stat().st_mtime) if js.is_file() else 0
    html = index_file.read_text()
    html = html.replace("/static/styles.css", f"/static/styles.css?v={css_v}")
    html = html.replace("/static/app.js", f"/static/app.js?v={js_v}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

SQL_WHITELIST = re.compile(r"^\s*SELECT\s+.*", re.IGNORECASE | re.DOTALL)
FORBIDDEN_SQL_TOKENS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE")
FORBIDDEN_SQL_RE = re.compile(
    r"\b(" + "|".join(FORBIDDEN_SQL_TOKENS) + r")\b", re.IGNORECASE
)

_openai_client = None


def get_openai_client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not OPENAI_API_KEY and not OPENAI_BASE_URL:
        raise RuntimeError(
            "OPENAI_API_KEY is required (or set OPENAI_BASE_URL to an OpenAI-compatible server)"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Missing openai package: install openai>=1.0") from exc
    kwargs = {"api_key": OPENAI_API_KEY or "sk-not-needed"}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    _openai_client = OpenAI(**kwargs)
    return _openai_client


class QueryRequest(BaseModel):
    question: str
    explain_sql: Optional[bool] = False


class QueryResponse(BaseModel):
    sql: str
    records: List[dict]
    explanation: Optional[str] = None
    s3_url: Optional[str] = None


class TaskRequest(BaseModel):
    task_name: str
    task_file: Optional[str] = "agent_tasks.yaml"


def inspect_schema() -> str:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    parts = []
    for table in tables:
        columns = inspector.get_columns(table)
        column_definitions = ", ".join(f"{col['name']} {col['type']}" for col in columns)
        parts.append(f"{table}({column_definitions})")
    return "\n".join(parts)


def sanitize_sql(sql: str) -> str:
    stripped = sql.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()
    if not SQL_WHITELIST.match(stripped):
        raise ValueError("Generated SQL must be a single SELECT statement.")
    if ";" in stripped:
        raise ValueError("Multiple SQL statements are not allowed.")
    sql_without_strings = re.sub(r"'(?:''|[^'])*'", "", stripped)
    sql_without_strings = re.sub(r'"(?:""|[^"])*"', "", sql_without_strings)
    match = FORBIDDEN_SQL_RE.search(sql_without_strings)
    if match:
        raise ValueError(
            f"Generated SQL contains unsupported operation: {match.group(1).upper()}"
        )
    return stripped


def generate_sql(question: str) -> str:
    client = get_openai_client()
    schema = inspect_schema()
    prompt = (
        "You are a SQL generation assistant. Generate a single valid SQL SELECT statement only, "
        "with no explanation, that answers the user's request. Use only tables and columns available in the schema below. "
        "Do not include any DML or DDL statements. Do not output anything other than the SQL statement.\n\n"
        f"Schema:\n{schema}\n\n"
        f"User request: {question}\n\n"
        "Respond with SQL only."
    )
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are a SQL query generator for database analytics."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=400,
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()


def execute_query(sql: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


def upload_csv(path: str, filename: str) -> Optional[str]:
    if not S3_BUCKET:
        return None
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise RuntimeError("Missing boto3 package: install boto3 to upload to S3") from exc

    client = boto3.client("s3")
    key = f"{S3_PREFIX.rstrip('/')}/{filename}" if S3_PREFIX else filename
    try:
        client.upload_file(path, S3_BUCKET, key)
        return f"s3://{S3_BUCKET}/{key}"
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 upload failed: {exc}") from exc


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "conversational_agent"}


@app.post("/query", response_model=QueryResponse)
def query_endpoint(payload: QueryRequest):
    try:
        raw_sql = generate_sql(payload.question)
        sql = sanitize_sql(raw_sql)
        df = execute_query(sql)
        filename = f"conversational_{int(pd.Timestamp.now().timestamp())}.csv"
        os.makedirs(OUTDIR, exist_ok=True)
        path = os.path.join(OUTDIR, filename)
        df.to_csv(path, index=False)
        s3_url = upload_csv(path, filename) if S3_BUCKET else None
        explanation = f"Generated SQL: {sql}" if payload.explain_sql else None
        return QueryResponse(sql=sql, records=df.to_dict(orient="records"), explanation=explanation, s3_url=s3_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/run-task")
def run_task_endpoint(payload: TaskRequest):
    try:
        from mcp_agent import run_tasks_file
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to import task runner: {exc}")

    try:
        results = run_tasks_file(payload.task_file, payload.task_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rows = None
    output_path = None
    serializable_results = []
    for result in results:
        if isinstance(result, dict) and "records" in result:
            if rows is None:
                rows = result["records"]
            if "path" in result:
                output_path = result["path"]
            serializable_results.append(result.get("path", result))
        elif isinstance(result, list) and result and all(isinstance(x, str) for x in result):
            normalized = [{"table": name} for name in result]
            if rows is None:
                rows = normalized
            serializable_results.append(result)
        elif isinstance(result, list) and result and all(isinstance(x, dict) for x in result):
            normalized = [
                {k: (str(v) if k == "type" else v) for k, v in item.items()}
                for item in result
            ]
            if rows is None:
                rows = normalized
            serializable_results.append(normalized)
        else:
            serializable_results.append(result)

    return {"results": serializable_results, "records": rows, "output_path": output_path}


@app.get("/tasks")
def list_task_names():
    try:
        import yaml
        from pathlib import Path
    except ImportError as exc:
        raise HTTPException(status_code=400, detail="Missing pyyaml package") from exc

    task_file = os.getenv("TASK_FILE", "agent_tasks.yaml")
    if not os.path.exists(task_file):
        raise HTTPException(status_code=404, detail=f"Task file not found: {task_file}")

    try:
        data = yaml.safe_load(Path(task_file).read_text())
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        return {"tasks": [task.get("name") for task in tasks if "name" in task]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("conversational_agent:app", host="0.0.0.0", port=port, log_level="info")
