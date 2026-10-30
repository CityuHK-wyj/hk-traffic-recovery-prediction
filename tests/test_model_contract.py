"""SYNTHETIC contract tests; no rows are research observations."""
from pathlib import Path

import pandas as pd
import pytest

from traffic_recovery.models.contract import (
    ExperimentContract,
    select_model_rows,
    validation_manifest,
    validate_event_table,
)


ROOT = Path(__file__).parents[1]
CONTRACT = ExperimentContract.from_path(ROOT / "configs" / "experiment_contract.json")


def events() -> pd.DataFrame:
    prediction = pd.to_datetime([
        "2026-10-15T10:00:00+08:00",
        "2026-10-17T10:00:00+08:00",
        "2026-10-19T10:00:00+08:00",
        "2026-10-16T23:30:00+08:00",
    ], utc=True).tz_convert("Asia/Hong_Kong")
    return pd.DataFrame({
        "event_id": ["SYNTHETIC-1", "SYNTHETIC-2", "SYNTHETIC-3", "SYNTHETIC-P"],
        "prediction_time": prediction,
        "split": pd.Series(["train", "validation", "test", "purged"], dtype="string"),
        "label_15m": pd.Series([0, 1, 1, pd.NA], dtype="Int8"),
        "label_30m": pd.Series([0, 1, 1, pd.NA], dtype="Int8"),
        "label_60m": pd.Series([1, 1, 1, pd.NA], dtype="Int8"),
        "speed_ratio": [0.4, 0.5, 0.3, 0.4],
        "recovery_time": prediction + pd.Timedelta(minutes=30),
        "feature_max_available_at": prediction - pd.Timedelta(minutes=1),
    })


def test_contract_loads_and_validates_known_censoring() -> None:
    report = validate_event_table(events(), CONTRACT)
    assert report == {
        "rows": 4, "events": 4, "purged": 1,
        "known_label_15m": 3, "known_label_30m": 3, "known_label_60m": 3,
    }


def test_model_rows_drop_censored_and_reject_outcomes() -> None:
    features, labels = select_model_rows(
        events(), CONTRACT, horizon=60, features=["speed_ratio"]
    )
    assert len(features) == 3 and labels.tolist() == [1, 1, 1]
    with pytest.raises(ValueError, match="Outcome columns"):
        select_model_rows(events(), CONTRACT, horizon=60, features=["recovery_time"])


@pytest.mark.parametrize("mutation, message", [
    (lambda frame: frame.assign(event_id=["x", "x", "y", "z"]), "unique"),
    (lambda frame: frame.assign(label_15m=pd.Series([1, 0, 1, pd.NA], dtype="Int8")), "monotone"),
    (lambda frame: frame.assign(feature_max_available_at=frame.prediction_time + pd.Timedelta(minutes=1)), "unavailable"),
    (lambda frame: frame.assign(prediction_time=frame.prediction_time.dt.tz_localize(None)), "timezone-aware"),
])
def test_contract_rejects_invalid_tables(mutation, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_event_table(mutation(events()), CONTRACT)


def test_contract_rejects_unpurged_boundary_crossing() -> None:
    frame = events()
    frame.loc[3, "split"] = "train"
    with pytest.raises(ValueError, match="temporal boundary"):
        validate_event_table(frame, CONTRACT)


def test_contract_requires_string_ids_and_feature_watermarks() -> None:
    with pytest.raises(ValueError, match="nonempty string"):
        validate_event_table(events().assign(event_id=[1, 2, 3, 4]), CONTRACT)
    with pytest.raises(ValueError, match="feature_max_available_at is required"):
        validate_event_table(events().drop(columns="feature_max_available_at"), CONTRACT)
    missing_row_watermark = events()
    missing_row_watermark.loc[0, "feature_max_available_at"] = pd.NaT
    with pytest.raises(ValueError, match="missing for rows"):
        validate_event_table(missing_row_watermark, CONTRACT)


def test_validation_manifest_hashes_exact_inputs(tmp_path: Path) -> None:
    event_path = tmp_path / "events.parquet"
    events().to_parquet(event_path, index=False)
    report = validate_event_table(events(), CONTRACT)
    manifest = validation_manifest(
        event_path, ROOT / "configs" / "experiment_contract.json", CONTRACT, report
    )
    assert len(manifest["events"]["sha256"]) == 64
    assert manifest["contract_version"] == CONTRACT.version
    assert manifest["validation"]["events"] == 4
