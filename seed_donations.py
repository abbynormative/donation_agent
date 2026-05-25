"""Generate an example donations table for local development.

Creates a `donations` table with the columns referenced by agent_tasks.yaml
and run_queries.py (zip, state, amount), plus a few useful extras
(id, donor_name, donated_at).

Usage:
    python seed_donations.py                  # 1000 rows, replaces table
    python seed_donations.py --rows 5000      # custom row count
    python seed_donations.py --if-exists fail # don't overwrite existing data
"""

import argparse
import os
import random
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///donations.db")

ZIP_STATE = [
    ("10001", "NY"), ("10002", "NY"), ("11201", "NY"),
    ("94103", "CA"), ("94110", "CA"), ("90001", "CA"), ("90210", "CA"),
    ("60601", "IL"), ("60614", "IL"),
    ("02108", "MA"), ("02139", "MA"),
    ("78701", "TX"), ("75201", "TX"), ("77002", "TX"),
    ("98101", "WA"), ("98109", "WA"),
    ("33101", "FL"), ("33139", "FL"),
    ("80202", "CO"),
    ("30303", "GA"),
]

FIRST_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Quinn", "Drew"]
LAST_NAMES = ["Smith", "Johnson", "Lee", "Patel", "Garcia", "Nguyen", "Chen", "Brown", "Davis", "Kim"]


def generate_rows(n: int, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    end = datetime(2026, 5, 25)
    start = end - timedelta(days=365)
    span_seconds = int((end - start).total_seconds())

    rows = []
    for i in range(1, n + 1):
        zip_code, state = rng.choice(ZIP_STATE)
        donor_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        amount = round(rng.lognormvariate(mu=3.5, sigma=1.0), 2)
        donated_at = start + timedelta(seconds=rng.randint(0, span_seconds))
        rows.append({
            "id": i,
            "donor_name": donor_name,
            "amount": amount,
            "zip": zip_code,
            "state": state,
            "donated_at": donated_at.isoformat(timespec="seconds"),
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Seed an example donations table")
    parser.add_argument("--rows", type=int, default=1000, help="Number of donation rows to generate")
    parser.add_argument(
        "--if-exists",
        choices=["fail", "replace", "append"],
        default="replace",
        help="Behavior when the donations table already exists",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL, future=True)
    df = generate_rows(args.rows, seed=args.seed)
    df.to_sql("donations", engine, if_exists=args.if_exists, index=False)
    print(f"Wrote {len(df)} rows to 'donations' in {DATABASE_URL} (if_exists={args.if_exists})")


if __name__ == "__main__":
    main()
