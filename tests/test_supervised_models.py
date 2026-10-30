"""SYNTHETIC supervised-model tests; values are not research results."""
from pathlib import Path

import pandas as pd

from traffic_recovery.models.contract import ExperimentContract
from traffic_recovery.models.evaluation import evaluate_predictions
from traffic_recovery.models.supervised import (
    SupervisedRules,
    run_supervised_files,
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
        "event_id": [f"SYNTHETIC-SUPERVISED-{index}" for index in range(len(times))],
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


def test_logistic_tunes_each_horizon_and_exports_odds_ratios() -> None:
    result = train_supervised(dataset(), CONTRACT, RULES, kind="logistic")
    assert len(result.predictions) == len(dataset()) * 3
    assert result.predictions.y_score.between(0, 1).all()
    assert result.tuning.groupby("horizon_min").selected.sum().eq(1).all()
    assert set(result.fitted) == {15, 30, 60}
    assert result.interpretation.importance_type.eq("coefficient").all()
    assert result.interpretation.odds_ratio.notna().all()
    assert all(summary["refit_after_selection"] is False for summary in result.summaries)


def test_test_labels_do_not_change_selection_or_scores() -> None:
    first = train_supervised(dataset(), CONTRACT, RULES, kind="logistic")
    changed = dataset()
    test = changed.split.eq("test")
    replacement = (1 - changed.loc[test, "label_15m"].astype(int)).astype("Int8")
    changed.loc[test, ["label_15m", "label_30m", "label_60m"]] = pd.concat(
        [replacement, replacement, replacement], axis=1
    ).to_numpy()
    second = train_supervised(changed, CONTRACT, RULES, kind="logistic")
    selected_columns = ["horizon_min", "parameters", "validation_log_loss", "selected"]
    pd.testing.assert_frame_equal(first.tuning[selected_columns], second.tuning[selected_columns])
    score_columns = ["event_id", "horizon_min", "y_score", "y_pred"]
    pd.testing.assert_frame_equal(
        first.predictions.loc[first.predictions.split.eq("test"), score_columns].reset_index(drop=True),
        second.predictions.loc[second.predictions.split.eq("test"), score_columns].reset_index(drop=True),
    )


def test_tree_exports_structure_and_feature_importance() -> None:
    frame = dataset()
    frame.loc[frame.split.eq("validation").idxmax(), "speed_kmh"] = pd.NA
    result = train_supervised(frame, CONTRACT, RULES, kind="tree")
    assert result.interpretation.importance_type.eq("feature_importance").all()
    assert result.interpretation.groupby("horizon_min").value.sum().between(0, 1).all()
    assert all(summary["tree_depth"] >= 1 for summary in result.summaries)
    assert all(summary["tree_leaves"] >= 2 for summary in result.summaries)
    assert all("|---" in summary["tree_text"] for summary in result.summaries)


def test_supervised_metrics_are_long_form() -> None:
    predictions = train_supervised(dataset(), CONTRACT, RULES, kind="logistic").predictions
    metrics = evaluate_predictions(predictions, version_column="model_version")
    assert set(metrics.metric_name) == {
        "accuracy", "precision", "recall", "f1", "balanced_accuracy",
        "roc_auc", "pr_auc", "brier_score", "log_loss",
    }
    assert metrics.n_missing_feature.eq(0).all()


def test_supervised_file_runs_write_evidence_and_tree_figures(tmp_path: Path) -> None:
    dataset_path = tmp_path / "model.parquet"
    dataset().to_parquet(dataset_path, index=False)
    for kind in ("logistic", "tree"):
        output = tmp_path / kind
        manifest = run_supervised_files(
            kind=kind, dataset_path=dataset_path, contract_path=CONTRACT_PATH,
            rules_path=RULES_PATH, feature_groups=None,
            predictions_path=output / "predictions.parquet",
            metrics_path=output / "metrics.csv", tuning_path=output / "tuning.csv",
            interpretation_path=output / "interpretation.csv",
            manifest_path=output / "manifest.json",
            figure_dir=output / "figures" if kind == "tree" else None,
        )
        assert manifest["model_kind"] == kind
        assert manifest["run"]["seed"] == 42
        assert manifest["run"]["split_boundaries"]["test_start"]
        assert (output / "predictions.parquet").is_file()
        assert (output / "metrics.csv").is_file()
        assert (output / "tuning.csv").is_file()
        assert (output / "interpretation.csv").is_file()
        assert (output / "manifest.json").is_file()
        if kind == "tree":
            assert len(manifest["outputs"]["figures"]) == 3
            assert len(list((output / "figures").glob("*.png"))) == 3


def test_selected_feature_group_must_be_complete() -> None:
    frame = dataset().drop(columns="speed_ratio")
    try:
        train_supervised(frame, CONTRACT, RULES, kind="logistic")
    except ValueError as error:
        assert "incomplete" in str(error)
    else:
        raise AssertionError("Incomplete feature group should fail")
