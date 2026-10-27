"""SYNTHETIC differential tests against the small in-memory reference."""
import json
from pathlib import Path

import pandas as pd
import pytest

from traffic_recovery.data.bounded_coverage import run_bounded
from traffic_recovery.data.coverage import process_partitions

START = pd.Timestamp("2026-01-01", tz="Asia/Hong_Kong")


def fixture(source: Path) -> None:
    source.mkdir()
    rows = []
    for detector in ["SYNTH_A", "SYNTH_B"]:
        for t in pd.date_range(START + pd.Timedelta(seconds=30), periods=10, freq="30s"):
            rows.append({"detector_id": detector, "direction": "East", "lane_id": "Lane",
                "timestamp": t, "available_at": t + pd.Timedelta(minutes=6), "valid": "Y",
                "speed_kmh": 50., "volume_count": 1., "conflict": False,
                "signature": "Y|50|1|10|1", "source_file": "SYNTHETIC"})
    first = pd.DataFrame(rows)
    tail = first.iloc[:2].copy()
    tail["timestamp"] += pd.Timedelta(hours=23, minutes=55)
    tail["available_at"] = tail.timestamp + pd.Timedelta(minutes=6)
    correction = first.iloc[:1].copy()
    correction["signature"] = "late-conflict"
    correction["speed_kmh"] = 5.
    correction["available_at"] = START + pd.Timedelta(minutes=16)
    pd.concat([first, tail, correction]).to_parquet(source / "20260101.parquet", index=False)
    later = tail.copy()
    later["available_at"] += pd.Timedelta(minutes=1)
    later.to_parquet(source / "20260102.parquet", index=False)


def test_matches_reference_with_cross_day_duplicate_and_late_correction(tmp_path: Path) -> None:
    source = tmp_path / "source"
    fixture(source)
    reference = process_partitions(source, tmp_path / "reference", START, START + pd.Timedelta(days=1))
    actual = run_bounded(source, tmp_path / "bounded", START, START + pd.Timedelta(days=1), group_size=1, batch_size=3)
    keys = ["detector_id", "direction", "lane_id", "day"]
    pd.testing.assert_frame_equal(reference.sort_values(keys).reset_index(drop=True).sort_index(axis=1),
        actual.sort_values(keys).reset_index(drop=True).sort_index(axis=1), check_dtype=False)
    expected_bins = pd.concat([pd.read_parquet(p) for p in (tmp_path / "reference").glob("bins-*.parquet") if pq_nonempty(p)])
    actual_bins = pd.read_parquet(tmp_path / "bounded" / "bins-20260101.parquet")
    keys = keys[:3] + ["timestamp"]
    pd.testing.assert_frame_equal(expected_bins.sort_values(keys).reset_index(drop=True).sort_index(axis=1),
        actual_bins.sort_values(keys).reset_index(drop=True).sort_index(axis=1), check_dtype=False, check_categorical=False)


def pq_nonempty(path: Path) -> bool:
    return len(pd.read_parquet(path)) > 0


def test_resume_and_corrupt_checkpoint_fail_closed(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    fixture(source)
    first = run_bounded(source, output, START, START + pd.Timedelta(days=1), group_size=1)
    checkpoint = output / "checkpoint-20260101.json"
    before = checkpoint.read_bytes()
    second = run_bounded(source, output, START, START + pd.Timedelta(days=1), group_size=1)
    pd.testing.assert_frame_equal(first, second, check_dtype=False)
    assert checkpoint.read_bytes() == before
    record = json.loads(before)
    record["outputs"]["bins-20260101.parquet"] = "invalid"
    checkpoint.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt checkpoint"):
        run_bounded(source, output, START, START + pd.Timedelta(days=1), group_size=1)


def test_interrupted_day_is_recomputed_atomically(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    fixture(source)
    expected = run_bounded(source, output, START, START + pd.Timedelta(days=1), group_size=1)
    expected_bins = pd.read_parquet(output / "bins-20260101.parquet")
    (output / "checkpoint-20260101.json").unlink()
    (output / "bins-20260101.partial").write_bytes(b"synthetic interrupted output")
    (output / "bins-20260101.parquet").write_bytes(b"synthetic incomplete publication")
    actual = run_bounded(source, output, START, START + pd.Timedelta(days=1), group_size=1)
    pd.testing.assert_frame_equal(expected, actual, check_dtype=False)
    pd.testing.assert_frame_equal(expected_bins, pd.read_parquet(output / "bins-20260101.parquet"))
    assert not (output / "bins-20260101.partial").exists()


def test_empty_detector_day_is_explicit_zero_coverage(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    fixture(source)
    second = pd.read_parquet(source / "20260102.parquet")
    second.to_parquet(source / "20260103.parquet", index=False)
    profile = run_bounded(source, output, START, START + pd.Timedelta(days=2), group_size=1)
    absent = profile.loc[profile.day == START + pd.Timedelta(days=1)]
    assert len(absent) == 2
    assert absent.valid_slots.sum() == 0 and absent.expected_slots.sum() == 5760
    assert absent.max_invalid_or_absent_gap_seconds.eq(86400).all()


def test_late_record_from_a_later_archive_is_not_dropped(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    fixture(source)
    late = pd.read_parquet(source / "20260101.parquet").iloc[:1].copy()
    late["signature"] = "very-late-conflict"
    late["available_at"] = START + pd.Timedelta(days=2)
    late.to_parquet(source / "20260103.parquet", index=False)
    profile = run_bounded(source, output, START, START + pd.Timedelta(days=1), group_size=1)
    assert profile.conflict_slots.sum() >= 1
    assert profile.repeat_rows.sum() == 4
