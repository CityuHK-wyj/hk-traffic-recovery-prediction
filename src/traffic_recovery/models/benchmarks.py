"""Training-only constant and simple-rule recovery benchmarks."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
import sklearn

from traffic_recovery.data.http import sha256_file
from traffic_recovery.models.contract import ExperimentContract, validate_event_table
from traffic_recovery.models.evaluation import evaluate_predictions
from traffic_recovery.models.provenance import run_metadata, start_run


@dataclass(frozen=True)
class BenchmarkRules:
    """Predeclared thresholds; no value is selected from test outcomes."""

    version: str
    decision_threshold: float
    speed_ratio_threshold: float

    @classmethod
    def from_path(cls, path: Path) -> "BenchmarkRules":
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = cls(
            version=str(payload["version"]),
            decision_threshold=float(payload["decision_threshold"]),
            speed_ratio_threshold=float(payload["speed_ratio_rule"]["positive_at_or_above"]),
        )
        if not 0 <= result.decision_threshold <= 1:
            raise ValueError("decision_threshold must be in [0, 1]")
        if not 0 <= result.speed_ratio_threshold <= 1:
            raise ValueError("speed_ratio threshold must be in [0, 1]")
        return result


def benchmark_predictions(
    frame: pd.DataFrame,
    contract: ExperimentContract,
    rules: BenchmarkRules,
    *,
    horizons: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """Fit constant baselines on train only and score identical eligible rows."""
    validate_event_table(frame, contract)
    selected_horizons = horizons or contract.horizons
    if not set(selected_horizons) <= set(contract.horizons):
        raise ValueError("Requested horizon is outside the experiment contract")
    if "speed_ratio" not in frame:
        raise ValueError("speed_ratio is required for the predeclared rule benchmark")
    ratio = pd.to_numeric(frame.speed_ratio, errors="coerce")
    if ((ratio.dropna() < 0) | (ratio.dropna() > 1)).any():
        raise ValueError("speed_ratio benchmark requires values in [0, 1]")

    rows: list[dict[str, object]] = []
    allowed_splits = frame.split.isin(["train", "validation", "test"])
    for horizon in selected_horizons:
        label_name = f"label_{horizon}m"
        eligible = allowed_splits & frame[label_name].notna() & ratio.notna()
        train = eligible & frame.split.eq("train")
        if not train.any():
            raise ValueError(f"No eligible training labels for {horizon} minutes")
        y_train = frame.loc[train, label_name].astype(int)
        prevalence = float(y_train.mean())
        majority = int(prevalence > 0.5)  # deterministic negative class on a tie
        censored_by_split = {
            split: int((frame.split.eq(split) & frame[label_name].isna()).sum())
            for split in ("train", "validation", "test")
        }
        missing_ratio_by_split = {
            split: int((frame.split.eq(split) & frame[label_name].notna() & ratio.isna()).sum())
            for split in ("train", "validation", "test")
        }
        for index in frame.index[eligible]:
            common = {
                "event_id": frame.at[index, "event_id"],
                "prediction_time": frame.at[index, "prediction_time"],
                "split": str(frame.at[index, "split"]),
                "horizon_min": horizon,
                "y_true": int(frame.at[index, label_name]),
                "fit_train_n": int(train.sum()),
                "fit_train_positive": int(y_train.sum()),
                "fit_train_prevalence": prevalence,
                "n_censored_in_split": censored_by_split[str(frame.at[index, "split"])],
                "n_missing_rule_feature_in_split": missing_ratio_by_split[str(frame.at[index, "split"])],
                "benchmark_version": rules.version,
            }
            rows.extend([
                {**common, "model": "majority_class", "feature_set": "none",
                 "y_score": float(majority), "y_pred": majority,
                 "score_kind": "probability", "threshold": pd.NA},
                {**common, "model": "train_prevalence", "feature_set": "none",
                 "y_score": prevalence,
                 "y_pred": int(prevalence >= rules.decision_threshold),
                 "score_kind": "probability", "threshold": rules.decision_threshold},
                {**common, "model": "speed_ratio_rule", "feature_set": "local_speed_ratio",
                 "y_score": float(ratio.at[index]),
                 "y_pred": int(ratio.at[index] >= rules.speed_ratio_threshold),
                 "score_kind": "rule_score", "threshold": rules.speed_ratio_threshold},
            ])
    return pd.DataFrame(rows)


def evaluate_benchmarks(predictions: pd.DataFrame) -> pd.DataFrame:
    """Return long-form metrics with explicit reasons for undefined values."""
    return evaluate_predictions(predictions, version_column="benchmark_version")


def run_benchmark_files(
    *, dataset_path: Path, contract_path: Path, rules_path: Path,
    predictions_path: Path, metrics_path: Path, manifest_path: Path,
) -> dict[str, object]:
    """Run all benchmark horizons and write immutable, fingerprinted outputs."""
    for target in (predictions_path, metrics_path, manifest_path):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing artifact: {target}")
    started_at, started_counter = start_run()
    contract = ExperimentContract.from_path(contract_path)
    rules = BenchmarkRules.from_path(rules_path)
    frame = pd.read_parquet(dataset_path)
    predictions = benchmark_predictions(frame, contract, rules)
    metrics = evaluate_benchmarks(predictions)
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(predictions_path, index=False)
    metrics.to_csv(metrics_path, index=False)
    manifest = {
        "manifest_version": "benchmark-run-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_version": rules.version,
        "dataset": {"path": dataset_path.as_posix(), "sha256": sha256_file(dataset_path)},
        "contract": {"path": contract_path.as_posix(), "sha256": sha256_file(contract_path)},
        "rules": {"path": rules_path.as_posix(), "sha256": sha256_file(rules_path)},
        "predictions": {"path": predictions_path.as_posix(), "sha256": sha256_file(predictions_path),
                        "rows": len(predictions)},
        "metrics": {"path": metrics_path.as_posix(), "sha256": sha256_file(metrics_path),
                    "rows": len(metrics)},
        "run": run_metadata(
            started_at=started_at, started_counter=started_counter,
            contract=contract, seed=None,
        ),
        "software": {"pandas": pd.__version__, "scikit_learn": sklearn.__version__},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/experiment_contract.json"))
    parser.add_argument("--rules", type=Path, default=Path("configs/benchmarks.json"))
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    run_benchmark_files(
        dataset_path=args.dataset, contract_path=args.contract, rules_path=args.rules,
        predictions_path=args.predictions, metrics_path=args.metrics,
        manifest_path=args.manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
