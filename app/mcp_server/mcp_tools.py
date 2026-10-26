"""MCP tool implementations. Everything reads DynamoDB except:
  get_activity_detail -> synchronous call to the gateway Lambda (live from Garmin)
  refresh_data        -> async call to the gateway Lambda
"""

import json
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from common import store
from common.load import acwr_zone, daily_loads, form_zone, pmc
from common.util import is_num, parse_date, today_local

MAX_RANGE_DAYS = 400
WARMUP_DAYS = 120  # history fed into CTL before the reporting window so it isn't artificially low
SPORTS = ["swim", "bike", "run", "strength", "multisport", "walk_hike", "other"]
HIDDEN = {"PK", "SK", "updated_at", "child_ids"}


# ---------- helpers ----------

def _window(start_date, end_date, default_days: int) -> tuple[date, date]:
    end = parse_date(end_date, today_local())
    start = parse_date(start_date, end - timedelta(days=default_days - 1))
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError(f"Range too large; max {MAX_RANGE_DAYS} days")
    return start, end


def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _avg(values, n: int = 1):
    nums = [float(v) for v in values if is_num(v)]
    return round(sum(nums) / len(nums), n) if nums else None


def _clean(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in HIDDEN}


def _hr_refs(days: list[dict], acts: list[dict]) -> tuple[float | None, float | None]:
    rests = [d["resting_hr"] for d in days if is_num(d.get("resting_hr"))]
    rest = statistics.median(rests) if rests else None
    env_max = float(os.environ.get("ATHLETE_MAX_HR", "0") or 0)
    observed = [a["max_hr"] for a in acts if is_num(a.get("max_hr"))]
    max_hr = env_max if env_max > 0 else (max(observed) if observed else None)
    return rest, max_hr


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def _invoke_gateway(payload: dict, wait: bool = True):
    import boto3
    from botocore.config import Config

    client = boto3.client("lambda", config=Config(read_timeout=25, retries={"max_attempts": 0}))
    resp = client.invoke(
        FunctionName=os.environ["GATEWAY_FUNCTION_NAME"],
        InvocationType="RequestResponse" if wait else "Event",
        Payload=json.dumps(payload).encode(),
    )
    if not wait:
        return None
    body = json.loads(resp["Payload"].read() or b"null")
    if resp.get("FunctionError"):
        msg = body.get("errorMessage") if isinstance(body, dict) else body
        raise RuntimeError(f"Garmin gateway error: {msg}")
    return body


# ---------- tools ----------

def get_daily_wellness(start_date=None, end_date=None):
    start, end = _window(start_date, end_date, 7)
    days = [_clean(d) for d in store.day_items(start, end)]
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "averages": {
            "sleep_hours": _avg([d.get("sleep_hours") for d in days], 2),
            "sleep_score": _avg([d.get("sleep_score") for d in days]),
            "hrv_last_night": _avg([d.get("hrv_last_night") for d in days]),
            "resting_hr": _avg([d.get("resting_hr") for d in days]),
            "readiness_score": _avg([d.get("readiness_score") for d in days]),
            "body_battery_at_wake": _avg([d.get("body_battery_at_wake") for d in days]),
        },
        "days_with_data": len(days),
        "days": days,
    }


def get_activities(start_date=None, end_date=None, sport=None, limit=50):
    start, end = _window(start_date, end_date, 14)
    acts = store.activity_items(start, end)
    if sport:
        acts = [a for a in acts if a.get("sport") == sport]
    totals: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "hours": 0.0, "km": 0.0})
    for a in acts:
        t = totals[a.get("sport", "other")]
        t["sessions"] += 1
        t["hours"] += (a.get("duration_min") or 0) / 60
        t["km"] += a.get("distance_km") or 0
    acts.sort(key=lambda a: a.get("start_local", ""), reverse=True)
    lim = _clamp(limit, 1, 200, 50)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "totals_by_sport": {k: {"sessions": v["sessions"], "hours": round(v["hours"], 1), "km": round(v["km"], 1)}
                            for k, v in totals.items()},
        "count": len(acts),
        "activities": [_clean(a) for a in acts[:lim]],
        "truncated": len(acts) > lim,
    }


def get_activity_detail(activity_id):
    activity_id = str(activity_id or "").strip()
    if not activity_id.isdigit():
        raise ValueError("activity_id must be the numeric Garmin activity id (see get_activities)")
    return _invoke_gateway({"action": "activity_detail", "activity_id": activity_id})


