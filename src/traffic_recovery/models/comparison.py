"""Run predeclared feature-group experiments and build an evidence-backed report."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd
import sklearn
from sklearn.tree import plot_tree

from traffic_recovery.data.http import sha256_file
from traffic_recovery.models.benchmarks import (
    BenchmarkRules,
    benchmark_predictions,
    evaluate_benchmarks,
)
from traffic_recovery.models.contract import ExperimentContract
from traffic_recovery.models.evaluation import evaluate_predictions
from traffic_recovery.models.provenance import run_metadata, start_run
from traffic_recovery.models.supervised import SupervisedRules, train_supervised


@dataclass(frozen=True)
class ComparisonRules:
    version: str
    scientific_approval: str
    models: tuple[str, ...]
    feature_sets: tuple[tuple[str, tuple[str, ...]], ...]
    reference_feature_set: str
    comparison_split: str
    metrics: dict[str, str]

    @classmethod
    def from_path(cls, path: Path) -> "ComparisonRules":
        payload = json.loads(path.read_text(encoding="utf-8"))
        feature_sets = tuple(
            (str(item["name"]), tuple(str(group) for group in item["groups"]))
            for item in payload["feature_sets"]
        )
        rules = cls(
            version=str(payload["version"]),
            scientific_approval=str(payload["scientific_approval"]),
            models=tuple(str(model) for model in payload["models"]),
            feature_sets=feature_sets,
            reference_feature_set=str(payload["reference_feature_set"]),
            comparison_split=str(payload["comparison_split"]),
            metrics={str(name): str(direction) for name, direction in payload["metrics"].items()},
        )
        names = [name for name, _ in rules.feature_sets]
        if not names or len(names) != len(set(names)):
            raise ValueError("Feature-set names must be nonempty and unique")
        for name, groups in rules.feature_sets:
            if not groups or len(groups) != len(set(groups)):
                raise ValueError(f"Feature set {name} has invalid groups")
        if rules.reference_feature_set not in names:
            raise ValueError("reference_feature_set is not configured")
        if not rules.models or not set(rules.models) <= {"logistic", "tree", "rf", "hgb"}:
            raise ValueError("models may contain only logistic, tree, rf and hgb")
        if rules.comparison_split not in {"train", "validation", "test"}:
            raise ValueError("comparison_split is invalid")
        if not rules.metrics or not set(rules.metrics.values()) <= {"higher", "lower"}:
            raise ValueError("Every metric direction must be higher or lower")
        return rules


def compare_to_reference(metrics: pd.DataFrame, rules: ComparisonRules) -> pd.DataFrame:
    """Return signed raw deltas and direction-normalised improvements."""
    selected = metrics.loc[
        metrics.split.eq(rules.comparison_split)
        & metrics.metric_name.isin(rules.metrics)
        & metrics.model.isin([
            "logistic_regression", "decision_tree",
            "random_forest", "hist_gradient_boosting",
        ])
    ].copy()
    reference = selected.loc[
        selected.feature_set.eq(rules.reference_feature_set),
        ["model", "horizon_min", "metric_name", "metric_value", "n_rows", "n_events"],
    ].rename(columns={
        "metric_value": "reference_value", "n_rows": "reference_n_rows",
        "n_events": "reference_n_events",
    })
    result = selected.merge(
        reference, on=["model", "horizon_min", "metric_name"],
        how="left", validate="many_to_one",
    )
    if result.reference_value.isna().any() and result.metric_value.notna().any():
        # Undefined reference metrics are allowed only where the compared metric is
        # also undefined; otherwise a comparison would silently lose its baseline.
        bad = result.reference_value.isna() & result.metric_value.notna()
        if bad.any():
            raise ValueError("A defined metric has no defined local reference")
    result["raw_delta"] = result.metric_value - result.reference_value
    direction = result.metric_name.map(rules.metrics)
    result["improvement_vs_reference"] = result.raw_delta.where(
        direction.eq("higher"), -result.raw_delta
    )
    result["metric_direction"] = direction
    result.insert(0, "comparison_version", rules.version)
    columns = [
        "comparison_version", "split", "model", "horizon_min", "feature_set",
        "metric_name", "metric_direction", "metric_value", "reference_value",
        "raw_delta", "improvement_vs_reference", "n_rows", "reference_n_rows",
        "n_events", "reference_n_events", "undefined_reason",
    ]
    return result[columns].sort_values(
        ["model", "horizon_min", "metric_name", "feature_set"]
    ).reset_index(drop=True)


def _format_value(value: object) -> str:
    return "NA" if pd.isna(value) else f"{float(value):.4f}"


def render_report(
    *, contract: ExperimentContract, supervised_status: str,
    rules: ComparisonRules, metrics: pd.DataFrame, comparisons: pd.DataFrame,
    dataset_path: Path, dataset_sha256: str,
) -> str:
    """Render a compact report that preserves pending-approval caveats."""
    approvals = [contract.status, supervised_status, rules.scientific_approval]
    approved = all(status == "approved" for status in approvals)
    status = "APPROVED RESEARCH RUN" if approved else "EXPLORATORY — NOT APPROVED AS FINAL RESULTS"
    test = metrics.loc[
        metrics.split.eq(rules.comparison_split)
        & metrics.metric_name.isin(rules.metrics)
    ].sort_values(["model", "horizon_min", "feature_set", "metric_name"])
    lines = [
        "# Feature-group model comparison", "", f"**Status: {status}**", "",
        "This report is generated from fingerprinted model outputs. Synthetic or",
        "pending-approval measurements must not be presented as empirical findings.", "",
        "## Evidence", "", f"- Dataset: `{dataset_path.as_posix()}`",
        f"- Dataset SHA-256: `{dataset_sha256}`",
        f"- Contract status: `{contract.status}`",
        f"- Supervised-model status: `{supervised_status}`",
        f"- Comparison status: `{rules.scientific_approval}`", "",
        "## Test metrics", "",
        "| model | horizon | feature set | metric | value | n | undefined reason |",
        "|---|---:|---|---|---:|---:|---|",
    ]
    for row in test.itertuples(index=False):
        reason = "" if pd.isna(row.undefined_reason) else str(row.undefined_reason)
        lines.append(
            f"| {row.model} | {row.horizon_min} | {row.feature_set} | "
            f"{row.metric_name} | {_format_value(row.metric_value)} | {row.n_rows} | {reason} |"
        )
    lines.extend([
        "", "## Change from local features", "",
        "Positive improvement means better performance after accounting for whether",
        "the metric is higher-is-better or lower-is-better.", "",
        "| model | horizon | feature set | metric | improvement |",
        "|---|---:|---|---|---:|",
    ])
    for row in comparisons.loc[
        ~comparisons.feature_set.eq(rules.reference_feature_set)
    ].itertuples(index=False):
        lines.append(
            f"| {row.model} | {row.horizon_min} | {row.feature_set} | "
            f"{row.metric_name} | {_format_value(row.improvement_vs_reference)} |"
        )
    lines.extend([
        "", "## Interpretation limits", "",
        "- Model selection used validation log loss; the test split was evaluated once.",
        "- A metric delta is descriptive and is not a confidence interval or significance test.",
        "- Missing context is imputed inside the train-fitted pipeline and missingness counts remain in metrics.",
        "- Every compared model uses the same cohort with observed event-time speed_ratio.",
        "- Final claims require team approval of the cohort, labels, spatial mapping and source coverage.", "",
    ])
    return "\n".join(lines)


def _verify_dataset_manifest(dataset_path: Path, manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("manifest_version") != "model-dataset-manifest-v1":
        raise ValueError("Unsupported model-dataset manifest")
    expected = payload.get("output", {}).get("sha256")
    actual = sha256_file(dataset_path)
    if expected != actual:
        raise ValueError("Dataset hash does not match its model-dataset manifest")
    return payload


def run_comparison_files(
    *, dataset_path: Path, dataset_manifest_path: Path, contract_path: Path,
    benchmark_rules_path: Path, supervised_rules_path: Path,
    comparison_rules_path: Path, output_dir: Path,
) -> dict[str, Any]:
    """Run all configured experiments without overwriting existing evidence."""
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite comparison directory: {output_dir}")
    started_at, started_counter = start_run()
    dataset_manifest = _verify_dataset_manifest(dataset_path, dataset_manifest_path)
    contract = ExperimentContract.from_path(contract_path)
    benchmark_rules = BenchmarkRules.from_path(benchmark_rules_path)
    supervised_rules = SupervisedRules.from_path(supervised_rules_path)
    comparison_rules = ComparisonRules.from_path(comparison_rules_path)
    supervised_payload = json.loads(supervised_rules_path.read_text(encoding="utf-8"))
    frame = pd.read_parquet(dataset_path)
    if "speed_ratio" not in frame:
        raise ValueError("Comparison cohort requires speed_ratio for paired benchmarks")
    ratio = pd.to_numeric(frame.speed_ratio, errors="coerce")
    original_rows = len(frame)
    excluded_by_split = {
        split: int((frame.split.eq(split) & ratio.isna()).sum())
        for split in ("train", "validation", "test")
    }
    frame = frame.loc[ratio.notna()].copy()
    cohort = {
        "policy": "known-label rows with observed speed_ratio for every compared model",
        "input_rows": original_rows,
        "retained_rows": len(frame),
        "excluded_missing_speed_ratio_by_split": excluded_by_split,
    }

    benchmark_prediction = benchmark_predictions(frame, contract, benchmark_rules)
    metric_frames = [evaluate_benchmarks(benchmark_prediction)]
    prediction_frames = [benchmark_prediction]
    tuning_frames: list[pd.DataFrame] = []
    interpretation_frames: list[pd.DataFrame] = []
    summaries: list[dict[str, object]] = []
    fitted_trees: list[tuple[str, int, Any]] = []
    for feature_name, groups in comparison_rules.feature_sets:
        for kind in comparison_rules.models:
            result = train_supervised(
                frame, contract, supervised_rules, kind=kind, feature_groups=groups
            )
            result.predictions["feature_set"] = feature_name
            result.tuning["feature_set"] = feature_name
            result.interpretation["feature_set"] = feature_name
            prediction_frames.append(result.predictions)
            metric_frames.append(evaluate_predictions(
                result.predictions, version_column="model_version"
            ))
            tuning_frames.append(result.tuning)
            interpretation_frames.append(result.interpretation)
            summaries.extend({
                "feature_set": feature_name, "model_kind": kind, **summary
            } for summary in result.summaries)
            if kind == "tree":
                fitted_trees.extend(
                    (feature_name, horizon, pipeline)
                    for horizon, pipeline in result.fitted.items()
                )

    predictions = pd.concat(prediction_frames, ignore_index=True, sort=False)
    metrics = pd.concat(metric_frames, ignore_index=True, sort=False)
    tuning = pd.concat(tuning_frames, ignore_index=True)
    interpretation = pd.concat(interpretation_frames, ignore_index=True)
    comparisons = compare_to_reference(metrics, comparison_rules)
    dataset_hash = sha256_file(dataset_path)
    report = render_report(
        contract=contract,
        supervised_status=str(supervised_payload.get("scientific_approval", "unknown")),
        rules=comparison_rules, metrics=metrics, comparisons=comparisons,
        dataset_path=dataset_path, dataset_sha256=dataset_hash,
    )

    output_dir.mkdir(parents=True)
    paths = {
        "predictions": output_dir / "predictions.parquet",
        "metrics": output_dir / "metrics.csv",
        "comparisons": output_dir / "feature-group-comparisons.csv",
        "tuning": output_dir / "tuning.csv",
        "interpretation": output_dir / "interpretation.csv",
        "report": output_dir / "report.md",
    }
    predictions.to_parquet(paths["predictions"], index=False)
    metrics.to_csv(paths["metrics"], index=False)
    comparisons.to_csv(paths["comparisons"], index=False)
    tuning.to_csv(paths["tuning"], index=False)
    interpretation.to_csv(paths["interpretation"], index=False)
    paths["report"].write_text(report, encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    figure_dir = output_dir / "tree-figures"
    figure_dir.mkdir()
    figure_entries = []
    for feature_set, horizon, pipeline in fitted_trees:
        path = figure_dir / f"{feature_set.replace('+', '_')}-{horizon}m.png"
        names = pipeline.named_steps["preprocess"].get_feature_names_out()
        figure, axis = plt.subplots(figsize=(18, 9))
        plot_tree(
            pipeline.named_steps["classifier"], feature_names=list(names),
            class_names=["not within", "within"], filled=True, rounded=True,
            proportion=True, ax=axis,
        )
        figure.tight_layout()
        figure.savefig(path, dpi=150)
        plt.close(figure)
        figure_entries.append({"path": path.as_posix(), "sha256": sha256_file(path)})

    manifest_path = output_dir / "manifest.json"
    manifest = {
        "manifest_version": "feature-group-comparison-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "comparison_version": comparison_rules.version,
        "scientific_approval": comparison_rules.scientific_approval,
        "dataset": {"path": dataset_path.as_posix(), "sha256": dataset_hash},
        "dataset_manifest": {
            "path": dataset_manifest_path.as_posix(),
            "sha256": sha256_file(dataset_manifest_path),
            "validation": dataset_manifest.get("validation"),
        },
        "configs": {
            name: {"path": path.as_posix(), "sha256": sha256_file(path)}
            for name, path in {
                "contract": contract_path, "benchmarks": benchmark_rules_path,
                "supervised": supervised_rules_path, "comparison": comparison_rules_path,
            }.items()
        },
        "outputs": {
            name: {"path": path.as_posix(), "sha256": sha256_file(path)}
            for name, path in paths.items()
        } | {"tree_figures": figure_entries},
        "rows": {
            "predictions": len(predictions), "metrics": len(metrics),
            "comparisons": len(comparisons), "tuning": len(tuning),
            "interpretation": len(interpretation),
        },
        "comparison_cohort": cohort,
        "summaries": summaries,
        "run": run_metadata(
            started_at=started_at, started_counter=started_counter,
            contract=contract, seed=supervised_rules.seed,
        ),
        "software": {"pandas": pd.__version__, "scikit_learn": sklearn.__version__},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/experiment_contract.json"))
    parser.add_argument("--benchmark-rules", type=Path, default=Path("configs/benchmarks.json"))
    parser.add_argument("--supervised-rules", type=Path, default=Path("configs/supervised_models.json"))
    parser.add_argument("--comparison-rules", type=Path, default=Path("configs/feature_group_comparison.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_comparison_files(
        dataset_path=args.dataset, dataset_manifest_path=args.dataset_manifest,
        contract_path=args.contract, benchmark_rules_path=args.benchmark_rules,
        supervised_rules_path=args.supervised_rules,
        comparison_rules_path=args.comparison_rules, output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
