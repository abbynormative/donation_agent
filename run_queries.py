import os
from sqlalchemy import create_engine, text
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///donations.db")
OUTDIR = os.getenv("OUTDIR", "outputs")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_PREFIX", "")

os.makedirs(OUTDIR, exist_ok=True)
engine = create_engine(DATABASE_URL, future=True)

QUERIES = {
    "top_zips": """
    SELECT zip, COUNT(*) AS donation_count, SUM(amount) AS total_amount
    FROM donations
    GROUP BY zip
    ORDER BY donation_count DESC
    LIMIT 100;
    """,
    "top_states": """
    SELECT state, COUNT(*) AS donation_count, SUM(amount) AS total_amount
    FROM donations
    GROUP BY state
    ORDER BY donation_count DESC
    LIMIT 100;
    """,
    "zip_pct": """
    SELECT zip, donation_count,
      ROUND(100.0 * donation_count / SUM(donation_count) OVER (), 2) AS pct_of_total
    FROM (SELECT zip, COUNT(*) AS donation_count FROM donations GROUP BY zip) s
    ORDER BY donation_count DESC
    LIMIT 20;
    """,
}

def upload_to_s3(file_path: str, bucket: str, key: str):
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except Exception:
        print("boto3 not available; install boto3 to enable S3 uploads")
        return False

    s3 = boto3.client("s3")
    try:
        s3.upload_file(file_path, bucket, key)
        return True
    except (BotoCoreError, ClientError) as e:
        print("S3 upload failed:", e)
        return False


def main():
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uploaded = []
    with engine.connect() as conn:
        for name, q in QUERIES.items():
            df = pd.read_sql(text(q), conn)
            filename = f"{ts}_{name}.csv"
            path = os.path.join(OUTDIR, filename)
            df.to_csv(path, index=False)
            print("Wrote", path)

            if S3_BUCKET:
                s3_key = f"{S3_PREFIX.rstrip('/')}/{filename}" if S3_PREFIX else filename
                ok = upload_to_s3(path, S3_BUCKET, s3_key)
                if ok:
                    s3_url = f"s3://{S3_BUCKET}/{s3_key}"
                    print("Uploaded to", s3_url)
                    uploaded.append(s3_url)

    if uploaded:
        print("All uploads:")
        for u in uploaded:
            print(" -", u)


if __name__ == "__main__":
    main()
