"""Offline regression checks on authentic, checksummed government samples.

These are real source evidence, unlike the TEST* fixtures. Expected counts come
from the recorded audit, not recomputation of a test's assertion formula.
"""
import json
from pathlib import Path

import pytest

from traffic_recovery.data.http import sha256_file
from traffic_recovery.data.traffic import SchemaError, clean_traffic, parse_traffic

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "sample" / "verified"


def test_curated_files_match_recorded_checksums() -> None:
    for item in json.loads((SAMPLES / "checksums.json").read_bytes()):
        assert sha256_file(SAMPLES / item["file"]) == item["sha256"]


def test_verified_raw_schema_and_real_conflicting_lane_records() -> None:
    parsed = parse_traffic((SAMPLES / "sample_20261021.xml").read_bytes())
    assert len(parsed) == 4200
    with pytest.raises(SchemaError, match="Conflicting duplicate"):
        clean_traffic(parsed)
    clean, report = clean_traffic(parsed, conflicts="quarantine")
    assert len(clean) == 4196
    assert report["conflicting_keys_quarantined"] == 2
    assert report["conflicting_rows_quarantined"] == 4
    assert clean.timestamp.max().isoformat() == "2026-10-20T23:54:00+08:00"


def test_verified_processed_schema_and_offline_masking() -> None:
    clean, report = clean_traffic(parse_traffic((SAMPLES / "segment_current.xml").read_bytes()))
    assert len(clean) == 4525
    assert report["source_offline_rows"] == 46
    assert clean.irn_version.unique().tolist() == ["20221210"]


def test_first_archived_raw_file_is_genuinely_empty() -> None:
    with pytest.raises(SchemaError, match="Empty traffic dataset"):
        parse_traffic((SAMPLES / "earliest_raw.xml").read_bytes())
