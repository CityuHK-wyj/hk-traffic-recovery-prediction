"""Explicitly synthetic slot fixtures, plus the existing authentic source sample."""
from pathlib import Path

import pandas as pd

from traffic_recovery.data.coverage import deduplicate, make_bins, missing_run_seconds, profile_day, profile_period, process_partitions
from traffic_recovery.data.pilot import select_cohort
from traffic_recovery.data.pilot_ingest import compact_snapshot

START = pd.Timestamp("2026-01-01", tz="Asia/Hong_Kong")


def slots() -> pd.DataFrame:
    times = pd.date_range(START + pd.Timedelta(seconds=30), periods=10, freq="30s")
    return pd.DataFrame({"detector_id": "SYNTHETIC", "direction": "East", "lane_id": "Test",
        "timestamp": times, "available_at": times + pd.Timedelta(minutes=6), "valid": "Y",
        "speed_kmh": 50., "volume_count": 1., "conflict": False, "signature": "Y|50|1|10|1"})


def test_repeat_dedup_earliest_availability_and_conflict_quarantine() -> None:
    original = slots()
    later = original.copy()
    later["available_at"] += pd.Timedelta(minutes=1)
    result = deduplicate(pd.concat([original, later]))
    assert len(result) == 10 and result.repeat_rows.sum() == 10
    assert result.available_at.min() == original.available_at.min()
    later.loc[0, "signature"] = "Y|20|1|10|1"
    result = deduplicate(pd.concat([original, later]))
    assert result.conflict.sum() == 1
    assert result.loc[result.conflict, "speed_kmh"].isna().all()
    assert result.loc[result.conflict, "volume_count"].isna().all()


def test_no_flow_excluded_but_missing_not_zero_and_minimum_two_slots() -> None:
    frame = slots()
    frame.loc[:8, "volume_count"] = 0
    binned = make_bins(deduplicate(frame))
    assert binned.iloc[0].valid_slots == 10
    assert binned.iloc[0].flow_slots == 1
    assert not binned.iloc[0].usable
    frame.loc[8, "volume_count"] = 1
    assert make_bins(deduplicate(frame)).iloc[0].usable
    frame["speed_kmh"] = float("nan")
    assert pd.isna(make_bins(deduplicate(frame)).iloc[0].speed_kmh)


def test_bins_right_closed_and_availability_waits_for_all_rows() -> None:
    frame = slots()
    result = make_bins(deduplicate(frame))
    assert len(result) == 1
    assert result.iloc[0].timestamp == START + pd.Timedelta(minutes=5)
    assert result.iloc[0].last_source_available_at == START + pd.Timedelta(minutes=11)
    assert result.iloc[0].available_at == START + pd.Timedelta(minutes=15)


def test_full_day_denominator_edges_offline_and_conflicts() -> None:
    frame = slots()
    frame.loc[0, "valid"] = "N"
    frame.loc[0, "speed_kmh"] = float("nan")
    frame.loc[1, "conflict"] = True
    frame.loc[1, "speed_kmh"] = float("nan")
    result = profile_day(deduplicate(frame), START).iloc[0]
    assert result.present_slots == 10 and result.valid_slots == 8
    assert result.offline_slots == 1 and result.conflict_slots == 1
    assert result.max_absent_gap_seconds == 86100
    assert missing_run_seconds(pd.Series([], dtype="datetime64[ns, UTC]"), START, START + pd.Timedelta(days=1)) == 86400


def test_cohort_selection_does_not_use_future_coverage() -> None:
    profile = pd.DataFrame({"detector_id": ["SYNTHETIC"] * 2, "direction": ["East"] * 2, "lane_id": ["Test"] * 2,
        "day": [START, START + pd.Timedelta(days=1)], "valid_coverage": [0.7, 0.1],
        "valid_5m_coverage": [0.98, 0.1], "usable_5m_coverage": [0.95, 0.1],
        "conflict_slots": [0, 100], "max_invalid_or_absent_gap_seconds": [60, 86400]})
    config = {"valid_5m_mean_min": 0.95, "valid_5m_daily_min": 0.90, "flow_5m_mean_min": 0.80, "max_units": 24}
    cohort, comparison = select_cohort(profile, START + pd.Timedelta(days=1), config)
    assert len(cohort) == 1
    assert comparison.loc[(comparison.resolution == "30s"), "lane_units"].sum() == 0
    profile.loc[1, "valid_5m_coverage"] = 1
    pd.testing.assert_frame_equal(cohort, select_cohort(profile, START + pd.Timedelta(days=1), config)[0])


def test_late_captures_cannot_enter_closed_features() -> None:
    frame = slots()
    frame["available_at"] = START + pd.Timedelta(minutes=16)
    assert make_bins(deduplicate(frame)).empty


def test_multi_day_outage_is_not_clipped_to_one_day() -> None:
    frame = slots()
    a = profile_day(deduplicate(frame), START)
    a["expected_slots"] = 2880
    b = a.copy()
    b["day"] = START + pd.Timedelta(days=2)
    for col in ["first_valid", "last_valid", "first_present", "last_present"]:
        b[col] += pd.Timedelta(days=2)
    result = profile_period(pd.concat([a, b]), START, START + pd.Timedelta(days=3))
    assert result.iloc[0].max_absent_gap_seconds == 172500


def test_incremental_partition_boundaries_and_full_inventory(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    first = slots()
    first["source_file"] = "SYNTHETIC"
    tail = slots().iloc[:2].copy()
    tail["timestamp"] += pd.Timedelta(hours=23, minutes=55)
    tail["available_at"] = tail.timestamp + pd.Timedelta(minutes=6)
    tail["source_file"] = "SYNTHETIC"
    correction = first.iloc[:1].copy()
    correction["signature"] = "SYNTHETIC_LATE_CORRECTION"
    correction["speed_kmh"] = 5
    correction["available_at"] = START + pd.Timedelta(minutes=16)  # after first bin closure
    pd.concat([first, tail, correction]).to_parquet(source / "20260101.parquet", index=False)
    second = tail.copy()  # identical key repeated across archive boundaries
    second["available_at"] += pd.Timedelta(minutes=1)
    second.to_parquet(source / "20260102.parquet", index=False)
    profile = process_partitions(source, output, START, START + pd.Timedelta(days=1))
    assert profile.present_slots.sum() == 12 and profile.repeat_rows.sum() == 3
    assert profile.conflict_slots.sum() == 1  # quality audit retains late evidence
    assert profile.expected_slots.sum() == 2880
    bins = pd.concat([b for p in output.glob("bins-*.parquet") if len(b := pd.read_parquet(p))])
    assert not bins.duplicated(["detector_id", "direction", "lane_id", "timestamp"]).any()
    first_bin = bins.loc[bins.timestamp == START + pd.Timedelta(minutes=5)].iloc[0]
    assert first_bin.usable and first_bin.valid_slots == 10 and first_bin.speed_kmh == 50
    assert first_bin.conflict_slots == 0  # no retrospective late-correction leakage


def test_authentic_snapshot_compact_adapter_provenance() -> None:
    path = Path("data/sample/verified/sample_20261019.xml")
    result = compact_snapshot(path.read_bytes(), "20261019-0000-rawSpeedVol-all.xml")
    assert len(result) > 0 and not result.signature.isna().any()
    assert (result.available_at >= result.timestamp).all()
    assert result.source_file.nunique() == 1
