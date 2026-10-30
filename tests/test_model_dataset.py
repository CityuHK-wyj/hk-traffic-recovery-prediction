"""SYNTHETIC model-dataset integration tests; never research observations."""
from pathlib import Path

import pandas as pd
import pytest

from traffic_recovery.models.contract import ExperimentContract
from traffic_recovery.models.dataset import build_model_dataset, build_model_dataset_files


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "configs" / "experiment_contract.json"
CONTRACT = ExperimentContract.from_path(CONTRACT_PATH)


def event_rows() -> pd.DataFrame:
    prediction = pd.to_datetime([
        "2026-10-15T10:00:00+08:00",
        "2026-10-17T10:00:00+08:00",
        "2026-10-19T10:00:00+08:00",
    ], utc=True).tz_convert("Asia/Hong_Kong")
    return pd.DataFrame({
        "event_id": ["SYNTHETIC-TRAIN", "SYNTHETIC-VALID", "SYNTHETIC-TEST"],
        "prediction_time": prediction,
        "split_proposal": pd.Series(["train", "validation", "test"], dtype="string"),
        "detector_id": ["D1", "D2", "D3"],
        "direction": ["East"] * 3,
        "lane_id": ["L1", "L2", "L3"],
        "segment_id": ["S1", "S2", "S3"],
        "label_15m": pd.Series([0, 1, 1], dtype="Int8"),
        "label_30m": pd.Series([0, 1, 1], dtype="Int8"),
        "label_60m": pd.Series([1, 1, 1], dtype="Int8"),
        "reason_15m": ["observed"] * 3,
        "reason_30m": ["observed"] * 3,
        "reason_60m": ["observed"] * 3,
        "speed_kmh": [30.0, 40.0, 45.0],
        "speed_ratio": [0.3, 0.4, 0.45],
        "baseline_kmh": [100.0] * 3,
        "valid_slots": [4] * 3,
        "onset_observed_minutes": [10] * 3,
        "feature_max_available_at": prediction - pd.Timedelta(minutes=1),
        "recovery_time": prediction + pd.Timedelta(minutes=30),
        "onset_time": prediction - pd.Timedelta(minutes=10),
        "definition_version": ["synthetic-v1"] * 3,
    })


def context_rows(events: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "event_id": events.event_id,
        "prediction_time": events.prediction_time,
        "is_weekend": [False, True, False],
        "calendar_source_observed": [True] * 3,
        "calendar_max_source_available_at": events.prediction_time - pd.Timedelta(days=1),
        "weather_missing": [False, False, True],
        "weather_available_at": pd.DatetimeIndex([
            events.prediction_time.iloc[0] - pd.Timedelta(minutes=2),
            events.prediction_time.iloc[1] - pd.Timedelta(minutes=2),
            pd.NaT,
        ]),
        "context_version": ["synthetic-context"] * 3,
    })


def spatial_rows(events: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "event_id": events.event_id,
        "prediction_time": events.prediction_time,
        "upstream_mean_speed_kmh": [20.0, pd.NA, 30.0],
        "upstream_max_available_at": events.prediction_time - pd.Timedelta(minutes=2),
        "network_version": ["synthetic-network"] * 3,
        "feature_status": ["verified_neighbors"] * 3,
    })


def test_model_dataset_merges_exact_grain_and_prunes_unapproved_columns() -> None:
    events = event_rows()
    result, report = build_model_dataset(
        events, CONTRACT, context=context_rows(events), spatial=spatial_rows(events)
    )
    assert result.event_id.tolist() == events.event_id.tolist()
    assert result.split.tolist() == ["train", "validation", "test"]
    assert "onset_time" not in result
    assert "recovery_time" in result
    assert result.dataset_version.nunique() == 1
    assert report["feature_groups"]["spatial"] == ["upstream_mean_speed_kmh"]


def test_model_dataset_rejects_missing_or_duplicate_feature_keys() -> None:
    events = event_rows()
    with pytest.raises(ValueError, match="exactly match"):
        build_model_dataset(events, CONTRACT, context=context_rows(events).iloc[:2])
    duplicate = pd.concat([context_rows(events), context_rows(events).iloc[:1]])
    with pytest.raises(ValueError, match="one row per event"):
        build_model_dataset(events, CONTRACT, context=duplicate)


def test_model_dataset_rejects_collisions_and_future_availability() -> None:
    events = event_rows()
    collision = context_rows(events).assign(speed_ratio=[0.1, 0.1, 0.1])
    with pytest.raises(ValueError, match="collide"):
        build_model_dataset(events, CONTRACT, context=collision)
    context = context_rows(events)
    context["calendar_max_source_available_at"] = events.prediction_time + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="unavailable"):
        build_model_dataset(events, CONTRACT, context=context)


def test_model_dataset_files_write_hashed_manifest(tmp_path: Path) -> None:
    events = event_rows()
    event_path = tmp_path / "events.parquet"
    context_path = tmp_path / "context.parquet"
    output_path = tmp_path / "model.parquet"
    manifest_path = tmp_path / "model-manifest.json"
    events.to_parquet(event_path, index=False)
    context_rows(events).to_parquet(context_path, index=False)
    manifest = build_model_dataset_files(
        events_path=event_path, context_path=context_path, spatial_path=None,
        contract_path=CONTRACT_PATH, output_path=output_path,
        manifest_path=manifest_path,
    )
    assert manifest["validation"]["rows"] == 3
    assert len(manifest["output"]["sha256"]) == 64
    assert output_path.is_file() and manifest_path.is_file()
