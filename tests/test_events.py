"""Explicitly SYNTHETIC trajectories; behavior tests, never research observations."""
import pandas as pd
import pytest

from traffic_recovery.data.events import EventRules, FEATURES, assign_splits, build_events, fit_reference

START = pd.Timestamp("2026-01-01", tz="Asia/Hong_Kong")


def trajectory(speeds: list[float | None], lag: int = 6) -> pd.DataFrame:
    times = pd.date_range(START, periods=len(speeds), freq="5min")
    return pd.DataFrame({"detector_id": "SYNTHETIC_TEST", "direction": "East", "lane_id": "Test lane",
        "timestamp": times, "available_at": times + pd.Timedelta(minutes=lag), "speed_kmh": speeds,
        "usable": [s is not None for s in speeds], "valid_slots": 4})


def construct(speeds: list[float | None], rules: EventRules = EventRules()) -> pd.DataFrame:
    series = trajectory(speeds)
    return build_events(series, 100, start=START, end=START + pd.Timedelta(minutes=len(speeds) * 5), rules=rules)


def test_event_persistence_across_midnight() -> None:
    series = trajectory([90] * 3 + [40] * 2 + [90] * 4)
    series["timestamp"] += pd.Timedelta(hours=23, minutes=40)
    series["available_at"] += pd.Timedelta(hours=23, minutes=40)
    events = build_events(series, 100, start=START + pd.Timedelta(hours=23, minutes=40),
                          end=START + pd.Timedelta(days=1, hours=1))
    assert len(events) == 1
    assert events.iloc[0].onset_time.day != events.iloc[0].recovery_time.day
    assert events.iloc[0].label_15m == 1


def test_onset_requires_prior_recovered_state_and_two_low_bins() -> None:
    assert construct([40] * 10).empty  # left-censored congestion is not an onset
    assert construct([90, 90, 90, 40, 90]).empty
    events = construct([90, 90, 90, 40, 40, 60])
    assert len(events) == 1
    assert events.iloc[0].onset_time == START + pd.Timedelta(minutes=15)
    assert events.iloc[0].prediction_time == START + pd.Timedelta(minutes=26)


def test_sustained_recovery_confirmation_not_backdated() -> None:
    events = construct([90, 90, 90, 40, 40, 85, 85, 85, 40, 40])
    event = events.iloc[0]
    assert event.recovery_time == START + pd.Timedelta(minutes=35)
    assert event.recovery_available_at == START + pd.Timedelta(minutes=41)
    assert [event[f"label_{h}m"] for h in [15, 30, 60]] == [1, 1, 1]
    # Recurrence before the horizon endpoint does not negate a within label.
    assert len(events) == 1  # embargo prevents overlapping prediction windows


def test_threshold_equality_is_inclusive() -> None:
    events = construct([80] * 3 + [50] * 2 + [80] * 3)
    assert len(events) == 1 and events.iloc[0].label_15m == 1


def test_recovery_exactly_at_deadline_is_positive() -> None:
    series = trajectory([90] * 3 + [40] * 2 + [90] * 3, lag=0)
    events = build_events(series, 100, start=START, end=START + pd.Timedelta(minutes=40))
    assert events.iloc[0].recovery_time - events.iloc[0].prediction_time == pd.Timedelta(minutes=15)
    assert events.iloc[0].label_15m == 1


def test_multiple_horizons_negative_then_positive() -> None:
    events = construct([90] * 3 + [40] * 7 + [90] * 3)
    assert [events.iloc[0][f"label_{h}m"] for h in [15, 30, 60]] == [0, 0, 1]


def test_unrecovered_observed_event_is_negative_not_censored() -> None:
    event = construct([90] * 3 + [40] * 20).iloc[0]
    assert event.termination_reason == "period_end"
    assert [event[f"label_{h}m"] for h in [15, 30, 60]] == [0, 0, 0]


def test_censoring_distinguishes_unknown_from_negative() -> None:
    event = construct([90] * 3 + [40] * 7 + [None]).iloc[0]
    assert event.label_15m == 0
    assert pd.isna(event.label_30m) and pd.isna(event.label_60m)
    assert event.reason_60m == "missing_or_invalid_bin"
    assert pd.isna(construct([90] * 3 + [40] * 3).iloc[0].label_15m)
    assert construct([90] * 3 + [40] * 2).empty  # confirmation arrives after prediction period


def test_missing_timestamp_breaks_consecutive_recovery() -> None:
    series = trajectory([90] * 3 + [40] * 2 + [90] * 5).drop(index=6)
    events = build_events(series, 100, start=START, end=START + pd.Timedelta(minutes=50))
    assert events.iloc[0].termination_reason == "missing_or_invalid_bin"
    assert pd.isna(events.iloc[0].label_15m)
    assert pd.isna(events.iloc[0].recovery_time)


