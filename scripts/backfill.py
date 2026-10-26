#!/usr/bin/env python3
"""Load history so training load (CTL) starts accurate. Runs the gateway in 90-day chunks."""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import boto3
from botocore.config import Config

CHUNK = 90


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--function", required=True, help="gateway Lambda name (terraform output)")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    lam = session.client("lambda", config=Config(read_timeout=910, retries={"max_attempts": 0}))

    end = date.today()
    remaining = args.days
    # Oldest chunk first, newest last, so the final run also refreshes the fitness snapshot.
    chunks = []
    while remaining > 0:
        days = min(CHUNK, remaining)
        chunks.append((end, days))
        end -= timedelta(days=days)
        remaining -= days
    for chunk_end, days in reversed(chunks):
        print(f"Syncing {days} days ending {chunk_end} ...", flush=True)
        resp = lam.invoke(
            FunctionName=args.function,
            Payload=json.dumps({"action": "sync", "days": days, "end_date": chunk_end.isoformat()}).encode(),
        )
        body = json.loads(resp["Payload"].read())
        if resp.get("FunctionError"):
            print(f"  failed: {body.get('errorMessage')}", file=sys.stderr)
            return 1
        print(f"  {body['days_synced']} days, {body['activities_synced']} activities, "
              f"{body['error_count']} non-fatal errors, {body['duration_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
