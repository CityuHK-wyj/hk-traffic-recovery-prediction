"""Backward, availability-aware weather observation joins."""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from ._validation import (
    hkt, require_aware, require_columns, require_provenance, require_string_ids,
    timestamp_series, validate_events,
)


DEFAULT_VALUE_COLUMNS = (
    "temperature_c", "relative_humidity_pct", "rainfall_mm", "wind_speed_kmh",
)


def weather_features(
    events: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    value_columns: Iterable[str] = DEFAULT_VALUE_COLUMNS,
    max_age: pd.Timedelta = pd.Timedelta(hours=1),
) -> pd.DataFrame:
    """Select the latest already-available observation at an assigned station."""
    if max_age <= pd.Timedelta(0):
        raise ValueError("max_age must be positive")
    values = tuple(value_columns)
    if not values:
        raise ValueError("At least one weather value column is required")
    validate_events(events, ["weather_station_id"])
    require_columns(
        observations,
        ["station_id", "observed_at", "available_at", *values],
        "weather_observations",
    )
    require_provenance(observations, "weather_observations")
    if len(observations):
        require_aware(observations, ["observed_at", "available_at"], "weather_observations")
        require_string_ids(observations, ["station_id"], "weather_observations")
        if (observations.available_at < observations.observed_at).any():
            raise ValueError("Weather availability cannot precede observation time")
        for column in values:
            pd.to_numeric(observations[column].dropna(), errors="raise")

    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        when = event.prediction_time
        candidates = observations.loc[
            observations.station_id.eq(event.weather_station_id)
            & observations.observed_at.le(when)
            & observations.available_at.le(when)
            & observations.observed_at.ge(when - max_age)
        ].sort_values(["observed_at", "available_at"])
        row: dict[str, object] = {
            "event_id": event.event_id,
            "prediction_time": when,
            "weather_station_id": event.weather_station_id,
            "weather_observed_at": pd.NaT,
            "weather_available_at": pd.NaT,
            "weather_age_minutes": pd.NA,
            "weather_missing": True,
            **{column: pd.NA for column in values},
        }
        if len(candidates):
            selected = candidates.iloc[-1]
            row.update({column: selected[column] for column in values})
            row.update({
                "weather_observed_at": selected.observed_at,
                "weather_available_at": selected.available_at,
                "weather_age_minutes": (when - selected.observed_at).total_seconds() / 60,
                "weather_missing": bool(selected[list(values)].isna().all()),
            })
        rows.append(row)
    result = pd.DataFrame(rows)
    if len(result):
        result["prediction_time"] = hkt(result.prediction_time)
        for column in ["weather_observed_at", "weather_available_at"]:
            result[column] = timestamp_series(result[column].tolist(), result.index)
    return result
