"""Local read-only API for authentic, provisional medium-pilot observations.

No model inference and no spatial adjacency claims. Input checksums are verified
against the saved research report; missing/corrupt evidence returns HTTP 503.
"""
from datetime import datetime, timedelta
import csv
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from traffic_recovery.data.http import sha256_file

LOGGER = logging.getLogger(__name__)
HK = ZoneInfo("Asia/Hong_Kong")
DEFAULT_DIR = Path("data/local/pilot/medium-40")
DEFAULT_REPORT = Path("reports/medium_pilot/statistics.json")
DEFAULT_METADATA = Path("data/sample/verified/detectors.csv")
DEFAULT_CHECKSUMS = Path("data/sample/verified/checksums.json")


def create_app(data_dir: Path | None = None, report: Path | None = None,
               metadata: Path | None = None, checksums: Path | None = None) -> FastAPI:
    """Create a localhost-oriented API using explicit paths, including synthetic tests.

    All input Parquet hashes and detector metadata hash must match supplied
    manifests. No source file is overwritten. Missing/mismatched evidence yields
    an actionable 503, and unknown event IDs yield 404. Timestamps use HKT.
    """
    root = Path(data_dir or os.environ.get("TRAFFIC_PILOT_DIR", DEFAULT_DIR))
    stats_file = Path(report or os.environ.get("TRAFFIC_PILOT_REPORT", DEFAULT_REPORT))
    metadata_file = Path(metadata or os.environ.get("TRAFFIC_DETECTORS", DEFAULT_METADATA))
    checksum_file = Path(checksums or os.environ.get("TRAFFIC_DETECTOR_CHECKSUMS", DEFAULT_CHECKSUMS))
    application = FastAPI(title="HK Traffic Recovery — local research pilot", version="0.1.0")
    application.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                               allow_methods=["GET"], allow_headers=["*"])

    def evidence() -> tuple[Path, list[Path], dict]:
        try:
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
            checksum_records = json.loads(checksum_file.read_text(encoding="utf-8"))
            expected_metadata = next(item["sha256"] for item in checksum_records if item["file"] == metadata_file.name)
            events = root / "medium_events.parquet"
            if sha256_file(events) != stats["events_sha256"] or sha256_file(metadata_file) != expected_metadata:
                raise ValueError("event or detector checksum mismatch")
            expected_bins = stats["bin_sha256"]
            if not expected_bins or any(Path(name).name != name for name in expected_bins):
                raise ValueError("invalid bin manifest")
            bins = [root / name for name in sorted(expected_bins)]
            if any(sha256_file(path) != expected_bins[path.name] for path in bins):
                raise ValueError("bin checksum mismatch")
            return events, bins, stats
        except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
            LOGGER.error("event_evidence_unavailable type=%s error=%s", type(exc).__name__, exc)
            raise HTTPException(status_code=503, detail="Verified medium-pilot evidence unavailable or checksum mismatch. See README reproduction instructions.") from exc

    def query(sql: str, parameters: list) -> list[dict]:
        try:
            with duckdb.connect(":memory:") as conn:
                conn.execute("SET TimeZone = 'Asia/Hong_Kong'")
                rows = conn.execute(sql, parameters)
                names = [item[0] for item in rows.description]
                return [dict(zip(names, row)) for row in rows.fetchall()]
        except duckdb.Error as exc:
            LOGGER.exception("event_query_failed")
            raise HTTPException(status_code=503, detail="Pilot dataset schema/query failure; inspect server logs.") from exc

    def event_row(identifier: str, event_file: Path) -> dict:
        rows = query("SELECT * FROM read_parquet(?) WHERE event_id = ?", [str(event_file), identifier])
        if not rows:
            raise HTTPException(status_code=404, detail="Event not found")
        if len(rows) != 1:
            raise HTTPException(status_code=503, detail="Event IDs are not unique")
        return rows[0]

    @application.get("/api/health")
    def health() -> dict:
        event_file, bins, _ = evidence()
        return {"status": "ok", "dataset": "medium-pilot-provisional", "event_sha256": sha256_file(event_file), "bin_partitions": len(bins)}

    @application.get("/api/events")
    def list_events(limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> dict:
        event_file, _, _ = evidence()
        items = query("SELECT event_id, detector_id, direction, lane_id, onset_time, prediction_time, termination_reason, label_15m, label_30m, label_60m FROM read_parquet(?) ORDER BY prediction_time, event_id LIMIT ? OFFSET ?", [str(event_file), limit, offset])
        total = query("SELECT count(*) AS n FROM read_parquet(?)", [str(event_file)])[0]["n"]
        return {"dataset": "medium-pilot-provisional", "total": total, "items": items,
                "notice": "Real observations; convenience cohort and provisional retrospective labels, not model predictions."}

    @application.get("/api/events/{event_id}")
    def event_details(event_id: str) -> dict:
        event_file, _, _ = evidence()
        event = event_row(event_id, event_file)
        try:
            with metadata_file.open(encoding="utf-8-sig", newline="") as stream:
                locations = [row for row in csv.DictReader(stream) if row["AID_ID_Number"] == event["detector_id"]]
            if len(locations) != 1:
                raise ValueError("detector ID absent or duplicated")
            location = locations[0]
            lat, lon = float(location["Latitude"]), float(location["Longitude"])
            if not (21 <= lat <= 24 and 112 <= lon <= 115):
                raise ValueError("detector coordinates outside expected regional bounds")
        except (OSError, KeyError, ValueError) as exc:
            LOGGER.error("detector_metadata_error event_id=%s error=%s", event_id, exc)
            raise HTTPException(status_code=503, detail="Detector location metadata invalid or missing") from exc
        return {"dataset": "medium-pilot-provisional", "event": event,
                "detector": {"id": event["detector_id"], "latitude": lat, "longitude": lon,
                             "road_description": location["Road_EN"], "metadata_direction": location["Direction"],
                             "coordinate_caveat": "Current metadata; historical location and latitude/longitude datum are not verified."},
                "predictions": {"status": "unavailable", "reason": "No genuine trained model integrated.", "values": None},
                "notice": "Recovery labels and times are retrospective outcomes, not features or predictions; thresholds provisional."}

    @application.get("/api/events/{event_id}/curve")
    def event_curve(event_id: str) -> dict:
        event_file, bins, stats = evidence()
        event = event_row(event_id, event_file)
        # Preserve a fixed 5m grid, including missing timestamps, without imputing speed.
        start = max(event["onset_time"] - timedelta(minutes=45), datetime.fromisoformat(stats["reference_end"]))
        end = min(event["prediction_time"] + timedelta(minutes=90), datetime.fromisoformat(stats["event_end"]) - timedelta(minutes=5))
        observations = query("SELECT timestamp, available_at, speed_kmh, usable, present_slots, valid_slots, flow_slots, offline_slots, conflict_slots FROM read_parquet(?) WHERE detector_id = ? AND direction = ? AND lane_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp", [list(map(str, bins)), event["detector_id"], event["direction"], event["lane_id"], start, end])
        by_time = {row["timestamp"]: row for row in observations}
        if len(by_time) != len(observations):
            raise HTTPException(status_code=503, detail="Duplicate bin timestamps in pilot data")
        points = []
        stamp = start
        while stamp <= end:
            row = by_time.get(stamp)
            points.append(row if row else {"timestamp": stamp, "available_at": None, "speed_kmh": None, "usable": False,
                                           "present_slots": 0, "valid_slots": 0, "flow_slots": 0, "offline_slots": None, "conflict_slots": None})
            stamp += timedelta(minutes=5)
        return {"event_id": event_id, "points": points, "grid_minutes": 5,
                "notice": "Historical observations include post-prediction data; not all points were available at prediction time. Null is missing, never zero speed."}

    return application


app = create_app()
