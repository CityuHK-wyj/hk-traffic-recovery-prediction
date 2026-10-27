"""Offline API integration using explicitly SYNTHETIC Parquet/metadata fixtures."""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from traffic_recovery.api.app import create_app


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def client(tmp_path: Path) -> tuple[TestClient, Path]:
    now = pd.Timestamp("2026-01-01 10:00", tz="Asia/Hong_Kong")
    events = pd.DataFrame([{"event_id": "SYNTHETIC", "detector_id": "TEST", "direction": "East", "lane_id": "L",
        "onset_time": now, "onset_confirmed_at": now + pd.Timedelta(minutes=5), "prediction_time": now + pd.Timedelta(minutes=15),
        "termination_reason": "missing_or_invalid_bin", "label_15m": None, "label_30m": None, "label_60m": None,
        "baseline_kmh": 80., "congestion_ratio": .5, "recovery_ratio": .8}])
    event_path = tmp_path / "medium_events.parquet"
    events.to_parquet(event_path, index=False)
    bins = pd.DataFrame([{"detector_id": "TEST", "direction": "East", "lane_id": "L", "timestamp": now,
        "available_at": now + pd.Timedelta(minutes=10), "speed_kmh": 30., "usable": True,
        "present_slots": 3, "valid_slots": 3, "flow_slots": 3, "offline_slots": 0, "conflict_slots": 0}])
    bin_path = tmp_path / "bins-20260101.parquet"
    bins.to_parquet(bin_path, index=False)
    metadata = tmp_path / "synthetic_detectors.csv"
    with metadata.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["AID_ID_Number", "Latitude", "Longitude", "Road_EN", "Direction"])
        writer.writeheader()
        writer.writerow({"AID_ID_Number": "TEST", "Latitude": 22.3, "Longitude": 114.2, "Road_EN": "SYNTHETIC ROAD", "Direction": "East"})
    checks = tmp_path / "checks.json"
    checks.write_text(json.dumps([{"file": metadata.name, "sha256": digest(metadata)}]), encoding="utf-8")
    report = tmp_path / "stats.json"
    report.write_text(json.dumps({"events_sha256": digest(event_path), "bin_sha256": {bin_path.name: digest(bin_path)},
        "reference_end": "2026-01-01T00:00:00+08:00", "event_end": "2026-01-02T00:00:00+08:00"}), encoding="utf-8")
    return TestClient(create_app(tmp_path, report, metadata, checks)), bin_path


def test_read_event_and_unknown_predictions(client: tuple[TestClient, Path]) -> None:
    http, _ = client
    response = http.get("/api/events")
    assert response.status_code == 200 and response.json()["total"] == 1
    result = http.get("/api/events/SYNTHETIC").json()
    assert result["event"]["label_15m"] is None
    assert result["predictions"] == {"status": "unavailable", "reason": "No genuine trained model integrated.", "values": None}
    assert result["detector"]["longitude"] == 114.2
    assert http.get("/api/events/not-found").status_code == 404


def test_curve_missing_is_null_and_timestamps_are_aware(client: tuple[TestClient, Path]) -> None:
    http, _ = client
    result = http.get("/api/events/SYNTHETIC/curve")
    assert result.status_code == 200
    points = result.json()["points"]
    assert len(points) > 1 and sum(p["speed_kmh"] is not None for p in points) == 1
    assert any(p["speed_kmh"] is None and p["usable"] is False for p in points)
    assert all("+08:00" in p["timestamp"] for p in points)


def test_corrupt_and_missing_evidence_returns_503(client: tuple[TestClient, Path]) -> None:
    http, path = client
    path.write_bytes(b"SYNTHETIC CORRUPTION")
    assert http.get("/api/health").status_code == 503
    path.unlink()
    assert http.get("/api/events").status_code == 503


def test_query_params_are_bounded(client: tuple[TestClient, Path]) -> None:
    http, _ = client
    assert http.get("/api/events?limit=500").status_code == 422
    assert http.get("/api/events?offset=-1").status_code == 422
