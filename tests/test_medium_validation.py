"""SYNTHETIC tests for independent real-event verification helper."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from traffic_recovery.data.events import build_events

SPEC = importlib.util.spec_from_file_location("medium_pilot", Path("scripts/medium_pilot.py"))
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_validation_detects_incorrect_label() -> None:
    start = pd.Timestamp("2026-01-01", tz="Asia/Hong_Kong")
    times = pd.date_range(start, periods=12, freq="5min")
    bins = pd.DataFrame({"detector_id": "SYNTH", "direction": "East", "lane_id": "TEST",
        "timestamp": times, "available_at": times + pd.Timedelta(minutes=10),
        "speed_kmh": [90, 90, 90, 40, 40, 90, 90, 90, 90, 90, 90, 90],
        "valid_slots": 2, "usable": True})
    events = build_events(bins, 100, start=start, end=start + pd.Timedelta(hours=1))
    events["reference_fit_end"] = start
    assert MODULE.validate_event_rows(events, bins)["events_checked"] == 1
    events.loc[0, "label_15m"] = 0
    with pytest.raises(AssertionError):
        MODULE.validate_event_rows(events, bins)
