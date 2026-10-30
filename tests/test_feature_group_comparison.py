"""SYNTHETIC feature-group comparison tests; values are not research results."""
import json
from pathlib import Path

import pandas as pd

from traffic_recovery.data.http import sha256_file
from traffic_recovery.models.comparison import (
    ComparisonRules,
    compare_to_reference,
    run_comparison_files,
)
from traffic_recovery.models.contract import ExperimentContract


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "configs" / "experiment_contract.json"
BENCHMARK_PATH = ROOT / "configs" / "benchmarks.json"
COMPARISON_PATH = ROOT / "configs" / "feature_group_comparison.json"
CONTRACT = ExperimentContract.from_path(CONTRACT_PATH)


def dataset() -> pd.DataFrame:
    timestamps = [
        *(f"2026-10-15T{hour:02d}:00:00+08:00" for hour in range(8, 16)),
        *(f"2026-10-17T{hour:02d}:00:00+08:00" for hour in range(8, 14)),
        *(f"2026-10-19T{hour:02d}:00:00+08:00" for hour in range(8, 14)),
    ]
    prediction = pd.to_datetime(timestamps, utc=True).tz_convert("Asia/Hong_Kong")
    labels = pd.Series(([0, 1] * 4) + ([0, 1] * 3) + ([0, 1] * 3), dtype="Int8")
    ratio = [0.3 if value == 0 else 0.75 for value in labels]
    frame = pd.DataFrame({
        "event_id": [f"SYNTHETIC-COMPARISON-{index}" for index in range(len(labels))],
        "prediction_time": prediction,
        "split": pd.Series(["train"] * 8 + ["validation"] * 6 + ["test"] * 6),
        "label_15m": labels, "label_30m": labels, "label_60m": labels,
        "speed_kmh": [80 * value for value in ratio], "speed_ratio": ratio,
        "baseline_kmh": 80.0, "valid_slots": 4,
        "onset_observed_minutes": list(range(len(labels))),
        "feature_max_available_at": prediction - pd.Timedelta(minutes=1),
    })
    calendar = {
        "hour_sin": 0.1, "hour_cos": 0.9, "dow_sin": 0.2, "dow_cos": 0.8,
        "is_weekend": 0, "is_public_holiday": 0, "is_day_before_holiday": 0,
        "is_day_after_holiday": 0, "holiday_count": 0,
        "calendar_source_observed": 1,
        "calendar_max_source_available_at": prediction - pd.Timedelta(days=1),
    }
    return frame.assign(**calendar)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_repository_comparison_rules_cover_all_incremental_groups() -> None:
    rules = ComparisonRules.from_path(COMPARISON_PATH)
    names = {name for name, _ in rules.feature_sets}
    assert {
        "local", "local+calendar", "local+weather", "local+incident",
        "local+major_event", "local+spatial", "local+all_context", "local+all",
    } == names
    assert rules.reference_feature_set == "local"


def test_comparison_delta_respects_metric_direction() -> None:
    rules = ComparisonRules(
        version="test", scientific_approval="pending", models=("logistic",),
        feature_sets=(("local", ("local",)), ("local+calendar", ("local", "calendar"))),
        reference_feature_set="local", comparison_split="test",
        metrics={"roc_auc": "higher", "log_loss": "lower"},
    )
    rows = []
    for feature, auc, loss in (("local", 0.7, 0.6), ("local+calendar", 0.8, 0.5)):
        for metric, value in (("roc_auc", auc), ("log_loss", loss)):
            rows.append({
                "split": "test", "model": "logistic_regression", "horizon_min": 15,
                "feature_set": feature, "metric_name": metric, "metric_value": value,
                "n_rows": 10, "n_events": 10, "undefined_reason": None,
            })
    comparison = compare_to_reference(pd.DataFrame(rows), rules)
    added = comparison.loc[comparison.feature_set.eq("local+calendar")]
    assert added.improvement_vs_reference.round(6).eq(0.1).all()