def get_training_load(end_date=None, days=42):
    end = parse_date(end_date, today_local())
    days = _clamp(days, 7, 365, 42)
    fetch_start = end - timedelta(days=days + WARMUP_DAYS - 1)
    acts = store.activity_items(fetch_start, end)
    day_rows = store.day_items(end - timedelta(days=60), end)
    rest, max_hr = _hr_refs(day_rows, acts)
    total, by_sport, sources = daily_loads(acts, rest, max_hr)
    series = pmc(total, fetch_start, end)
    window = series[-days:]
    cur = series[-1]
    week_ago = series[-8] if len(series) >= 8 else series[0]
    acwr = round(cur["atl"] / cur["ctl"], 2) if cur["ctl"] > 1 else None

    def sport_block(n):
        cutoff = (end - timedelta(days=n - 1)).isoformat()
        out = {}
        for s in SPORTS:
            load = sum(v for d, v in by_sport.get(s, {}).items() if d >= cutoff)
            hours = sum((a.get("duration_min") or 0) for a in acts if a.get("sport") == s and a["date"] >= cutoff) / 60
            if load or hours:
                out[s] = {"load": round(load, 1), "hours": round(hours, 1)}
        return out

    weekly: dict[str, dict] = {}
    for row in window:
        wk = _week_start(date.fromisoformat(row["date"])).isoformat()
        w = weekly.setdefault(wk, {"week_of": wk, "load": 0.0})
        w["load"] = round(w["load"] + row["load"], 1)
        w["ctl_end"], w["atl_end"], w["form_end"] = row["ctl"], row["atl"], row["form"]

    earliest = min((a["date"] for a in acts), default=None)
    history_days = (end - date.fromisoformat(earliest)).days + 1 if earliest else 0
    return {
        "as_of": end.isoformat(),
        "current": {
            "fitness_ctl": cur["ctl"],
            "fatigue_atl": cur["atl"],
            "form": cur["form"],
            "form_zone": form_zone(cur["form"]),
            "acwr": acwr,
            "acwr_zone": acwr_zone(acwr),
            "ctl_change_7d": round(cur["ctl"] - week_ago["ctl"], 1),
        },
        "by_sport_last_7_days": sport_block(7),
        "by_sport_last_28_days": sport_block(28),
        "weekly": list(weekly.values()),
        "last_14_days": series[-14:],
        "load_sources": dict(sources),
        "data_coverage": {
            "history_days": history_days,
            "note": None if history_days >= 42 else
            "Less than 6 weeks of history: CTL is still ramping up and reads low. Backfill more data.",
        },
        "method": "CTL=42d EWMA, ATL=7d EWMA of daily load; form=CTL-ATL. Load = Garmin activity load, "
                  "else HR-TRIMP, else duration estimate. Units are not TSS; use trends. Zones are guidelines.",
    }


def get_weekly_summary(weeks=8, end_date=None):
    end = parse_date(end_date, today_local())
    weeks = _clamp(weeks, 1, 52, 8)
    first_week = _week_start(end) - timedelta(weeks=weeks - 1)
    acts = store.activity_items(first_week, end)
    days = store.day_items(first_week, end)
    rest, max_hr = _hr_refs(days, acts)
    daily_loads(acts, rest, max_hr)  # annotates each activity with "load"
    out = []
    for i in range(weeks):
        ws = first_week + timedelta(weeks=i)
        we = ws + timedelta(days=6)
        in_week = lambda d: ws.isoformat() <= d <= we.isoformat()  # noqa: E731
        wa = [a for a in acts if in_week(a["date"])]
        wd = [d for d in days if in_week(d["date"])]
        sports = {}
        for s in SPORTS:
            sa = [a for a in wa if a.get("sport") == s]
            if sa:
                sports[s] = {
                    "sessions": len(sa),
                    "hours": round(sum(a.get("duration_min") or 0 for a in sa) / 60, 1),
                    "km": round(sum(a.get("distance_km") or 0 for a in sa), 1),
                }
        out.append({
            "week_of": ws.isoformat(),
            "partial_week": we > end,
            "total_hours": round(sum(a.get("duration_min") or 0 for a in wa) / 60, 1),
            "total_load": round(sum(a.get("load") or 0 for a in wa), 1),
            "by_sport": sports,
            "avg_sleep_hours": _avg([d.get("sleep_hours") for d in wd], 2),
            "avg_sleep_score": _avg([d.get("sleep_score") for d in wd]),
            "avg_hrv": _avg([d.get("hrv_last_night") for d in wd]),
            "avg_resting_hr": _avg([d.get("resting_hr") for d in wd]),
            "avg_readiness": _avg([d.get("readiness_score") for d in wd]),
        })
    return {"weeks": out}


