"""SYNTHETIC benchmark tests; values are not research results."""
from pathlib import Path

import pandas as pd

from traffic_recovery.models.benchmarks import (
    BenchmarkRules,
    benchmark_predictions,
    evaluate_benchmarks,
    run_benchmark_files,
)
from traffic_recovery.models.contract import ExperimentContract


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "configs" / "experiment_contract.json"
RULES_PATH = ROOT / "configs" / "benchmarks.json"
CONTRACT = ExperimentContract.from_path(CONTRACT_PATH)
RULES = BenchmarkRules.from_path(RULES_PATH)


def dataset() -> pd.DataFrame:
    prediction = pd.to_datetime([
        "2026-10-15T08:00:00+08:00", "2026-10-15T09:00:00+08:00",
        "2026-10-15T10:00:00+08:00", "2026-10-15T11:00:00+08:00",
        "2026-10-17T10:00:00+08:00", "2026-10-17T11:00:00+08:00",
        "2026-10-19T10:00:00+08:00", "2026-10-19T11:00:00+08:00",
    ], utc=True).tz_convert("Asia/Hong_Kong")
    labels = pd.Series([0, 0, 0, 1, 0, 1, 0, 1], dtype="Int8")
    return pd.DataFrame({
        "event_id": [f"SYNTHETIC-{index}" for index in range(8)],
        "prediction_time": prediction,
        "split": pd.Series(["train"] * 4 + ["validation"] * 2 + ["test"] * 2,
                           dtype="string"),
        "label_15m": labels,
        "label_30m": labels,
        "label_60m": labels,
        "speed_ratio": [0.2, 0.3, 0.45, 0.5, 0.35, 0.45, 0.25, 0.5],
        "feature_max_available_at": prediction - pd.Timedelta(minutes=1),
        "dataset_version": [CONTRACT.version] * 8,
    })


def test_benchmarks_fit_constants_from_train_only() -> None:
    predictions = benchmark_predictions(dataset(), CONTRACT, RULES, horizons=(15,))
    assert len(predictions) == 8 * 3
    prevalence = predictions.loc[predictions.model.eq("train_prevalence")]
    majority = predictions.loc[predictions.model.eq("majority_class")]
    assert prevalence.y_score.eq(0.25).all()
    assert majority.y_pred.eq(0).all()
    assert predictions.fit_train_n.eq(4).all()


def test_test_labels_never_change_fitted_benchmark_scores() -> None:
    first = benchmark_predictions(dataset(), CONTRACT, RULES, horizons=(15,))
    changed = dataset()
    changed.loc[
        changed.split.eq("test"), ["label_15m", "label_30m", "label_60m"]
    ] = [[1, 1, 1], [0, 0, 0]]
    second = benchmark_predictions(changed, CONTRACT, RULES, horizons=(15,))
    columns = ["event_id", "model", "y_score", "y_pred", "fit_train_prevalence"]
    pd.testing.assert_frame_equal(first[columns], second[columns])


def test_metrics_are_long_form_and_rule_scores_are_not_probabilities() -> None:
    predictions = benchmark_predictions(dataset(), CONTRACT, RULES)
    metrics = evaluate_benchmarks(predictions)
    assert set(metrics.metric_name) == {
        "accuracy", "precision", "recall", "f1", "balanced_accuracy",
        "roc_auc", "pr_auc", "brier_score", "log_loss",
    }
    rule_probability_metrics = metrics.loc[
        metrics.model.eq("speed_ratio_rule")
        & metrics.metric_name.isin(["brier_score", "log_loss"])
    ]
    assert rule_probability_metrics.metric_value.isna().all()
    assert rule_probability_metrics.undefined_reason.eq("score_is_not_probability").all()
    assert metrics.loc[metrics.metric_name.eq("roc_auc"), "metric_value"].notna().all()


def test_censored_and_missing_rule_features_are_explicit_exclusions() -> None:
    frame = dataset()
    frame.loc[6, "label_15m"] = pd.NA
    frame.loc[7, "speed_ratio"] = pd.NA
    predictions = benchmark_predictions(frame, CONTRACT, RULES, horizons=(15,))
    test_predictions = predictions.loc[predictions.split.eq("test")]
    assert test_predictions.empty
    # Counts remain visible in other split-independent model metadata only when a
    # split has an eligible row, so add one eligible test row and retain exclusions.
    frame.loc[6, "label_15m"] = 0
    predictions = benchmark_predictions(frame, CONTRACT, RULES, horizons=(15,))
    test_predictions = predictions.loc[predictions.split.eq("test")]
    assert test_predictions.n_missing_rule_feature_in_split.eq(1).all()


def test_benchmark_files_write_predictions_metrics_and_manifest(tmp_path: Path) -> None:
    dataset_path = tmp_path / "model.parquet"
    predictions_path = tmp_path / "predictions.parquet"
    metrics_path = tmp_path / "metrics.csv"
    manifest_path = tmp_path / "manifest.json"
    dataset().to_parquet(dataset_path, index=False)
    manifest = run_benchmark_files(
        dataset_path=dataset_path, contract_path=CONTRACT_PATH, rules_path=RULES_PATH,
        predictions_path=predictions_path, metrics_path=metrics_path,
        manifest_path=manifest_path,
    )
    assert manifest["predictions"]["rows"] == 72
    assert manifest["metrics"]["rows"] == 243
    assert manifest["run"]["run_id"]
    assert manifest["run"]["lock"]["sha256"]
    assert predictions_path.is_file() and metrics_path.is_file() and manifest_path.is_file()
