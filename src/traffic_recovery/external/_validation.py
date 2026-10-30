"""Shared validation for prediction-time external feature adapters."""
from __future__ import annotations

from collections.abc import Iterable
import re

import pandas as pd


HKT = "Asia/Hong_Kong"
PROVENANCE_COLUMNS = ("source_url", "source_retrieved_at", "source_sha256")


def require_columns(frame: pd.DataFrame, columns: Iterable[str], table: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{table} missing columns: {sorted(missing)}")


def require_aware(frame: pd.DataFrame, columns: Iterable[str], table: str, *, nullable: bool = False) -> None:
    for column in columns:
        if not isinstance(frame[column].dtype, pd.DatetimeTZDtype):
            raise ValueError(f"{table}.{column} must be timezone-aware")
        if not nullable and frame[column].isna().any():
            raise ValueError(f"{table}.{column} must not be missing")


def require_string_ids(
    frame: pd.DataFrame, columns: Iterable[str], table: str, *, nullable: bool = False
) -> None:
    """Reject numeric/coerced identifiers so leading-zero loss cannot be hidden."""
    for column in columns:
        values = frame[column]
        if not nullable and values.isna().any():
            raise ValueError(f"{table}.{column} must not be missing")
        known = values.dropna()
        if not known.map(lambda value: isinstance(value, str)).all():
            raise ValueError(f"{table}.{column} must contain strings")
        if known.str.strip().eq("").any():
            raise ValueError(f"{table}.{column} must be nonempty")


def require_provenance(frame: pd.DataFrame, table: str) -> None:
    """Require row-level source identity while staged files retain original bytes."""
    require_columns(frame, PROVENANCE_COLUMNS, table)
    if not len(frame):
        return
    require_string_ids(frame, ["source_url", "source_sha256"], table)
    require_aware(frame, ["source_retrieved_at"], table)
    hashes = frame.source_sha256.str.lower()
    if not hashes.map(lambda value: bool(re.fullmatch(r"[0-9a-f]{64}", value))).all():
        raise ValueError(f"{table}.source_sha256 must contain SHA-256 hex digests")


def validate_events(events: pd.DataFrame, extra: Iterable[str] = ()) -> None:
    require_columns(events, ["event_id", "prediction_time", *extra], "events")
    require_aware(events, ["prediction_time"], "events")
    require_string_ids(events, ["event_id", *extra], "events")
    if events.event_id.duplicated().any():
        raise ValueError("events.event_id must be unique")


def hkt(series: pd.Series) -> pd.Series:
    return series.dt.tz_convert(HKT)


def timestamp_series(values: list[object], index: pd.Index) -> pd.Series:
    return pd.Series(pd.to_datetime(values, utc=True), index=index).dt.tz_convert(HKT)