def get_fitness_snapshot():
    item = store.get_item("META", "fitness")
    if not item:
        return {"message": "No fitness snapshot yet. Run refresh_data or wait for the next scheduled sync."}
    return _clean(item) | {"updated_at": item.get("updated_at")}


def get_sync_status():
    item = store.get_item("META", "sync")
    if not item:
        return {"message": "No sync has completed yet."}
    item = _clean(item)
    finished = item.get("finished_at")
    if finished:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(finished)
        item["hours_since_sync"] = round(age.total_seconds() / 3600, 1)
    return item


def refresh_data(days=3):
    days = _clamp(days, 1, 30, 3)
    _invoke_gateway({"action": "sync", "days": days}, wait=False)
    return {
        "status": "started",
        "message": f"Pulling the last {days} day(s) from Garmin in the background. "
                   "It usually finishes within a minute; check get_sync_status, then re-query.",
    }


def get_race_calendar():
    today = today_local()
    try:
        races = json.loads(os.environ.get("RACE_CALENDAR", "[]") or "[]")
    except json.JSONDecodeError:
        races = []
    rows = []
    for r in races:
        try:
            d = date.fromisoformat(r["date"])
        except (KeyError, TypeError, ValueError):
            continue
        delta = (d - today).days
        rows.append({**r, "days_to_go": delta, "weeks_to_go": round(delta / 7, 1), "past": delta < 0})
    rows.sort(key=lambda r: r["date"])
    return {"today": today.isoformat(), "athlete_goals": os.environ.get("ATHLETE_GOALS", ""), "races": rows}


# ---------- registry ----------

_DATE = {"type": "string", "description": "YYYY-MM-DD", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_RO = {"readOnlyHint": True, "openWorldHint": False}

TOOLS = {
    "get_daily_wellness": {
        "fn": get_daily_wellness,
        "description": "Daily recovery metrics per day: sleep (hours, score, stages), overnight HRV and "
                       "HRV status/baseline, resting HR, training readiness, body battery, stress. "
                       "Defaults to the last 7 days.",
        "inputSchema": {"type": "object", "properties": {"start_date": _DATE, "end_date": _DATE}},
        "annotations": _RO,
    },
    "get_activities": {
        "fn": get_activities,
        "description": "Workouts in a date range with duration, distance, pace/speed, HR, power, Garmin "
                       "training load and training effect, plus totals per sport. Defaults to last 14 days.",
        "inputSchema": {"type": "object", "properties": {
            "start_date": _DATE, "end_date": _DATE,
            "sport": {"type": "string", "enum": SPORTS},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        }},
        "annotations": _RO,
    },
    "get_activity_detail": {
        "fn": get_activity_detail,
        "description": "Live from Garmin: laps/splits and time in HR zones for one activity. "
                       "Use the activity_id from get_activities.",
        "inputSchema": {"type": "object", "required": ["activity_id"],
                        "properties": {"activity_id": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    "get_training_load": {
        "fn": get_training_load,
        "description": "Training load management: fitness (CTL), fatigue (ATL), form, acute:chronic ratio, "
                       "7- and 28-day load and hours per sport, weekly trend. Use for load and taper decisions.",
        "inputSchema": {"type": "object", "properties": {
            "end_date": _DATE, "days": {"type": "integer", "minimum": 7, "maximum": 365}}},
        "annotations": _RO,
    },
    "get_weekly_summary": {
        "fn": get_weekly_summary,
        "description": "Week-by-week (Mon-Sun) hours, km and sessions per sport, total load, and average "
                       "sleep, HRV, resting HR and readiness. Good for reviewing plan adherence.",
        "inputSchema": {"type": "object", "properties": {
            "weeks": {"type": "integer", "minimum": 1, "maximum": 52}, "end_date": _DATE}},
        "annotations": _RO,
    },
    "get_fitness_snapshot": {
        "fn": get_fitness_snapshot,
        "description": "Latest VO2 max (run/bike), Garmin race predictions (5K to marathon), training "
                       "status and load focus.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _RO,
    },
    "get_race_calendar": {
        "fn": get_race_calendar,
        "description": "Athlete goals and target races with days/weeks remaining. Use when planning blocks.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _RO,
    },
    "get_sync_status": {
        "fn": get_sync_status,
        "description": "When data was last synced from Garmin and whether it had errors.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _RO,
    },
    "refresh_data": {
        "fn": refresh_data,
        "description": "Start a background sync from Garmin for the last N days (use after a new workout).",
        "inputSchema": {"type": "object", "properties": {
            "days": {"type": "integer", "minimum": 1, "maximum": 30}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": True},
    },
}
