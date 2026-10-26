#!/usr/bin/env python3
"""Log in to Garmin on YOUR computer and store the session tokens in SSM.

Run once after the first deploy, and again if the sync alarm reports auth failures.
Your password is never stored anywhere: it goes only to Garmin's login service.
The token file is written to a temp dir, uploaded, then deleted.
"""

import argparse
import getpass
import os
import sys
import tempfile

import boto3
from garminconnect import Garmin


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parameter", default="/garmin-coach/garmin-tokens", help="SSM parameter name")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE"), help="AWS CLI profile")
    args = p.parse_args()

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    with tempfile.TemporaryDirectory() as tmp:
        client = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ").strip())
        client.login(tmp)
        print(f"Logged in to Garmin as {client.get_full_name()}")
        token_path = os.path.join(tmp, "garmin_tokens.json")
        if not os.path.exists(token_path):
            print(f"Expected token file not found in {tmp}: {os.listdir(tmp)}", file=sys.stderr)
            return 1
        with open(token_path) as f:
            tokens = f.read()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    session.client("ssm").put_parameter(
        Name=args.parameter, Value=tokens, Type="SecureString", Overwrite=True, Tier="Intelligent-Tiering"
    )
    print(f"Stored tokens in SSM {args.parameter} ({args.region}). Local copy deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
