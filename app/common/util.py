"""Small shared helpers: dates, number cleanup, DynamoDB type conversion."""

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


def athlete_tz():
    """Athlete's local timezone, so 'today' matches the date on the watch."""
    name = os.environ.get("ATHLETE_TIMEZONE", "America/Los_Angeles")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # missing tzdata or bad name
        return timezone.utc


def today_local() -> date:
    return datetime.now(athlete_tz()).date()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_date(value, default: date) -> date:
    if value in (None, ""):
        return default
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def is_num(x) -> bool:
    if isinstance(x, bool) or not isinstance(x, (int, float, Decimal)):
        return False
    return not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def rnd(x, n: int = 1):
    return round(float(x), n) if is_num(x) else None


def g(obj, *path, default=None):
    """Safe nested get through dicts and list indexes."""
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and -len(cur) <= key < len(cur):
            cur = cur[key]
        else:
            return default
        if cur is None:
            return default
    return cur


def drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def to_dynamo(obj):
    """Floats -> Decimal (a DynamoDB requirement)."""
    return json.loads(json.dumps(obj, default=str), parse_float=Decimal)


def to_plain(obj):
    """Decimal -> int/float so results serialize cleanly to JSON."""
    if isinstance(obj, list):
        return [to_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def fmt_duration(seconds) -> str | None:
    if not is_num(seconds) or seconds <= 0:
        return None
    s = int(round(float(seconds)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace(speed_mps, per_meters: int = 1000) -> str | None:
    """Speed in m/s -> 'm:ss' per km (or per 100 m for swims)."""
    if not is_num(speed_mps) or speed_mps <= 0:
        return None
    return fmt_duration(per_meters / float(speed_mps))


def emf_metric(name: str, value: float, namespace: str = "GarminCoach") -> None:
    """Emit a CloudWatch custom metric via Embedded Metric Format (no PutMetricData call)."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "CloudWatchMetrics": [
                        {"Namespace": namespace, "Dimensions": [[]], "Metrics": [{"Name": name, "Unit": "Count"}]}
                    ],
                },
                name: value,
            }
        )
    )
