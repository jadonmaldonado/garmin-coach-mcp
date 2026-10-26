"""Garmin gateway Lambda: the ONLY component that talks to Garmin.

Actions (event["action"]):
  sync             pull wellness + activities for a date window into DynamoDB
                   (EventBridge Scheduler calls this; MCP refresh_data calls it async)
  activity_detail  live laps + HR zones for one activity (MCP calls it synchronously)

Keeping Garmin access in one function means one IAM role can read the token,
and token refreshes never race between functions.
"""

import json
import logging
import os
import time
from datetime import timedelta

import transform
from common import store
from common.util import daterange, drop_none, emf_metric, now_iso, parse_date, today_local
from garmin_session import GarminSession, is_auth_error

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_SYNC_DAYS = 120  # ~5 Garmin calls/day keeps one invocation well under the 15 min limit
PAUSE = float(os.environ.get("GARMIN_CALL_PAUSE_SECONDS", "0.3"))


def lambda_handler(event, context):
    event = event or {}
    action = event.get("action", "sync")
    if action == "sync":
        return run_sync(int(event.get("days", 3)), event.get("end_date"))
    if action == "activity_detail":
        return run_activity_detail(str(event.get("activity_id", "")))
    raise ValueError(f"Unknown action: {action}")


def _call(errors: list, label: str, fn, *args):
    """Call Garmin; record non-auth failures and keep going. Auth failures abort the run."""
    try:
        return fn(*args)
    except Exception as exc:
        if is_auth_error(exc):
            raise
        errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:200]}")
        return None
    finally:
        time.sleep(PAUSE)


def run_sync(days: int, end_date=None) -> dict:
    days = max(1, min(days, MAX_SYNC_DAYS))
    end = parse_date(end_date, today_local())
    start = end - timedelta(days=days - 1)
    errors: list[str] = []
    started = time.time()

    with GarminSession() as client:
        day_rows = []
        for d in daterange(start, end):
            ds = d.isoformat()
            item = {"PK": "DAY", "SK": ds, "date": ds, "updated_at": now_iso()}
            item.update(transform.extract_sleep(_call(errors, f"sleep {ds}", client.get_sleep_data, ds)))
            item.update(transform.extract_hrv(_call(errors, f"hrv {ds}", client.get_hrv_data, ds)))
            readiness = _call(errors, f"readiness {ds}", client.get_morning_training_readiness, ds)
            if not readiness:
                readiness = _call(errors, f"readiness-fallback {ds}", client.get_training_readiness, ds)
            item.update(transform.extract_readiness(readiness))
            item.update(transform.extract_stats(_call(errors, f"stats {ds}", client.get_stats, ds)))
            day_rows.append(drop_none(item))
        store.put_items(day_rows)

        raw_acts = _call(errors, "activities", client.get_activities_by_date, start.isoformat(), end.isoformat())
        acts = [transform.extract_activity(a) for a in (raw_acts or []) if isinstance(a, dict)]
        store.put_items(
            [drop_none({"PK": "ACT", "SK": f"{a['start_local']}#{a['activity_id']}", **a}) for a in acts if a]
        )

        if end == today_local():  # fitness snapshot only reflects "now"
            snapshot = transform.extract_fitness(
                _call(errors, "vo2max", client.get_max_metrics, end.isoformat()),
                _call(errors, "race_predictions", client.get_race_predictions),
                _call(errors, "training_status", client.get_training_status, end.isoformat()),
            )
            store.put_item(drop_none({"PK": "META", "SK": "fitness", "updated_at": now_iso(), **snapshot}))

    summary = {
        "status": "ok" if not errors else "partial",
        "window": f"{start.isoformat()}..{end.isoformat()}",
        "days_synced": len(day_rows),
        "activities_synced": len([a for a in acts if a]),
        "error_count": len(errors),
        "errors": errors[:20],
        "duration_s": round(time.time() - started, 1),
        "finished_at": now_iso(),
    }
    if end == today_local():
        store.put_item({"PK": "META", "SK": "sync", **summary})
    emf_metric("SyncSuccess", 1)
    log.info(json.dumps({"event": "sync_complete", **{k: v for k, v in summary.items() if k != "errors"}}))
    return summary


def run_activity_detail(activity_id: str) -> dict:
    if not activity_id.isdigit():
        raise ValueError("activity_id must be numeric")
    errors: list[str] = []
    with GarminSession() as client:
        summary = _call(errors, "activity", client.get_activity, activity_id)
        if not summary:
            raise ValueError(f"Activity {activity_id} not found")
        splits = _call(errors, "splits", client.get_activity_splits, activity_id)
        zones = _call(errors, "hr_zones", client.get_activity_hr_in_timezones, activity_id)
    detail = transform.extract_activity_detail(summary, splits, zones)
    if errors:
        detail["warnings"] = errors
    return detail
