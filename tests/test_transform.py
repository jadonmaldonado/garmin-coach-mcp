from transform import extract_activity, extract_hrv, extract_readiness, extract_sleep, sport_bucket


def test_sport_buckets():
    assert sport_bucket("lap_swimming") == "swim"
    assert sport_bucket("open_water_swimming") == "swim"
    assert sport_bucket("virtual_ride") == "bike"
    assert sport_bucket("indoor_cycling") == "bike"
    assert sport_bucket("treadmill_running") == "run"
    assert sport_bucket("strength_training") == "strength"
    assert sport_bucket("multi_sport") == "multisport"
    assert sport_bucket(None) == "other"


def test_extract_activity_run():
    rec = extract_activity({
        "activityId": 123, "activityName": "Tempo", "startTimeLocal": "2026-10-18 06:30:00",
        "activityType": {"typeKey": "running"}, "duration": 3000, "distance": 10000,
        "averageSpeed": 3.3333, "averageHR": 158, "activityTrainingLoad": 142.4,
    })
    assert rec["activity_id"] == "123"
    assert rec["date"] == "2026-10-18"
    assert rec["sport"] == "run"
    assert rec["distance_km"] == 10.0
    assert rec["pace_per_km"] == "5:00"
    assert rec["garmin_load"] == 142.4


def test_extract_activity_skips_incomplete():
    assert extract_activity({"activityName": "no id"}) is None


def test_extractors_tolerate_missing_payloads():
    assert extract_sleep(None) == {}
    assert extract_hrv(None)["hrv_status"] is None
    assert extract_readiness([]) == {}


def test_readiness_picks_morning_entry():
    out = extract_readiness([
        {"score": 40, "timestamp": "2026-10-18T15:00:00"},
        {"score": 72, "timestamp": "2026-10-18T06:05:00", "level": "HIGH"},
    ])
    assert out["readiness_score"] == 72
