"""Integrate independently auditable external feature groups by event key."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd

from .calendar import calendar_features
from .incidents import incident_features
from .major_events import major_event_features
from .weather import DEFAULT_VALUE_COLUMNS, weather_features
from ._validation import validate_events


@dataclass(frozen=True)
class ContextRules:
    """Versioned tolerances for external feature integration."""

    version: str = "external-context-v1"
    weather_max_age: pd.Timedelta = pd.Timedelta(hours=1)
    incident_max_distance_m: float | None = None
    major_event_max_distance_m: float | None = None
    major_event_before: pd.Timedelta = pd.Timedelta(hours=2)
    major_event_after: pd.Timedelta = pd.Timedelta(hours=1)

    @classmethod
    def from_path(cls, path: Path) -> "ContextRules":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=str(payload["version"]),
            weather_max_age=pd.Timedelta(minutes=payload["weather"]["max_age_minutes"]),
            incident_max_distance_m=payload["incident"]["max_distance_m"],
            major_event_max_distance_m=payload["major_event"]["max_distance_m"],
            major_event_before=pd.Timedelta(minutes=payload["major_event"]["before_minutes"]),
            major_event_after=pd.Timedelta(minutes=payload["major_event"]["after_minutes"]),
        )


def build_context_features(
    events: pd.DataFrame,
    *,
    holidays: pd.DataFrame,
    weather_observations: pd.DataFrame,
    incidents: pd.DataFrame,
    major_events: pd.DataFrame,
    weather_value_columns: Iterable[str] = DEFAULT_VALUE_COLUMNS,
    rules: ContextRules = ContextRules(),
) -> pd.DataFrame:
    """Return exactly one external-context row for every input event."""
    validate_events(events, ["segment_id", "weather_station_id"])
    key = ["event_id", "prediction_time"]
    result = events[key].copy()
    groups = [
        calendar_features(events, holidays),
        weather_features(
            events, weather_observations,
            value_columns=weather_value_columns, max_age=rules.weather_max_age,
        ),
        incident_features(events, incidents, max_distance_m=rules.incident_max_distance_m),
        major_event_features(
            events, major_events, before=rules.major_event_before, after=rules.major_event_after,
            max_distance_m=rules.major_event_max_distance_m,
        ),
    ]
    for group in groups:
        payload = [column for column in group.columns if column not in key]
        result = result.merge(group[key + payload], on=key, how="left", validate="one_to_one")
    if len(result) != len(events) or result.event_id.duplicated().any():
        raise ValueError("External integration changed the event grain")
    result["context_version"] = rules.version
    return result
