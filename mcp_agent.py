import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
import pandas as pd

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///donations.db")
OUTDIR = os.getenv("OUTDIR", "outputs")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_PREFIX", "")

os.makedirs(OUTDIR, exist_ok=True)
engine = create_engine(DATABASE_URL, future=True)

DEFAULT_TASK_FILE = "agent_tasks.yaml"


class AgentError(Exception):
    pass


def s3_client():
    try:
        import boto3
    except ImportError:
        raise AgentError("Missing boto3: install boto3 to enable S3 uploads")
    return boto3.client("s3")


def upload_to_s3(file_path: str, bucket: str, key: str):
    s3 = s3_client()
    try:
        s3.upload_file(file_path, bucket, key)
        return True
    except Exception as exc:
        raise AgentError(f"S3 upload failed: {exc}")


def get_output_path(filename: str):
    return os.path.join(OUTDIR, filename)


def write_dataframe(df: pd.DataFrame, filename: str):
    path = get_output_path(filename)
    df.to_csv(path, index=False)
    print(f"Wrote {path}")
    return path


def execute_query(query: str):
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


def list_tables():
    inspector = inspect(engine)
    return inspector.get_table_names()


def describe_table(table_name: str):
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    if not columns:
        raise AgentError(f"Table '{table_name}' not found")
    return columns


def load_csv_to_table(table_name: str, csv_path: str, if_exists: str = "append"):
    if not os.path.exists(csv_path):
        raise AgentError(f"CSV file not found: {csv_path}")
    df = pd.read_csv(csv_path)
    df.to_sql(table_name, engine, if_exists=if_exists, index=False)
    print(f"Loaded {len(df)} rows into {table_name} (if_exists={if_exists})")
    return len(df)


def parse_task_file(path: str):
    if not os.path.exists(path):
        raise AgentError(f"Task file not found: {path}")
    data = Path(path).read_text()
    if path.endswith(".json"):
        return json.loads(data)
    try:
        import yaml
    except ImportError:
        raise AgentError("Missing pyyaml: install pyyaml to load YAML task files")
    return yaml.safe_load(data)


def run_task(task: dict):
    action = task.get("action")
    if not action:
        raise AgentError("Task missing 'action' field")

    if action == "query":
        query = task.get("query")
        if not query:
            raise AgentError("Task action 'query' requires a 'query' field")
        df = execute_query(query)
        output = task.get("output", f"{task.get('name', 'query')}.csv")
        path = write_dataframe(df, output)
        if task.get("upload_s3", False):
            if not S3_BUCKET:
                print("S3_BUCKET not set; skipping S3 upload")
            else:
                key = f"{S3_PREFIX.rstrip('/')}/{output}" if S3_PREFIX else output
                upload_to_s3(path, S3_BUCKET, key)
        return {"path": path, "records": df.to_dict(orient="records")}

    if action == "load_csv":
        csv_path = task.get("path")
        table = task.get("table")
        if not csv_path or not table:
            raise AgentError("Task action 'load_csv' requires 'path' and 'table'")
        return load_csv_to_table(table, csv_path, task.get("if_exists", "append"))

    if action == "list_tables":
        tables = list_tables()
        print("Tables:")
        for t in tables:
            print(f" - {t}")
        return tables

    if action == "describe_table":
        table = task.get("table")
        if not table:
            raise AgentError("Task action 'describe_table' requires a 'table' field")
        columns = describe_table(table)
        print(f"Schema for {table}:")
        for col in columns:
            print(f" - {col['name']} ({col['type']})")
        return columns

    raise AgentError(f"Unsupported task action: {action}")


def run_tasks_file(task_file: str, task_name: str = None):
    data = parse_task_file(task_file)
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        raise AgentError("Task file must contain a top-level 'tasks' list")
    if task_name:
        tasks = [task for task in tasks if task.get("name") == task_name]
        if not tasks:
            raise AgentError(f"Task named '{task_name}' not found")
    results = []
    for task in tasks:
        print(f"Running task: {task.get('name', '<unnamed>')} ({task.get('action')})")
        results.append(run_task(task))
    return results


def main():
    parser = argparse.ArgumentParser(description="Flexible MCP agent for database tasks")
    subparsers = parser.add_subparsers(dest="command")

    parser_query = subparsers.add_parser("query", help="Run a SQL query")
    parser_query.add_argument("--query", required=True)
    parser_query.add_argument("--output", default="query_result.csv")
    parser_query.add_argument("--upload-s3", action="store_true")

    parser_task = subparsers.add_parser("run-task", help="Run a named task from a task file")
    parser_task.add_argument("--task-file", default=DEFAULT_TASK_FILE)
    parser_task.add_argument("--task-name")

    parser_tasks = subparsers.add_parser("run-tasks", help="Run all tasks from a file")
    parser_tasks.add_argument("--task-file", default=DEFAULT_TASK_FILE)

    parser_load = subparsers.add_parser("load-csv", help="Load a CSV into the database")
    parser_load.add_argument("--table", required=True)
    parser_load.add_argument("--path", required=True)
    parser_load.add_argument("--if-exists", choices=["fail", "replace", "append"], default="append")

    parser_tables = subparsers.add_parser("list-tables", help="List database tables")
    parser_describe = subparsers.add_parser("describe-table", help="Describe the schema of a table")
    parser_describe.add_argument("--table", required=True)

    args = parser.parse_args()

    try:
        if args.command == "query":
            df = execute_query(args.query)
            path = write_dataframe(df, args.output)
            if args.upload_s3:
                if not S3_BUCKET:
                    raise AgentError("S3_BUCKET is required for upload_s3")
                key = f"{S3_PREFIX.rstrip('/')}/{args.output}" if S3_PREFIX else args.output
                upload_to_s3(path, S3_BUCKET, key)

        elif args.command == "run-task":
            run_tasks_file(args.task_file, args.task_name)

        elif args.command == "run-tasks":
            run_tasks_file(args.task_file)

        elif args.command == "load-csv":
            load_csv_to_table(args.table, args.path, args.if_exists)

        elif args.command == "list-tables":
            list_tables()

        elif args.command == "describe-table":
            describe_table(args.table)

        else:
            parser.print_help()
            sys.exit(1)
    except AgentError as exc:
        print(f"ERROR: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()
