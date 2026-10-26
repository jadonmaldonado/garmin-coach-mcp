from datetime import date, timedelta

from common.load import acwr_zone, activity_load, daily_loads, dedupe_multisport, pmc, trimp


def test_activity_load_prefers_garmin_value():
    load, src = activity_load({"garmin_load": 120.0, "duration_min": 60, "avg_hr": 150}, 50, 190)
    assert (load, src) == (120.0, "garmin")


def test_activity_load_falls_back_to_trimp_then_duration():
    _, src = activity_load({"duration_min": 60, "avg_hr": 140, "sport": "run"}, 50, 190)
    assert src == "trimp"
    load, src = activity_load({"duration_min": 60, "sport": "swim"})
    assert src == "duration_estimate" and load == 54.0


def test_trimp_rejects_bad_inputs():
    assert trimp(60, 140, 60, 55) is None
    assert trimp(None, 140, 60, 190) is None


def test_pmc_converges_to_constant_load():
    start = date(2026, 1, 1)
    end = start + timedelta(days=364)
    daily = {(start + timedelta(days=i)).isoformat(): 100.0 for i in range(365)}
    last = pmc(daily, start, end)[-1]
    assert 99 < last["ctl"] <= 100
    assert 99.9 < last["atl"] <= 100
    assert abs(last["form"]) < 1


def test_rest_week_makes_form_positive():
    start = date(2026, 1, 1)
    daily = {(start + timedelta(days=i)).isoformat(): 100.0 for i in range(84)}
    series = pmc(daily, start, start + timedelta(days=90))
    assert series[83]["form"] < series[90]["form"]
    assert series[90]["form"] > 0


def test_multisport_parent_not_double_counted():
    acts = [
        {"activity_id": "1", "date": "2026-10-01", "garmin_load": 300, "child_ids": ["2", "3"], "sport": "multisport"},
        {"activity_id": "2", "date": "2026-10-01", "garmin_load": 100, "sport": "swim"},
        {"activity_id": "3", "date": "2026-10-01", "garmin_load": 200, "sport": "bike"},
    ]
    assert [a["activity_id"] for a in dedupe_multisport(acts)] == ["2", "3"]
    total, by_sport, _ = daily_loads(acts)
    assert total["2026-10-01"] == 300


def test_acwr_zones():
    assert acwr_zone(0.5).startswith("low")
    assert acwr_zone(1.0) == "optimal"
    assert acwr_zone(1.6).startswith("high")
