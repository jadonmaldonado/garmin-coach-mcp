"""Turn raw Garmin Connect JSON into compact, stable records.

Garmin's payloads are undocumented and change, so every field is read defensively:
a missing field becomes None (dropped before storage) instead of crashing the sync.
"""

from common.util import fmt_duration, fmt_pace, g, is_num, rnd


def _min(seconds):
    return rnd(seconds / 60, 0) if is_num(seconds) else None


def sport_bucket(type_key: str | None) -> str:
    k = (type_key or "").lower()
    if "swim" in k:
        return "swim"
    if any(x in k for x in ("cycl", "bik", "ride", "spin")):
        return "bike"
    if "run" in k:
        return "run"
    if k in ("multi_sport", "triathlon", "duathlon", "swimrun"):
        return "multisport"
    if any(x in k for x in ("strength", "hiit", "pilates", "yoga")):
        return "strength"
    if "walk" in k or "hik" in k:
        return "walk_hike"
    return "other"


def extract_sleep(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    dto = raw.get("dailySleepDTO") or {}
    secs = dto.get("sleepTimeSeconds")
    return {
        "sleep_hours": rnd(secs / 3600, 2) if is_num(secs) and secs > 0 else None,
        "sleep_score": g(dto, "sleepScores", "overall", "value"),
        "sleep_quality": g(dto, "sleepScores", "overall", "qualifierKey"),
        "deep_min": _min(dto.get("deepSleepSeconds")),
        "light_min": _min(dto.get("lightSleepSeconds")),
        "rem_min": _min(dto.get("remSleepSeconds")),
        "awake_min": _min(dto.get("awakeSleepSeconds")),
        "avg_overnight_hrv": rnd(raw.get("avgOvernightHrv")),
        "sleep_resting_hr": raw.get("restingHeartRate"),
    }


def extract_hrv(raw) -> dict:
    s = g(raw, "hrvSummary") or {}
    return {
        "hrv_last_night": s.get("lastNightAvg"),
        "hrv_weekly_avg": s.get("weeklyAvg"),
        "hrv_status": s.get("status"),
        "hrv_baseline_low": g(s, "baseline", "balancedLow"),
        "hrv_baseline_high": g(s, "baseline", "balancedUpper"),
    }


def extract_readiness(raw) -> dict:
    entries = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    entries = [e for e in entries if isinstance(e, dict) and e.get("score") is not None]
    if not entries:
        return {}
    # Several readings per day are possible; the earliest is the morning (wake-up) score.
    e = sorted(entries, key=lambda x: str(x.get("timestamp") or x.get("timestampLocal") or ""))[0]
    return {
        "readiness_score": e.get("score"),
        "readiness_level": e.get("level"),
        "readiness_feedback": e.get("feedbackShort"),
        "recovery_time_min": e.get("recoveryTime"),
    }


def extract_stats(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {
        "resting_hr": raw.get("restingHeartRate"),
        "body_battery_high": raw.get("bodyBatteryHighestValue"),
        "body_battery_low": raw.get("bodyBatteryLowestValue"),
        "body_battery_at_wake": raw.get("bodyBatteryAtWakeTime"),
        "avg_stress": raw.get("averageStressLevel"),
        "steps": raw.get("totalSteps"),
    }


def _speed_fields(sport: str, speed) -> dict:
    if sport == "run":
        return {"pace_per_km": fmt_pace(speed)}
    if sport == "swim":
        return {"pace_per_100m": fmt_pace(speed, 100)}
    if sport == "bike":
        return {"avg_speed_kmh": rnd(speed * 3.6) if is_num(speed) else None}
    return {}


def extract_activity(a: dict) -> dict | None:
    act_id = a.get("activityId")
    start = a.get("startTimeLocal")
    if not act_id or not start:
        return None
    start_iso = str(start).replace(" ", "T")[:19]
    type_key = g(a, "activityType", "typeKey")
    sport = sport_bucket(type_key)
    duration = a.get("duration")
    distance = a.get("distance")
    rec = {
        "activity_id": str(act_id),
        "name": a.get("activityName"),
        "type": type_key,
        "sport": sport,
        "start_local": start_iso,
        "date": start_iso[:10],
        "duration_min": rnd(duration / 60) if is_num(duration) else None,
        "duration": fmt_duration(duration),
        "moving_min": rnd(a["movingDuration"] / 60) if is_num(a.get("movingDuration")) else None,
        "distance_km": rnd(distance / 1000, 2) if is_num(distance) and distance > 0 else None,
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "garmin_load": rnd(a.get("activityTrainingLoad")),
        "aerobic_te": rnd(a.get("aerobicTrainingEffect")),
        "anaerobic_te": rnd(a.get("anaerobicTrainingEffect")),
        "avg_power": rnd(a.get("avgPower"), 0),
        "norm_power": rnd(a.get("normPower"), 0),
        "elevation_gain_m": rnd(a.get("elevationGain"), 0),
        "calories": rnd(a.get("calories"), 0),
        "child_ids": [str(c) for c in a.get("childIds") or []] or None,
    }
    rec.update(_speed_fields(sport, a.get("averageSpeed")))
    return rec


def extract_fitness(vo2, races, status) -> dict:
    entry = vo2[0] if isinstance(vo2, list) and vo2 else vo2 if isinstance(vo2, dict) else {}
    race = races[0] if isinstance(races, list) and races else races if isinstance(races, dict) else {}
    devices = g(status, "mostRecentTrainingStatus", "latestTrainingStatusData") or {}
    ts = next(iter(devices.values()), {}) if isinstance(devices, dict) else {}
    balance_map = g(status, "mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap") or {}
    bal = next(iter(balance_map.values()), {}) if isinstance(balance_map, dict) else {}
    return {
        "vo2max_run": g(entry, "generic", "vo2MaxPreciseValue") or g(entry, "generic", "vo2MaxValue"),
        "vo2max_bike": g(entry, "cycling", "vo2MaxPreciseValue") or g(entry, "cycling", "vo2MaxValue"),
        "race_prediction_5k": fmt_duration(race.get("time5K")),
        "race_prediction_10k": fmt_duration(race.get("time10K")),
        "race_prediction_half": fmt_duration(race.get("timeHalfMarathon")),
        "race_prediction_marathon": fmt_duration(race.get("timeMarathon")),
        "training_status": ts.get("trainingStatusFeedbackPhrase") or ts.get("trainingStatus"),
        "garmin_acute_load": g(ts, "acuteTrainingLoadDTO", "dailyTrainingLoadAcute"),
        "garmin_chronic_load": g(ts, "acuteTrainingLoadDTO", "dailyTrainingLoadChronic"),
        "garmin_acwr": g(ts, "acuteTrainingLoadDTO", "dailyAcuteChronicWorkloadRatio"),
        "load_focus_aerobic_low": rnd(bal.get("monthlyLoadAerobicLow"), 0),
        "load_focus_aerobic_high": rnd(bal.get("monthlyLoadAerobicHigh"), 0),
        "load_focus_anaerobic": rnd(bal.get("monthlyLoadAnaerobic"), 0),
    }


def extract_activity_detail(summary, splits, zones) -> dict:
    s = g(summary, "summaryDTO") or {}
    type_key = g(summary, "activityTypeDTO", "typeKey")
    sport = sport_bucket(type_key)
    laps = []
    for i, lap in enumerate((g(splits, "lapDTOs") or [])[:60], start=1):
        dur, dist = lap.get("duration"), lap.get("distance")
        row = {
            "lap": i,
            "distance_km": rnd(dist / 1000, 2) if is_num(dist) else None,
            "duration": fmt_duration(dur),
            "avg_hr": rnd(lap.get("averageHR"), 0),
            "max_hr": rnd(lap.get("maxHR"), 0),
            "avg_power": rnd(lap.get("averagePower"), 0),
            "elevation_gain_m": rnd(lap.get("elevationGain"), 0),
        }
        row.update(_speed_fields(sport, lap.get("averageSpeed")))
        laps.append({k: v for k, v in row.items() if v is not None})
    zone_rows = [
        {"zone": z.get("zoneNumber"), "minutes": rnd(z.get("secsInZone", 0) / 60), "from_bpm": z.get("zoneLowBoundary")}
        for z in (zones if isinstance(zones, list) else [])
        if isinstance(z, dict)
    ]
    overview = {
        "activity_id": str(g(summary, "activityId") or ""),
        "name": g(summary, "activityName"),
        "type": type_key,
        "sport": sport,
        "start_local": g(s, "startTimeLocal"),
        "duration": fmt_duration(s.get("duration")),
        "distance_km": rnd(s["distance"] / 1000, 2) if is_num(s.get("distance")) else None,
        "avg_hr": rnd(s.get("averageHR"), 0),
        "max_hr": rnd(s.get("maxHR"), 0),
        "avg_power": rnd(s.get("averagePower"), 0),
        "norm_power": rnd(s.get("normalizedPower"), 0),
        "elevation_gain_m": rnd(s.get("elevationGain"), 0),
        "aerobic_te": rnd(s.get("trainingEffect")),
        "anaerobic_te": rnd(s.get("anaerobicTrainingEffect")),
        "garmin_load": rnd(s.get("activityTrainingLoad")),
        "avg_run_cadence": rnd(s.get("averageRunCadence"), 0),
        "avg_bike_cadence": rnd(s.get("averageBikeCadence"), 0),
    }
    overview.update(_speed_fields(sport, s.get("averageSpeed")))
    return {
        "overview": {k: v for k, v in overview.items() if v is not None},
        "laps": laps,
        "hr_zones": zone_rows,
    }
