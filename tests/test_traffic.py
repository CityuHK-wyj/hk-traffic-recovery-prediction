"""Offline public-boundary tests; TEST* identifiers are synthetic, never research data."""
from pathlib import Path

import pandas as pd
import pytest

from traffic_recovery.data.traffic import SchemaError, clean_traffic, parse_traffic

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_lane_and_normalize_hong_kong_midnight() -> None:
    frame = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes())
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row.detector_id == "TEST001"
    assert row.speed_raw == "40"
    assert row.timestamp.isoformat() == "2026-01-02T00:00:00+08:00"
    assert row.period_start.isoformat() == "2026-01-01T23:59:30+08:00"
    assert str(frame.timestamp.dt.tz) == "Asia/Hong_Kong"


def test_cleaning_missing_invalid_and_offline_values_without_zero_imputation() -> None:
    base = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes())
    frame = pd.concat([base] * 6, ignore_index=True)
    frame["detector_id"] = [f"TEST{i}" for i in range(6)]
    frame["speed_raw"] = ["", "-1", "bad", "0", "40", "inf"]
    frame["occupancy_raw"] = ["101", "-2", "20", "0", "10", "1.5"]
    frame["volume_raw"] = ["4", "1.5", "", "0", "4", "nan"]
    frame.loc[4, "valid"] = "N"
    clean, quality = clean_traffic(frame)
    assert clean.speed_kmh.isna().tolist() == [True, True, True, False, True, True]
    assert clean.loc[3, "volume_count"] == 0
    assert clean.loc[3, "speed_kmh"] == 0
    assert clean.loc[4, "speed_raw"] == "40"  # originals survive masking
    assert quality["measurements"]["speed"]["missing_raw"] == 1
    assert quality["measurements"]["speed"]["invalid_numeric"] == 3
    assert quality["measurements"]["occupancy"]["invalid_numeric"] == 3
    assert quality["measurements"]["volume"]["invalid_numeric"] == 2
    assert quality["source_offline_rows"] == 1


def test_exact_duplicates_collapse_and_conflicting_keys_fail() -> None:
    frame = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes())
    duplicate = pd.concat([frame, frame], ignore_index=True)
    clean, report = clean_traffic(duplicate)
    assert len(clean) == 1
    assert report["exact_duplicate_rows"] == 1
    duplicate.loc[1, "speed_raw"] = "45"
    with pytest.raises(SchemaError, match="Conflicting duplicate"):
        clean_traffic(duplicate)
    quarantined, report = clean_traffic(duplicate, conflicts="quarantine")
    assert quarantined.empty  # neither conflicting measurement is chosen
    assert report["conflicting_rows_quarantined"] == 2
    assert report["conflicting_keys_quarantined"] == 1


@pytest.mark.parametrize("column", ["speed_raw", "detector_id", "period_start", "valid"])
def test_missing_columns_rejected(column: str) -> None:
    frame = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes()).drop(columns=column)
    with pytest.raises(SchemaError):
        clean_traffic(frame)


@pytest.mark.parametrize("payload", [b"not xml", b"<html/>", b"<raw_speed_volume_list><date>2026-01-01</date><periods/></raw_speed_volume_list>"])
def test_unexpected_or_empty_xml_rejected(payload: bytes) -> None:
    with pytest.raises(SchemaError):
        parse_traffic(payload)


def test_missing_tag_is_not_treated_as_a_missing_measurement() -> None:
    payload = (FIXTURES / "raw_synthetic.xml").read_bytes().replace(b"<volume>4</volume>", b"")
    with pytest.raises(SchemaError, match="volume"):
        parse_traffic(payload)


def test_naive_or_blank_keys_rejected() -> None:
    frame = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes())
    frame["timestamp"] = frame.timestamp.dt.tz_localize(None)
    with pytest.raises(SchemaError, match="timezone-aware"):
        clean_traffic(frame)
    frame = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes())
    frame.loc[0, "lane_id"] = " "
    with pytest.raises(SchemaError, match="key"):
        clean_traffic(frame)


def test_unknown_validity_masks_measurements() -> None:
    frame = parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes())
    frame.loc[0, "valid"] = "?"
    clean, report = clean_traffic(frame)
    assert pd.isna(clean.loc[0, "speed_kmh"])
    assert report["unknown_validity_rows"] == 1


def test_processed_segments_remain_separate_from_detector_observations() -> None:
    # SYNTHETIC test XML following the verified processed-feed shape.
    payload = b"""<segment_speed_list><date>2026-01-01</date><time>12:00:00</time>
    <irn_version>TEST_VERSION</irn_version><segments><segment><segment_id>TEST_SEG</segment_id>
    <speed>37.5</speed><valid>Y</valid></segment></segments></segment_speed_list>"""
    clean, report = clean_traffic(parse_traffic(payload))
    assert clean.loc[0, "speed_kmh"] == 37.5
    assert clean.loc[0, "timestamp"].isoformat() == "2026-01-01T12:00:00+08:00"
    assert "detector_id" not in clean
    assert report["output_rows"] == 1


def test_cross_platform_path_round_trip(tmp_path: Path) -> None:
    destination = tmp_path / "sample with spaces" / "交通" / "clean.csv"
    destination.parent.mkdir(parents=True)
    clean, _ = clean_traffic(parse_traffic((FIXTURES / "raw_synthetic.xml").read_bytes()))
    clean.to_csv(destination, index=False)
    restored = pd.read_csv(destination)
    assert restored.loc[0, "detector_id"] == "TEST001"
    assert restored.loc[0, "timestamp"] == "2026-01-02 00:00:00+08:00"
