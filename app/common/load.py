"""Training load model: per-activity load + Performance Management Chart (CTL/ATL/form).

Load source priority per activity:
  1. Garmin's own activity training load (EPOC-based) when the watch reports it
  2. Banister TRIMP from average HR (needs resting + max HR)
  3. Duration x sport factor as a last resort (e.g. swims without HR)
Units are Garmin-load-ish, NOT TrainingPeaks TSS: compare trends, not absolute numbers.
"""

import math
from collections import Counter, defaultdict
from datetime import date

from common.util import daterange, is_num

CTL_DAYS = 42  # chronic load ("fitness")
ATL_DAYS = 7  # acute load ("fatigue")
SPORT_FACTORS = {"run": 1.0, "swim": 0.9, "bike": 0.8, "strength": 0.6, "multisport": 1.0}


def trimp(duration_min, avg_hr, rest_hr, max_hr) -> float | None:
    if not all(is_num(v) and v > 0 for v in (duration_min, avg_hr, rest_hr, max_hr)):
        return None
    if max_hr <= rest_hr:
        return None
    hrr = min(max((avg_hr - rest_hr) / (max_hr - rest_hr), 0.0), 1.0)
    return float(duration_min) * hrr * 0.64 * math.exp(1.92 * hrr)


def activity_load(act: dict, rest_hr=None, max_hr=None) -> tuple[float, str]:
    garmin = act.get("garmin_load")
    if is_num(garmin) and garmin > 0:
        return float(garmin), "garmin"
    t = trimp(act.get("duration_min"), act.get("avg_hr"), rest_hr, max_hr)
    if t:
        return t, "trimp"
    duration = act.get("duration_min") if is_num(act.get("duration_min")) else 0
    return float(duration) * SPORT_FACTORS.get(act.get("sport"), 0.5), "duration_estimate"


def dedupe_multisport(acts: list[dict]) -> list[dict]:
    """Drop a multisport parent when its child legs are also present, to avoid double counting."""
    ids = {str(a.get("activity_id")) for a in acts}
    return [a for a in acts if not (a.get("child_ids") and any(str(c) in ids for c in a["child_ids"]))]


def daily_loads(acts: list[dict], rest_hr=None, max_hr=None):
    """Annotates each activity with load/load_source; returns per-day totals."""
    total: dict[str, float] = defaultdict(float)
    by_sport: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sources: Counter = Counter()
    for a in dedupe_multisport(acts):
        load, src = activity_load(a, rest_hr, max_hr)
        a["load"] = round(load, 1)
        a["load_source"] = src
        total[a["date"]] += load
        by_sport[a.get("sport", "other")][a["date"]] += load
        sources[src] += 1
    return total, by_sport, sources


def pmc(daily: dict[str, float], start: date, end: date) -> list[dict]:
    """Exponentially weighted CTL/ATL. form = CTL - ATL at end of day (positive = fresh)."""
    ctl = atl = 0.0
    out = []
    for d in daterange(start, end):
        load = daily.get(d.isoformat(), 0.0)
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
        out.append({
            "date": d.isoformat(), "load": round(load, 1),
            "ctl": round(ctl, 1), "atl": round(atl, 1), "form": round(ctl - atl, 1),
        })
    return out


def acwr_zone(acwr: float | None) -> str | None:
    if acwr is None:
        return None
    if acwr < 0.8:
        return "low (detraining risk)"
    if acwr <= 1.3:
        return "optimal"
    if acwr <= 1.5:
        return "caution"
    return "high (injury-risk zone)"


def form_zone(form: float | None) -> str | None:
    if form is None:
        return None
    if form > 15:
        return "very fresh (taper/race, or losing fitness)"
    if form > 5:
        return "fresh"
    if form >= -10:
        return "neutral"
    if form >= -30:
        return "productive training fatigue"
    return "high fatigue (consider recovery)"
