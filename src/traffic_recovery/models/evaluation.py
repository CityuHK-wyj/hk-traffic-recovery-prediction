"""Shared long-form binary classification metrics with explicit undefined states."""
from __future__ import annotations

import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score


def _metric(
    rows: list[dict[str, object]], common: dict[str, object], name: str,
    value: float | None, reason: str | None = None,
) -> None:
    rows.append({**common, "metric_name": name, "metric_value": value,
                 "undefined_reason": reason})


def evaluate_predictions(predictions: pd.DataFrame, *, version_column: str) -> pd.DataFrame:
    """Evaluate event predictions by model, feature set, horizon and split."""
    required = {
        version_column, "event_id", "split", "horizon_min", "model", "feature_set",
        "y_true", "y_score", "y_pred", "score_kind", "n_censored_in_split",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Predictions missing metric columns: {sorted(missing)}")
    missing_feature_column = next((
        column for column in (
            "n_missing_feature_in_split", "n_missing_rule_feature_in_split"
        ) if column in predictions.columns
    ), None)
    if missing_feature_column is None:
        raise ValueError("Predictions missing a feature-missingness count column")
    rows: list[dict[str, object]] = []
    group_columns = [version_column, "horizon_min", "feature_set", "model", "split"]
    for keys, group in predictions.groupby(group_columns, sort=False, dropna=False):
        y = group.y_true.astype(int)
        pred = group.y_pred.astype(int)
        score = group.y_score.astype(float)
        positive = int(y.sum())
        predicted_positive = int(pred.sum())
        tp = int(((y == 1) & (pred == 1)).sum())
        tn = int(((y == 0) & (pred == 0)).sum())
        fp = int(((y == 0) & (pred == 1)).sum())
        fn = int(((y == 1) & (pred == 0)).sum())
        common = {
            **dict(zip(group_columns, keys)),
            "n_rows": len(group), "n_events": group.event_id.nunique(),
            "n_positive": positive,
            "n_censored": int(group.n_censored_in_split.max()),
            "n_missing_feature": int(group[missing_feature_column].max()),
            "prevalence": positive / len(group),
        }
        _metric(rows, common, "accuracy", (tp + tn) / len(group))
        _metric(rows, common, "precision", tp / predicted_positive if predicted_positive else None,
                None if predicted_positive else "no_predicted_positive")
        _metric(rows, common, "recall", tp / positive if positive else None,
                None if positive else "no_positive_labels")
        f1_denominator = 2 * tp + fp + fn
        _metric(rows, common, "f1", 2 * tp / f1_denominator if f1_denominator else None,
                None if f1_denominator else "no_positive_labels_or_predictions")
        if y.nunique() == 2:
            _metric(rows, common, "balanced_accuracy",
                    ((tn / (tn + fp)) + (tp / (tp + fn))) / 2)
            _metric(rows, common, "roc_auc", float(roc_auc_score(y, score)))
            _metric(rows, common, "pr_auc", float(average_precision_score(y, score)))
        else:
            for name in ("balanced_accuracy", "roc_auc", "pr_auc"):
                _metric(rows, common, name, None, "single_class_labels")
        if group.score_kind.nunique() != 1:
            raise ValueError("A metric group mixes score semantics")
        if group.score_kind.iloc[0] == "probability":
            _metric(rows, common, "brier_score", float(brier_score_loss(y, score)))
            _metric(rows, common, "log_loss", float(log_loss(y, score, labels=[0, 1])))
        else:
            _metric(rows, common, "brier_score", None, "score_is_not_probability")
            _metric(rows, common, "log_loss", None, "score_is_not_probability")
    return pd.DataFrame(rows)
