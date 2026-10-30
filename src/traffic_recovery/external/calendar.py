"""Prediction-time calendar features backed by a versioned holiday table."""
from __future__ import annotations

import math

import pandas as pd

from ._validation import (
    hkt, require_aware, require_columns, require_provenance, require_string_ids,
    timestamp_series, validate_events,
)


def calendar_features(events: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
    """Build clock and official-holiday features for each event.

    ``holidays`` must preserve the official publication availability of each
    holiday row. A holiday contributes only when its ``available_at`` is no later
    than the event prediction time. ``local_date`` is interpreted as a Hong Kong
    civil date, never as a UTC timestamp.
    """
    validate_events(events)
    require_columns(
        holidays,
        ["holiday_id", "local_date", "holiday_name", "available_at"],
        "holidays",
    )
    require_provenance(holidays, "holidays")
    if len(holidays):
        require_aware(holidays, ["available_at"], "holidays")
        require_string_ids(holidays, ["holiday_id"], "holidays")
        dates = pd.to_datetime(holidays.local_date, errors="raise")
        if isinstance(dates.dtype, pd.DatetimeTZDtype):
            raise ValueError("holidays.local_date must be a civil date without a timezone")
        holiday_dates = dates.dt.date
    else:
        holiday_dates = pd.Series([], dtype="object", index=holidays.index)

    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        when = event.prediction_time.tz_convert("Asia/Hong_Kong")
        local_date = when.date()
        known = holidays.loc[holidays.available_at.le(when)].copy()
        known_dates = holiday_dates.loc[known.index]
        same = known_dates.eq(local_date)
        before = known_dates.eq(local_date + pd.Timedelta(days=1))
        after = known_dates.eq(local_date - pd.Timedelta(days=1))
        source_observed = bool(len(known))
        angle_hour = 2 * math.pi * (when.hour * 60 + when.minute) / (24 * 60)
        angle_dow = 2 * math.pi * when.dayofweek / 7
        rows.append({
            "event_id": event.event_id,
            "prediction_time": when,
            "hour_sin": math.sin(angle_hour),
            "hour_cos": math.cos(angle_hour),
            "dow_sin": math.sin(angle_dow),
            "dow_cos": math.cos(angle_dow),
            "is_weekend": when.dayofweek >= 5,
            "is_public_holiday": bool(same.any()) if source_observed else pd.NA,
            "is_day_before_holiday": bool(before.any()) if source_observed else pd.NA,
            "is_day_after_holiday": bool(after.any()) if source_observed else pd.NA,
            "holiday_count": int(same.sum()) if source_observed else pd.NA,
            "calendar_source_observed": source_observed,
            "calendar_max_source_available_at": (
                known.available_at.max() if source_observed else pd.NaT
            ),
        })
    result = pd.DataFrame(rows)
    if len(result):
        result["prediction_time"] = hkt(result.prediction_time)
        result["calendar_max_source_available_at"] = timestamp_series(
            result.calendar_max_source_available_at.tolist(), result.index
        )
    return result