def test_one_high_bin_is_not_sustained_recovery() -> None:
    event = construct([90] * 3 + [40] * 2 + [90, 40, 90, 40] + [40] * 15).iloc[0]
    assert event.label_60m == 0 and pd.isna(event.recovery_time)


def test_second_event_requires_reset_and_nonoverlapping_60m_window() -> None:
    events = construct([90] * 3 + [40] * 2 + [90] * 13 + [40] * 2 + [90] * 3)
    assert len(events) == 2
    assert events.prediction_time.diff().iloc[1] > pd.Timedelta(minutes=60)
    events = construct([90] * 3 + [40] * 2 + [90] * 3 + [40] * 20)
    assert len(events) == 1  # onset suppressed in cooldown cannot reappear later


def test_features_available_and_unaffected_by_future_perturbation() -> None:
    first = trajectory([90] * 3 + [40] * 2 + [90] * 20)
    second = first.copy()
    second.loc[second.timestamp > START + pd.Timedelta(minutes=20), "speed_kmh"] = 10
    a = build_events(first, 100, start=START, end=START + pd.Timedelta(hours=2)).iloc[0]
    b = build_events(second, 100, start=START, end=START + pd.Timedelta(hours=2)).iloc[0]
    assert a[FEATURES].equals(b[FEATURES])
    assert a.feature_max_available_at <= a.prediction_time
    assert not any(x in FEATURES for x in ["recovery_time", "followup_end", "label_15m"])


def test_reference_uses_only_observed_and_available_past() -> None:
    history = trajectory([50] * 20)
    end = START + pd.Timedelta(minutes=50)
    a = fit_reference(history, fit_start=START, fit_end=end, min_bins=2)
    history.loc[history.timestamp >= end, "speed_kmh"] = 10000
    # Timestamp before boundary, but not available until after it: also forbidden.
    history.loc[history.timestamp == end - pd.Timedelta(minutes=5), "speed_kmh"] = 10000
    b = fit_reference(history, fit_start=START, fit_end=end, min_bins=2)
    pd.testing.assert_frame_equal(a, b)
    assert a.iloc[0].baseline_kmh == 50


def test_outcome_may_arrive_after_deadline_but_uses_observed_confirmation() -> None:
    series = trajectory([90] * 3 + [40] * 3 + [90] * 3 + [90] * 3, lag=10)
    event = build_events(series, 100, start=START, end=START + pd.Timedelta(hours=1)).iloc[0]
    assert event.recovery_time == START + pd.Timedelta(minutes=40)
    assert event.recovery_available_at > event.prediction_time + pd.Timedelta(minutes=15)
    assert event.label_15m == 1


def test_censored_episode_rearming_enables_split_not_positive_label() -> None:
    events = construct([90] * 3 + [40] * 3 + [None] + [90] * 6)
    event = events.iloc[0]
    assert pd.isna(event.label_60m) and pd.notna(event.episode_separated_at)
    boundary = START + pd.Timedelta(hours=2)
    assert assign_splits(events, boundary, boundary + pd.Timedelta(days=1), boundary + pd.Timedelta(days=2)).iloc[0] == "train"


def test_excessive_availability_lag_cannot_hide_pre_prediction_recovery() -> None:
    series = trajectory([90] * 3 + [40] * 3, lag=15)
    with pytest.raises(ValueError, match="shorter than recovery persistence"):
        build_events(series, 100, start=START, end=START + pd.Timedelta(hours=1))


def test_split_purges_horizon_crossings_and_event_end() -> None:
    events = construct([90] * 3 + [40] * 2 + [90] * 3)
    boundary = events.iloc[0].prediction_time + pd.Timedelta(minutes=59)
    assert assign_splits(events, boundary, boundary + pd.Timedelta(days=1), boundary + pd.Timedelta(days=2)).iloc[0] == "purged"
    boundary = events.iloc[0].prediction_time + pd.Timedelta(minutes=61)
    assert assign_splits(events, boundary, boundary + pd.Timedelta(days=1), boundary + pd.Timedelta(days=2)).iloc[0] == "train"


@pytest.mark.parametrize("kwargs", [{"congestion": 0.8, "recovery": 0.5}, {"onset_bins": 0}, {"recovery_bins": 0}])
def test_invalid_rules_raise(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        EventRules(**kwargs)


def test_duplicate_and_naive_timestamps_raise() -> None:
    series = trajectory([90] * 10)
    with pytest.raises(ValueError):
        build_events(pd.concat([series, series.iloc[:1]]), 100, start=START, end=START + pd.Timedelta(hours=1))
    series["available_at"] = series.available_at.dt.tz_localize(None)
    with pytest.raises(ValueError):
        build_events(series, 100, start=START, end=START + pd.Timedelta(hours=1))
