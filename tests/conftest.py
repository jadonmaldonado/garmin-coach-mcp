import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("app", "app/gateway", "app/mcp_server"):
    sys.path.insert(0, os.path.join(ROOT, sub))

os.environ.setdefault("ATHLETE_TIMEZONE", "America/Los_Angeles")
os.environ.setdefault("TABLE_NAME", "test-table")
