"""Prediction-time features for pre-published major events."""
from __future__ import annotations

import pandas as pd

from ._validation import (
    hkt, require_aware, require_columns, require_provenance, require_string_ids,
    timestamp_series, validate_events,
)


def major_event_features(
    events: pd.DataFrame,
    major_events: pd.DataFrame,
    *,
    before: pd.Timedelta = pd.Timedelta(hours=2),
    after: pd.Timedelta = pd.Timedelta(hours=1),
    max_distance_m: float | None = None,
) -> pd.DataFrame:
    """Summarize active, upcoming and recent events known at prediction time."""
    if before < pd.Timedelta(0) or after < pd.Timedelta(0):
        raise ValueError("Major-event influence windows must be nonnegative")
    if max_distance_m is not None and max_distance_m < 0:
        raise ValueError("max_distance_m must be nonnegative")
    validate_events(events, ["segment_id"])
    required = [
        "major_event_id", "segment_id", "available_at", "start_time",
        "end_time", "distance_m",
    ]
    require_columns(major_events, required, "major_events")
    require_provenance(major_events, "major_events")
    if len(major_events):
        require_aware(major_events, ["available_at", "start_time", "end_time"], "major_events")
        require_string_ids(major_events, ["major_event_id", "segment_id"], "major_events")
        if (major_events.end_time <= major_events.start_time).any():
            raise ValueError("Major-event end_time must follow start_time")
        pd.to_numeric(major_events.distance_m.dropna(), errors="raise")
        if (major_events.distance_m.dropna() < 0).any():
            raise ValueError("Major-event distance must be nonnegative")

    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        when = event.prediction_time
        known = major_events.loc[
            major_events.segment_id.eq(event.segment_id)
            & major_events.available_at.le(when)
        ].sort_values("available_at").drop_duplicates("major_event_id", keep="last")
        if max_distance_m is not None:
            known = known.loc[known.distance_m.notna() & known.distance_m.le(max_distance_m)]
        source_observed = bool(len(known))
        active = known.loc[known.start_time.le(when) & known.end_time.ge(when)]
        upcoming = known.loc[known.start_time.gt(when) & known.start_time.le(when + before)]
        recent = known.loc[known.end_time.lt(when) & known.end_time.ge(when - after)]
        relevant = pd.concat([active, upcoming, recent]).drop_duplicates("major_event_id")
        distances = relevant.distance_m.dropna()
        to_next = ((upcoming.start_time - when).dt.total_seconds() / 60
                   if len(upcoming) else pd.Series(dtype=float))
        since_latest = ((when - recent.end_time).dt.total_seconds() / 60
                        if len(recent) else pd.Series(dtype=float))
        rows.append({
            "event_id": event.event_id,
            "prediction_time": when,
            "major_event_records_observed": source_observed,
            "active_major_event_count": len(active) if source_observed else pd.NA,
            "upcoming_major_event_count": len(upcoming) if source_observed else pd.NA,
            "recent_major_event_count": len(recent) if source_observed else pd.NA,
            "nearest_major_event_distance_m": distances.min() if len(distances) else pd.NA,
            "minutes_to_next_major_event": to_next.min() if len(to_next) else pd.NA,
            "minutes_since_latest_major_event": since_latest.min() if len(since_latest) else pd.NA,
            "major_event_max_available_at": (
                known.available_at.max() if source_observed else pd.NaT
            ),
        })
    result = pd.DataFrame(rows)
    if len(result):
        result["prediction_time"] = hkt(result.prediction_time)
        result["major_event_max_available_at"] = timestamp_series(
            result.major_event_max_available_at.tolist(), result.index
        )
    return result
