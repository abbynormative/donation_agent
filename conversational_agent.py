import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
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

CHART_INTENT_RE = re.compile(
    r"\b(chart|graph|plot|trend|over\s*time|visuali[sz]e|bar|line|pie|donut|doughnut)\b",
    re.IGNORECASE,
)
SKILLS_DIR = Path(__file__).parent / "skills"
CHART_SKILL_FILE = SKILLS_DIR / "chart-maker.md"


def has_chart_intent(question: str) -> bool:
    return bool(question and CHART_INTENT_RE.search(question))


def load_skill(name: str) -> str:
    path = SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return ""
    return path.read_text()


def parse_agent_response(raw: str) -> Dict[str, Any]:
    """Extract {sql, chart?} from a model response.

    Accepts a bare SQL statement OR a JSON object (optionally fenced in ```json).
    """
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json|sql)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict) and isinstance(obj.get("sql"), str):
                chart = obj.get("chart") if isinstance(obj.get("chart"), dict) else None
                return {"sql": obj["sql"], "chart": chart}
        except json.JSONDecodeError:
            pass
    return {"sql": text, "chart": None}

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
    chart: Optional[Dict[str, Any]] = None
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


def generate_sql(question: str) -> Dict[str, Any]:
    """Return {sql, chart?} from the LLM. Always loads the sql-author skill; loads chart-maker when chart intent is present."""
    client = get_openai_client()
    schema = inspect_schema()
    wants_chart = has_chart_intent(question)
    sql_skill = load_skill("sql-author")

    sql_skill_block = (
        "----- BEGIN SKILL: sql-author -----\n"
        f"{sql_skill}\n"
        "----- END SKILL: sql-author -----\n"
    )

    if wants_chart:
        chart_skill = load_skill("chart-maker")
        prompt = (
            "Two skills apply to this request. Read both, then respond.\n\n"
            f"{sql_skill_block}\n"
            "----- BEGIN SKILL: chart-maker -----\n"
            f"{chart_skill}\n"
            "----- END SKILL: chart-maker -----\n\n"
            "Combine them: author the SQL per sql-author (with the self-check), and wrap it in the "
            "JSON envelope per chart-maker. Respond with a single JSON object only — no prose, no code fences.\n\n"
            f"Schema:\n{schema}\n\n"
            f"User request: {question}\n\n"
            "Respond with the JSON object only."
        )
        system = "You are a SQL + chart-spec generator. Apply the sql-author and chart-maker skills, and emit a JSON object matching the chart-maker schema."
    else:
        prompt = (
            "Apply this skill to the user's request, then respond.\n\n"
            f"{sql_skill_block}\n\n"
            f"Schema:\n{schema}\n\n"
            f"User request: {question}\n\n"
            "Respond with SQL only."
        )
        system = "You are a SQL query generator for database analytics. Apply the sql-author skill."

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1000 if wants_chart else 600,
        temperature=0.0,
    )
    return parse_agent_response(response.choices[0].message.content)


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


def validate_chart_spec(chart: Optional[Dict[str, Any]], columns: List[str]) -> Optional[Dict[str, Any]]:
    """Drop the chart spec if it references columns the SQL didn't produce."""
    if not chart:
        return None
    chart_type = chart.get("type")
    if chart_type not in ("bar", "line", "pie"):
        return None
    x = chart.get("x")
    y = chart.get("y")
    if isinstance(y, str):
        y = [y]
    if not isinstance(y, list):
        return None
    if x not in columns or not all(col in columns for col in y):
        return None
    return {
        "type": chart_type,
        "x": x,
        "y": y,
        "title": chart.get("title") or "",
    }


@app.post("/query", response_model=QueryResponse)
def query_endpoint(payload: QueryRequest):
    try:
        parsed = generate_sql(payload.question)
        sql = sanitize_sql(parsed["sql"])
        df = execute_query(sql)
        filename = f"conversational_{int(pd.Timestamp.now().timestamp())}.csv"
        os.makedirs(OUTDIR, exist_ok=True)
        path = os.path.join(OUTDIR, filename)
        df.to_csv(path, index=False)
        s3_url = upload_csv(path, filename) if S3_BUCKET else None
        explanation = f"Generated SQL: {sql}" if payload.explain_sql else None
        chart = validate_chart_spec(parsed.get("chart"), list(df.columns))
        return QueryResponse(
            sql=sql,
            records=df.to_dict(orient="records"),
            chart=chart,
            explanation=explanation,
            s3_url=s3_url,
        )
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


@app.get("/cluster-analysis")
def cluster_analysis_endpoint(n_clusters: int = 4):
    try:
        from donor_clustering import run_cluster_analysis
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to import cluster analysis: {exc}")

    try:
        return run_cluster_analysis(engine, n_clusters=n_clusters)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/cluster-analysis/download")
def download_segment_endpoint(segment: str, n_clusters: int = 4):
    try:
        from donor_clustering import get_segment_csv
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to import cluster analysis: {exc}")

    try:
        result = get_segment_csv(engine, n_clusters=n_clusters, segment=segment)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return Response(
        content=result["csv"],
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"'},
    )


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
