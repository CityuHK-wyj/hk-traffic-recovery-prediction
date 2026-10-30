"""Executable, fail-closed contract for ML-ready event tables.

This module validates interfaces; it does not scientifically approve the
provisional lane-event definition or temporal split policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
from typing import Iterable

import pandas as pd

from traffic_recovery.data.http import sha256_file


ALLOWED_SPLITS = {"train", "validation", "test", "purged"}
OUTCOME_PREFIXES = ("label_", "reason_")
OUTCOME_COLUMNS = {
    "recovery_time", "recovery_available_at", "followup_end",
    "termination_reason", "episode_separated_at",
}


@dataclass(frozen=True)
class ExperimentContract:
    """Versioned executable subset of the pending scientific contract."""

    version: str
    status: str
    horizons: tuple[int, ...]
    validation_start: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    feature_groups: dict[str, tuple[str, ...]]
    availability_columns: tuple[str, ...]
    availability_requirements: dict[str, tuple[str, ...]]

    @classmethod
    def from_path(cls, path: Path) -> "ExperimentContract":
        payload = json.loads(path.read_text(encoding="utf-8"))
        boundaries = payload["split_boundaries"]
        stamps = {
            key: pd.Timestamp(boundaries[key])
            for key in ("validation_start", "test_start", "test_end")
        }
        if any(stamp.tzinfo is None for stamp in stamps.values()):
            raise ValueError("Split boundaries must be timezone-aware")
        if not stamps["validation_start"] < stamps["test_start"] < stamps["test_end"]:
            raise ValueError("Split boundaries must be strictly increasing")
        groups = {
            name: tuple(columns) for name, columns in payload["feature_groups"].items()
        }
        horizons = tuple(int(value) for value in payload["horizons_minutes"])
        if not horizons or tuple(sorted(set(horizons))) != horizons:
            raise ValueError("Horizons must be unique and increasing")
        availability_columns = tuple(payload["availability_columns"])
        requirements = {
            str(column): tuple(features)
            for column, features in payload["availability_requirements"].items()
        }
        if set(requirements) != set(availability_columns):
            raise ValueError("Availability requirements must cover every watermark column")
        unknown_requirement_features = {
            feature for features in requirements.values() for feature in features
        } - {feature for features in groups.values() for feature in features}
        if unknown_requirement_features:
            raise ValueError(
                "Availability requirements reference unknown features: "
                f"{sorted(unknown_requirement_features)}"
            )
        return cls(
            version=str(payload["version"]),
            status=str(payload["scientific_approval"]),
            horizons=horizons,
            validation_start=stamps["validation_start"],
            test_start=stamps["test_start"],
            test_end=stamps["test_end"],
            feature_groups=groups,
            availability_columns=availability_columns,
            availability_requirements=requirements,
        )

    @property
    def feature_allowlist(self) -> tuple[str, ...]:
        return tuple(column for columns in self.feature_groups.values() for column in columns)


def _require_aware_hkt(series: pd.Series, name: str) -> None:
    if not isinstance(series.dtype, pd.DatetimeTZDtype) or series.isna().any():
        raise ValueError(f"{name} must contain non-null timezone-aware timestamps")
    zone = str(series.dt.tz)
    if zone not in {"Asia/Hong_Kong", "Hongkong"}:
        raise ValueError(f"{name} must use Asia/Hong_Kong, got {zone}")


def validate_event_table(frame: pd.DataFrame, contract: ExperimentContract) -> dict[str, int]:
    """Validate keys, labels, splits, availability and leakage boundaries."""
    labels = [f"label_{horizon}m" for horizon in contract.horizons]
    required = {"event_id", "prediction_time", "split", *labels}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing event contract columns: {sorted(missing)}")
    known_event_ids = frame.event_id.dropna()
    if frame.event_id.isna().any() or not known_event_ids.map(
        lambda value: isinstance(value, str)
    ).all() or known_event_ids.str.strip().eq("").any():
        raise ValueError("event_id must be a nonempty string")
    if frame.event_id.duplicated().any():
        raise ValueError("event_id must be unique")
    _require_aware_hkt(frame.prediction_time, "prediction_time")
    unexpected_splits = set(frame.split.dropna().astype(str)) - ALLOWED_SPLITS
    if frame.split.isna().any() or unexpected_splits:
        raise ValueError(f"Invalid split values: {sorted(unexpected_splits)}")
    for label in labels:
        invalid = frame[label].dropna().loc[lambda values: ~values.isin([0, 1])]
        if len(invalid):
            raise ValueError(f"{label} must contain only 0, 1 or missing")
    for shorter, longer in zip(labels, labels[1:]):
        known = frame[shorter].notna() & frame[longer].notna()
        if (frame.loc[known, shorter] > frame.loc[known, longer]).any():
            raise ValueError("Known within-horizon labels must be monotone")

    horizon = pd.Timedelta(minutes=max(contract.horizons))
    prediction_end = frame.prediction_time + horizon
    bad_train = frame.split.eq("train") & prediction_end.ge(contract.validation_start)
    bad_validation = frame.split.eq("validation") & (
        frame.prediction_time.lt(contract.validation_start)
        | prediction_end.ge(contract.test_start)
    )
    bad_test = frame.split.eq("test") & (
        frame.prediction_time.lt(contract.test_start)
        | prediction_end.ge(contract.test_end)
    )
    if (bad_train | bad_validation | bad_test).any():
        raise ValueError("A non-purged split crosses a configured temporal boundary")

    for column, protected_features in contract.availability_requirements.items():
        features_present = any(feature in frame for feature in protected_features)
        if features_present and column not in frame:
            raise ValueError(
                f"{column} is required when protected features are present"
            )
        if column not in frame:
            continue
        if not isinstance(frame[column].dtype, pd.DatetimeTZDtype):
            raise ValueError(f"{column} must be timezone-aware when present")
        present_features = [
            feature for feature in protected_features if feature in frame
        ]
        populated = (
            frame[present_features].notna().any(axis=1)
            if present_features else pd.Series(False, index=frame.index)
        )
        if features_present and (populated & frame[column].isna()).any():
            raise ValueError(
                f"{column} is missing for rows with protected feature values"
            )
        known = frame[column].notna()
        if (frame.loc[known, column] > frame.loc[known, "prediction_time"]).any():
            raise ValueError(f"{column} contains information unavailable at prediction time")

    return {
        "rows": len(frame),
        "events": frame.event_id.nunique(),
        "purged": int(frame.split.eq("purged").sum()),
        **{f"known_{label}": int(frame[label].notna().sum()) for label in labels},
    }


def select_model_rows(
    frame: pd.DataFrame,
    contract: ExperimentContract,
    *,
    horizon: int,
    features: Iterable[str],
    splits: Iterable[str] = ("train", "validation", "test"),
) -> tuple[pd.DataFrame, pd.Series]:
    """Return one horizon's known-label rows using only approved feature names."""
    validate_event_table(frame, contract)
    if horizon not in contract.horizons:
        raise ValueError(f"Unsupported horizon: {horizon}")
    requested = tuple(features)
    if len(set(requested)) != len(requested):
        raise ValueError("Feature names must be unique")
    forbidden = [
        name for name in requested
        if name in OUTCOME_COLUMNS or name.startswith(OUTCOME_PREFIXES)
    ]
    unknown = sorted(set(requested) - set(contract.feature_allowlist))
    if forbidden:
        raise ValueError(f"Outcome columns cannot be features: {sorted(forbidden)}")
    if unknown:
        raise ValueError(f"Features are not in the contract allowlist: {unknown}")
    missing = set(requested) - set(frame.columns)
    if missing:
        raise ValueError(f"Requested feature columns are missing: {sorted(missing)}")
    selected_splits = set(splits)
    if not selected_splits <= ALLOWED_SPLITS - {"purged"}:
        raise ValueError("Model rows may use only train, validation or test")
    label = f"label_{horizon}m"
    eligible = frame.split.isin(selected_splits) & frame[label].notna()
    return frame.loc[eligible, list(requested)].copy(), frame.loc[eligible, label].astype("Int8")


def validation_manifest(
    event_path: Path,
    contract_path: Path,
    contract: ExperimentContract,
    report: dict[str, int],
) -> dict[str, object]:
    """Record the exact cohort/config evidence used for contract validation."""
    return {
        "manifest_version": "experiment-validation-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": contract.version,
        "scientific_approval": contract.status,
        "events": {"path": event_path.as_posix(), "sha256": sha256_file(event_path)},
        "contract": {"path": contract_path.as_posix(), "sha256": sha256_file(contract_path)},
        "validation": report,
        "python": platform.python_version(),
        "pandas": pd.__version__,
    }