def test_end_to_end_comparison_writes_report_and_evidence(tmp_path: Path) -> None:
    dataset_path = tmp_path / "model.parquet"
    frame = dataset()
    excluded_event = frame.loc[frame.split.eq("test"), "event_id"].iloc[-1]
    frame.loc[frame.event_id.eq(excluded_event), "speed_ratio"] = pd.NA
    frame.to_parquet(dataset_path, index=False)
    dataset_manifest_path = tmp_path / "model-manifest.json"
    _write_json(dataset_manifest_path, {
        "manifest_version": "model-dataset-manifest-v1",
        "validation": {"scientific_approval": "pending_test"},
        "output": {"path": dataset_path.as_posix(), "sha256": sha256_file(dataset_path)},
    })
    supervised_path = tmp_path / "supervised.json"
    _write_json(supervised_path, {
        "version": "synthetic-supervised-v1",
        "scientific_approval": "pending_synthetic_test",
        "seed": 42, "selection_metric": "validation_log_loss",
        "decision_threshold": 0.5, "refit_after_selection": False,
        "default_feature_groups": ["local"],
        "logistic_regression": {
            "solver": "liblinear", "max_iter": 500, "C": [1.0],
            "class_weight": [None],
        },
        "decision_tree": {
            "criterion": "gini", "max_depth": [2], "min_samples_leaf": [1],
            "class_weight": [None],
        },
    })
    comparison_path = tmp_path / "comparison.json"
    _write_json(comparison_path, {
        "version": "synthetic-comparison-v1",
        "scientific_approval": "pending_synthetic_test",
        "models": ["logistic", "tree"], "reference_feature_set": "local",
        "feature_sets": [
            {"name": "local", "groups": ["local"]},
            {"name": "local+calendar", "groups": ["local", "calendar"]},
        ],
        "comparison_split": "test",
        "metrics": {"roc_auc": "higher", "log_loss": "lower"},
    })
    output = tmp_path / "comparison-output"
    manifest = run_comparison_files(
        dataset_path=dataset_path, dataset_manifest_path=dataset_manifest_path,
        contract_path=CONTRACT_PATH, benchmark_rules_path=BENCHMARK_PATH,
        supervised_rules_path=supervised_path, comparison_rules_path=comparison_path,
        output_dir=output,
    )
    assert manifest["rows"]["comparisons"] == 2 * 3 * 2 * 2
    assert len(manifest["outputs"]["tree_figures"]) == 6
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "EXPLORATORY — NOT APPROVED AS FINAL RESULTS" in report
    assert "Synthetic or" in report
    predictions = pd.read_parquet(output / "predictions.parquet")
    assert excluded_event not in set(predictions.event_id)
    assert manifest["comparison_cohort"]["retained_rows"] == len(frame) - 1
    excluded = manifest["comparison_cohort"]["excluded_missing_speed_ratio_by_split"]
    assert excluded["test"] == 1
    assert manifest["run"]["seed"] == 42
    assert (output / "feature-group-comparisons.csv").is_file()
    assert (output / "manifest.json").is_file()


def test_dataset_manifest_hash_mismatch_stops_before_output(tmp_path: Path) -> None:
    dataset_path = tmp_path / "model.parquet"
    dataset().to_parquet(dataset_path, index=False)
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, {
        "manifest_version": "model-dataset-manifest-v1",
        "output": {"sha256": "not-the-real-hash"},
    })
    try:
        run_comparison_files(
            dataset_path=dataset_path, dataset_manifest_path=manifest_path,
            contract_path=CONTRACT_PATH, benchmark_rules_path=BENCHMARK_PATH,
            supervised_rules_path=ROOT / "configs" / "supervised_models.json",
            comparison_rules_path=COMPARISON_PATH, output_dir=tmp_path / "output",
        )
    except ValueError as error:
        assert "hash" in str(error)
    else:
        raise AssertionError("A mismatched dataset hash should fail")
