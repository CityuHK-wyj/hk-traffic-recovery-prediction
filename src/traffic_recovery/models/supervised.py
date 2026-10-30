"""Leakage-safe logistic regression and decision-tree model selection."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import sklearn
from pandas.api.types import is_numeric_dtype
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text, plot_tree

from traffic_recovery.data.http import sha256_file
from traffic_recovery.models.contract import ExperimentContract, validate_event_table
from traffic_recovery.models.evaluation import evaluate_predictions
from traffic_recovery.models.provenance import run_metadata, start_run


MODEL_NAMES = {"logistic": "logistic_regression", "tree": "decision_tree"}


@dataclass(frozen=True)
class SupervisedRules:
    version: str
    seed: int
    selection_metric: str
    decision_threshold: float
    refit_after_selection: bool
    default_feature_groups: tuple[str, ...]
    logistic: dict[str, Any]
    tree: dict[str, Any]

    @classmethod
    def from_path(cls, path: Path) -> "SupervisedRules":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rules = cls(
            version=str(payload["version"]), seed=int(payload["seed"]),
            selection_metric=str(payload["selection_metric"]),
            decision_threshold=float(payload["decision_threshold"]),
            refit_after_selection=bool(payload["refit_after_selection"]),
            default_feature_groups=tuple(payload["default_feature_groups"]),
            logistic=dict(payload["logistic_regression"]),
            tree=dict(payload["decision_tree"]),
        )
        if rules.selection_metric != "validation_log_loss":
            raise ValueError("Only validation_log_loss selection is implemented")
        if rules.refit_after_selection:
            raise ValueError("This contract requires preprocessing fitted on train only")
        if not 0 <= rules.decision_threshold <= 1:
            raise ValueError("decision_threshold must be in [0, 1]")
        return rules


@dataclass
class SupervisedResult:
    predictions: pd.DataFrame
    tuning: pd.DataFrame
    interpretation: pd.DataFrame
    summaries: list[dict[str, object]]
    fitted: dict[int, Pipeline]


def resolve_features(
    frame: pd.DataFrame, contract: ExperimentContract, groups: tuple[str, ...]
) -> tuple[str, ...]:
    if not groups or len(set(groups)) != len(groups):
        raise ValueError("Feature groups must be nonempty and unique")
    unknown = set(groups) - set(contract.feature_groups)
    if unknown:
        raise ValueError(f"Unknown feature groups: {sorted(unknown)}")
    features = tuple(column for group in groups for column in contract.feature_groups[group])
    missing = set(features) - set(frame.columns)
    if missing:
        raise ValueError(f"Selected feature groups are incomplete: {sorted(missing)}")
    return features


def _preprocessor(frame: pd.DataFrame, *, scale: bool) -> ColumnTransformer:
    numeric = [column for column in frame if is_numeric_dtype(frame[column].dtype)]
    categorical = [column for column in frame if column not in numeric]
    transformers: list[tuple[str, Pipeline, list[str]]] = []
    if numeric:
        numeric_steps: list[tuple[str, object]] = [
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True))
        ]
        if scale:
            numeric_steps.append(("scale", StandardScaler()))
        transformers.append(("numeric", Pipeline(numeric_steps), numeric))
    if categorical:
        transformers.append(("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
            ("encode", OneHotEncoder(handle_unknown="ignore")),
        ]), categorical))
    if not transformers:
        raise ValueError("At least one feature is required")
    return ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=True)


def _candidates(kind: str, rules: SupervisedRules) -> list[dict[str, object]]:
    if kind == "logistic":
        return [
            {"C": c, "class_weight": weight}
            for c, weight in itertools.product(rules.logistic["C"], rules.logistic["class_weight"])
        ]
    if kind == "tree":
        return [
            {"max_depth": depth, "min_samples_leaf": leaf, "class_weight": weight}
            for depth, leaf, weight in itertools.product(
                rules.tree["max_depth"], rules.tree["min_samples_leaf"],
                rules.tree["class_weight"],
            )
        ]
    raise ValueError(f"Unknown model kind: {kind}")


def _pipeline(kind: str, x_train: pd.DataFrame, params: dict[str, object],
              rules: SupervisedRules) -> Pipeline:
    if kind == "logistic":
        estimator = LogisticRegression(
            C=float(params["C"]), class_weight=params["class_weight"],
            solver=str(rules.logistic["solver"]), max_iter=int(rules.logistic["max_iter"]),
            random_state=rules.seed,
        )
    elif kind == "tree":
        estimator = DecisionTreeClassifier(
            criterion=str(rules.tree["criterion"]), max_depth=params["max_depth"],
            min_samples_leaf=int(params["min_samples_leaf"]),
            class_weight=params["class_weight"], random_state=rules.seed,
        )
    else:
        raise ValueError(f"Unknown model kind: {kind}")
    return Pipeline([
        ("preprocess", _preprocessor(x_train, scale=kind == "logistic")),
        ("classifier", estimator),
    ])


def train_supervised(
    frame: pd.DataFrame,
    contract: ExperimentContract,
    rules: SupervisedRules,
    *,
    kind: str,
    feature_groups: tuple[str, ...] | None = None,
) -> SupervisedResult:
    """Tune on validation and evaluate the unchanged train-fitted model on test."""
    validate_event_table(frame, contract)
    groups = feature_groups or rules.default_feature_groups
    features = resolve_features(frame, contract, groups)
    feature_set = "+".join(groups)
    model_name = MODEL_NAMES.get(kind)
    if model_name is None:
        raise ValueError(f"Unknown model kind: {kind}")
    prediction_rows: list[dict[str, object]] = []
    tuning_rows: list[dict[str, object]] = []
    interpretation_rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    fitted: dict[int, Pipeline] = {}

    for horizon in contract.horizons:
        label = f"label_{horizon}m"
        masks = {
            split: frame.split.eq(split) & frame[label].notna()
            for split in ("train", "validation", "test")
        }
        if any(not mask.any() for mask in masks.values()):
            empty = [split for split, mask in masks.items() if not mask.any()]
            raise ValueError(f"Missing known-label rows for {horizon}m splits: {empty}")
        x_train = frame.loc[masks["train"], list(features)]
        y_train = frame.loc[masks["train"], label].astype(int)
        if y_train.nunique() < 2:
            raise ValueError(f"Training labels for {horizon}m contain one class")
        x_validation = frame.loc[masks["validation"], list(features)]
        y_validation = frame.loc[masks["validation"], label].astype(int)

        candidate_models: list[tuple[float, int, dict[str, object], Pipeline]] = []
        for candidate_id, params in enumerate(_candidates(kind, rules)):
            pipeline = _pipeline(kind, x_train, params, rules)
            pipeline.fit(x_train, y_train)
            probability = pipeline.predict_proba(x_validation)[:, 1]
            score = float(log_loss(y_validation, probability, labels=[0, 1]))
            candidate_models.append((score, candidate_id, params, pipeline))
            tuning_rows.append({
                "model_version": rules.version, "model": model_name,
                "feature_set": feature_set, "horizon_min": horizon,
                "candidate_id": candidate_id, "parameters": json.dumps(params, sort_keys=True),
                "validation_log_loss": score, "validation_n": len(y_validation),
                "selected": False,
            })
        best_score, best_id, best_params, best = min(candidate_models, key=lambda item: (item[0], item[1]))
        tuning_rows[-len(candidate_models) + best_id]["selected"] = True
        fitted[horizon] = best

        censored = {
            split: int((frame.split.eq(split) & frame[label].isna()).sum())
            for split in masks
        }
        missing_features = {
            split: int(frame.loc[frame.split.eq(split), list(features)].isna().any(axis=1).sum())
            for split in masks
        }
        for split, mask in masks.items():
            x = frame.loc[mask, list(features)]
            probability = best.predict_proba(x)[:, 1]
            predicted = (probability >= rules.decision_threshold).astype(int)
            for position, index in enumerate(frame.index[mask]):
                prediction_rows.append({
                    "event_id": frame.at[index, "event_id"],
                    "prediction_time": frame.at[index, "prediction_time"],
                    "split": split, "horizon_min": horizon,
                    "model": model_name, "feature_set": feature_set,
                    "y_true": int(frame.at[index, label]),
                    "y_score": float(probability[position]), "y_pred": int(predicted[position]),
                    "score_kind": "probability", "threshold": rules.decision_threshold,
                    "model_version": rules.version,
                    "n_censored_in_split": censored[split],
                    "n_missing_feature_in_split": missing_features[split],
                })

        feature_names = best.named_steps["preprocess"].get_feature_names_out()
        classifier = best.named_steps["classifier"]
        values = (classifier.coef_[0] if kind == "logistic"
                  else classifier.feature_importances_)
        for feature_name, value in zip(feature_names, values):
            interpretation_rows.append({
                "model_version": rules.version, "model": model_name,
                "feature_set": feature_set, "horizon_min": horizon,
                "feature": feature_name,
                "importance_type": "coefficient" if kind == "logistic" else "feature_importance",
                "value": float(value),
                "odds_ratio": math.exp(max(-700.0, min(700.0, float(value))))
                if kind == "logistic" else math.nan,
            })
        summary: dict[str, object] = {
            "horizon_min": horizon, "parameters": best_params,
            "validation_log_loss": best_score, "train_rows": len(y_train),
            "validation_rows": int(masks["validation"].sum()),
            "test_rows": int(masks["test"].sum()), "refit_after_selection": False,
        }
        if kind == "tree":
            summary.update({
                "tree_depth": int(classifier.get_depth()),
                "tree_leaves": int(classifier.get_n_leaves()),
                "tree_text": export_text(classifier, feature_names=list(feature_names)),
            })
        summaries.append(summary)
    return SupervisedResult(
        predictions=pd.DataFrame(prediction_rows), tuning=pd.DataFrame(tuning_rows),
        interpretation=pd.DataFrame(interpretation_rows), summaries=summaries,
        fitted=fitted,
    )


def run_supervised_files(
    *, kind: str, dataset_path: Path, contract_path: Path, rules_path: Path,
    feature_groups: tuple[str, ...] | None, predictions_path: Path, metrics_path: Path,
    tuning_path: Path, interpretation_path: Path, manifest_path: Path,
    figure_dir: Path | None = None,
) -> dict[str, object]:
    """Train, select and evaluate one supervised model family with evidence."""
    targets = [predictions_path, metrics_path, tuning_path, interpretation_path, manifest_path]
    for target in targets:
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing artifact: {target}")
    started_at, started_counter = start_run()
    if kind == "tree" and figure_dir is None:
        raise ValueError("Decision-tree runs require figure_dir")
    contract = ExperimentContract.from_path(contract_path)
    rules = SupervisedRules.from_path(rules_path)
    figure_paths = (
        [figure_dir / f"decision-tree-{horizon}m.png" for horizon in contract.horizons]
        if kind == "tree" and figure_dir is not None else []
    )
    for path in figure_paths:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing tree figure: {path}")
    result = train_supervised(
        pd.read_parquet(dataset_path), contract, rules,
        kind=kind, feature_groups=feature_groups,
    )
    metrics = evaluate_predictions(result.predictions, version_column="model_version")
    for target in (predictions_path, metrics_path, tuning_path, interpretation_path):
        target.parent.mkdir(parents=True, exist_ok=True)
    result.predictions.to_parquet(predictions_path, index=False)
    metrics.to_csv(metrics_path, index=False)
    result.tuning.to_csv(tuning_path, index=False)
    result.interpretation.to_csv(interpretation_path, index=False)

    figures: list[dict[str, str]] = []
    if kind == "tree" and figure_dir is not None:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt

        figure_dir.mkdir(parents=True, exist_ok=True)
        for horizon, pipeline in result.fitted.items():
            path = figure_dir / f"decision-tree-{horizon}m.png"
            feature_names = pipeline.named_steps["preprocess"].get_feature_names_out()
            figure, axis = plt.subplots(figsize=(18, 9))
            plot_tree(
                pipeline.named_steps["classifier"], feature_names=list(feature_names),
                class_names=["not within", "within"], filled=True, rounded=True,
                proportion=True, ax=axis,
            )
            figure.tight_layout()
            figure.savefig(path, dpi=150)
            plt.close(figure)
            figures.append({"path": path.as_posix(), "sha256": sha256_file(path)})

    manifest = {
        "manifest_version": "supervised-run-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_kind": kind, "model_version": rules.version,
        "dataset": {"path": dataset_path.as_posix(), "sha256": sha256_file(dataset_path)},
        "contract": {"path": contract_path.as_posix(), "sha256": sha256_file(contract_path)},
        "rules": {"path": rules_path.as_posix(), "sha256": sha256_file(rules_path)},
        "outputs": {
            "predictions": {"path": predictions_path.as_posix(), "sha256": sha256_file(predictions_path)},
            "metrics": {"path": metrics_path.as_posix(), "sha256": sha256_file(metrics_path)},
            "tuning": {"path": tuning_path.as_posix(), "sha256": sha256_file(tuning_path)},
            "interpretation": {"path": interpretation_path.as_posix(), "sha256": sha256_file(interpretation_path)},
            "figures": figures,
        },
        "summaries": result.summaries,
        "run": run_metadata(
            started_at=started_at, started_counter=started_counter,
            contract=contract, seed=rules.seed,
        ),
        "software": {"pandas": pd.__version__, "scikit_learn": sklearn.__version__},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def cli(kind: str) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/experiment_contract.json"))
    parser.add_argument("--rules", type=Path, default=Path("configs/supervised_models.json"))
    parser.add_argument("--feature-groups", help="Comma-separated groups; default comes from rules")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--tuning", type=Path, required=True)
    parser.add_argument("--interpretation", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path)
    args = parser.parse_args()
    groups = tuple(value.strip() for value in args.feature_groups.split(",")) if args.feature_groups else None
    run_supervised_files(
        kind=kind, dataset_path=args.dataset, contract_path=args.contract,
        rules_path=args.rules, feature_groups=groups,
        predictions_path=args.predictions, metrics_path=args.metrics,
        tuning_path=args.tuning, interpretation_path=args.interpretation,
        manifest_path=args.manifest, figure_dir=args.figure_dir,
    )
    return 0
