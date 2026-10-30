"""SYNTHETIC ensemble-model tests (random forest and hist gradient boosting).

Values produced here are code-behavior checks only, never research results.
"""
from pathlib import Path

import pandas as pd

from traffic_recovery.models.contract import ExperimentContract
from traffic_recovery.models.supervised import (
    SupervisedRules,
    train_supervised,
)

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "configs" / "experiment_contract.json"
RULES_PATH = ROOT / "configs" / "supervised_models.json"
CONTRACT = ExperimentContract.from_path(CONTRACT_PATH)
RULES = SupervisedRules.from_path(RULES_PATH)


def dataset() -> pd.DataFrame:
    times = [
        *(f"2026-10-15T{hour:02d}:00:00+08:00" for hour in range(8, 16)),
        *(f"2026-10-17T{hour:02d}:00:00+08:00" for hour in range(8, 14)),
        *(f"2026-10-19T{hour:02d}:00:00+08:00" for hour in range(8, 14)),
    ]
    prediction = pd.to_datetime(times, utc=True).tz_convert("Asia/Hong_Kong")
    labels = pd.Series(([0, 1] * 4) + ([0, 1] * 3) + ([0, 1] * 3), dtype="Int8")
    speed_ratio = [0.30 if label == 0 else 0.75 for label in labels]
    return pd.DataFrame({
        "event_id": [f"SYNTHETIC-ENSEMBLE-{index}" for index in range(len(times))],
        "prediction_time": prediction,
        "split": pd.Series(["train"] * 8 + ["validation"] * 6 + ["test"] * 6,
                           dtype="string"),
        "label_15m": labels,
        "label_30m": labels,
        "label_60m": labels,
        "speed_kmh": [ratio * 80 for ratio in speed_ratio],
        "speed_ratio": speed_ratio,
        "baseline_kmh": [80.0] * len(times),
        "valid_slots": [4] * len(times),
        "onset_observed_minutes": list(range(len(times))),
        "feature_max_available_at": prediction - pd.Timedelta(minutes=1),
        "dataset_version": [CONTRACT.version] * len(times),
    })


def test_random_forest_trains_and_exports_importance() -> None:
    result = train_supervised(dataset(), CONTRACT, RULES, kind="rf")
    assert len(result.predictions) == len(dataset()) * 3
    assert result.predictions.y_score.between(0, 1).all()
    assert result.tuning.groupby("horizon_min").selected.sum().eq(1).all()
    assert set(result.fitted) == {15, 30, 60}
    assert result.interpretation.importance_type.eq("feature_importance").all()
    assert result.interpretation.groupby("horizon_min").value.sum().gt(0).all()


def test_hgb_trains_and_exports_permutation_importance() -> None:
    result = train_supervised(dataset(), CONTRACT, RULES, kind="hgb")
    assert len(result.predictions) == len(dataset()) * 3
    assert result.predictions.y_score.between(0, 1).all()
    assert result.tuning.groupby("horizon_min").selected.sum().eq(1).all()
    assert set(result.fitted) == {15, 30, 60}
    assert result.interpretation.importance_type.eq("permutation_importance").all()
    assert result.interpretation.groupby("horizon_min").value.sum().notna().all()


def test_ensemble_model_names_are_registered() -> None:
    from traffic_recovery.models.supervised import MODEL_NAMES

    assert MODEL_NAMES["rf"] == "random_forest"
    assert MODEL_NAMES["hgb"] == "hist_gradient_boosting"


def test_test_labels_do_not_change_ensemble_selection() -> None:
    first = train_supervised(dataset(), CONTRACT, RULES, kind="rf")
    changed = dataset()
    test = changed.split.eq("test")
    replacement = (1 - changed.loc[test, "label_15m"].astype(int)).astype("Int8")
    changed.loc[test, ["label_15m", "label_30m", "label_60m"]] = pd.concat(
        [replacement, replacement, replacement], axis=1
    ).to_numpy()
    second = train_supervised(changed, CONTRACT, RULES, kind="rf")
    selected_columns = ["horizon_min", "parameters", "validation_log_loss", "selected"]
    pd.testing.assert_frame_equal(
        first.tuning[selected_columns], second.tuning[selected_columns]
    )
