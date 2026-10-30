"""As-of incident and closure features from source snapshots."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._validation import (
    hkt, require_aware, require_columns, require_provenance, require_string_ids,
    timestamp_series, validate_events,
)


def incident_features(
    events: pd.DataFrame,
    incidents: pd.DataFrame,
    *,
    max_distance_m: float | None = None,
) -> pd.DataFrame:
    """Summarize incidents active in the latest source snapshot by prediction time.

    Multiple rows for an incident are treated as successive source snapshots.
    Only the latest row already available at prediction time is considered, so a
    retrospectively populated end time cannot alter an earlier feature row.
    """
    if max_distance_m is not None and max_distance_m < 0:
        raise ValueError("max_distance_m must be nonnegative")
    validate_events(events, ["segment_id"])
    required = [
        "incident_id", "segment_id", "available_at", "effective_start",
        "effective_end", "distance_m", "is_road_closure",
    ]
    require_columns(incidents, required, "incidents")
    require_provenance(incidents, "incidents")
    if len(incidents):
        require_aware(incidents, ["available_at", "effective_start"], "incidents")
        require_aware(incidents, ["effective_end"], "incidents", nullable=True)
        require_string_ids(incidents, ["incident_id", "segment_id"], "incidents")
        known_closure = incidents.is_road_closure.dropna()
        if not known_closure.map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise ValueError("incidents.is_road_closure must contain booleans or missing")
        pd.to_numeric(incidents.distance_m.dropna(), errors="raise")
        if (incidents.distance_m.dropna() < 0).any():
            raise ValueError("Incident distance must be nonnegative")
        known_end = incidents.effective_end.notna()
        if (incidents.loc[known_end, "effective_end"] <= incidents.loc[known_end, "effective_start"]).any():
            raise ValueError("Incident effective_end must follow effective_start")

    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        when = event.prediction_time
        snapshots = incidents.loc[
            incidents.segment_id.eq(event.segment_id)
            & incidents.available_at.le(when)
        ].sort_values("available_at").drop_duplicates("incident_id", keep="last")
        active = snapshots.loc[
            snapshots.effective_start.le(when)
            & (snapshots.effective_end.isna() | snapshots.effective_end.gt(when))
        ]
        if max_distance_m is not None:
            active = active.loc[active.distance_m.notna() & active.distance_m.le(max_distance_m)]
        source_observed = bool(len(snapshots))
        distance = active.distance_m.dropna()
        age = (when - active.effective_start).dt.total_seconds() / 60 if len(active) else pd.Series(dtype=float)
        rows.append({
            "event_id": event.event_id,
            "prediction_time": when,
            "incident_records_observed": source_observed,
            "active_incident_count": len(active) if source_observed else pd.NA,
            "has_active_incident": bool(len(active)) if source_observed else pd.NA,
            "active_road_closure_count": (
                pd.NA if not source_observed or active.is_road_closure.isna().any()
                else int(active.is_road_closure.sum())
            ),
            "active_road_closure_status_missing": (
                bool(active.is_road_closure.isna().any()) if source_observed else pd.NA
            ),
            "nearest_incident_distance_m": distance.min() if len(distance) else pd.NA,
            "oldest_incident_age_minutes": age.max() if len(age) else pd.NA,
            "incident_max_available_at": (
                snapshots.available_at.max() if source_observed else pd.NaT
            ),
        })
    result = pd.DataFrame(rows)
    if len(result):
        result["prediction_time"] = hkt(result.prediction_time)
        result["incident_max_available_at"] = timestamp_series(
            result.incident_max_available_at.tolist(), result.index
        )
    return result
