# Unified model dataset and modelling protocol

Stages 3–6 implement the reproducible software path from approved event and
feature tables to baseline and supervised-model predictions. They do not produce
research findings without the approved real pilot cohort.

## Stage 3: unified event table

`traffic_recovery.models.dataset` treats the event table as the authoritative
grain. Context and spatial tables must contain exactly the same unique
`(event_id, prediction_time)` keys. Missing keys, duplicate keys and payload column
collisions fail instead of silently changing the sample.

The builder accepts upstream `split_proposal` as `split` only when no conflicting
`split` exists. It retains identifiers, nullable labels/reasons, outcome audit
fields, explicit provenance and only the configured feature allowlist. Outcome
audit fields remain in the dataset for validation but are rejected by the model
feature selector.

```text
uv run --locked python -m traffic_recovery.models.dataset --events data/local/pilot/derived/events.parquet --context data/local/external/event_context.parquet --spatial data/local/pilot/derived/spatial_features.parquet --output data/local/model/event_features.parquet --manifest reports/local/model-dataset-manifest.json
```

Omit `--context` or `--spatial` only when that optional group is unavailable. The
manifest hashes every supplied input, the experiment contract and the output.

## Stage 4: benchmarks

The implemented models are intentionally simple:

- `majority_class`: the most frequent known training label; a tie resolves to 0.
- `train_prevalence`: the known training positive rate as a constant probability.
- `speed_ratio_rule`: predicts positive when event-time `speed_ratio` is at or
  above the predeclared threshold in `configs/benchmarks.json`.

All three models are evaluated on identical rows with known labels and observed
`speed_ratio`. Censored labels and missing rule features are counted explicitly.
Neither validation nor test outcomes affect fitted prevalence or majority class.
The speed-ratio output is a ranking/rule score, not a calibrated probability, so
Brier score and log loss are null with `score_is_not_probability`.

```text
uv run --locked python -m traffic_recovery.models.benchmarks --dataset data/local/model/event_features.parquet --predictions reports/local/benchmark-predictions.parquet --metrics reports/local/benchmark-metrics.csv --manifest reports/local/benchmark-manifest.json
```

Metrics are long-form by horizon, feature set, model and split. Single-class
ROC-AUC, PR-AUC and balanced accuracy are null with an explicit reason. Existing
outputs are never overwritten.

## Stages 5 and 6: supervised models

`configs/supervised_models.json` predeclares the random seed, validation metric,
decision threshold and candidate grids. Logistic regression and decision trees
are trained independently for 15, 30 and 60 minutes. Every candidate—including
its imputer, encoder and logistic scaler—is fitted on training rows only.
Validation log loss selects one candidate per horizon. The selected train-fitted
pipeline is then applied unchanged to the test split; there is deliberately no
train-plus-validation refit.

Logistic regression exports transformed feature coefficients and odds ratios.
Decision trees export impurity feature importance, depth, leaf count, a text tree
and one PNG per horizon. Both commands also produce event-level probabilities,
long-form metrics, complete tuning tables and SHA-256 manifests:

```text
uv run --locked python -m traffic_recovery.models.logistic --dataset data/local/model/event_features.parquet --predictions reports/local/logistic-predictions.parquet --metrics reports/local/logistic-metrics.csv --tuning reports/local/logistic-tuning.csv --interpretation reports/local/logistic-coefficients.csv --manifest reports/local/logistic-manifest.json
uv run --locked python -m traffic_recovery.models.decision_tree --dataset data/local/model/event_features.parquet --predictions reports/local/tree-predictions.parquet --metrics reports/local/tree-metrics.csv --tuning reports/local/tree-tuning.csv --interpretation reports/local/tree-importance.csv --manifest reports/local/tree-manifest.json --figure-dir reports/local/tree-figures
```

The default feature set is `local`. Use `--feature-groups local,calendar` (and
other complete groups) for the feature-group comparison runs. Missing columns in
a selected group fail fast, preventing comparisons between silently different
feature definitions. Existing artifacts are never overwritten.

## Stages 7 and 8: feature-group comparison and handoff

`configs/feature_group_comparison.json` predeclares the local reference and seven
incremental feature sets: calendar, weather, incident, major event, spatial, all
context, and all context plus spatial. The comparison runner executes logistic
regression and decision trees for every configured set, and includes the three
stage-4 benchmarks in the combined prediction and metric files.

Before fitting, it restricts every compared model to the same rows with observed
event-time `speed_ratio`. The manifest records excluded counts by split, preventing
constant benchmarks and supervised models from being compared on different cohorts.

For each supervised model, horizon and test metric it records the raw difference
from `local` and a direction-normalised improvement. Positive improvement always
means better: higher for discrimination/classification metrics and lower for
Brier score or log loss. These are descriptive differences, not confidence
intervals or significance tests.

The command requires the stage-3 dataset manifest and verifies its SHA-256 before
training. It creates a new output directory containing predictions, metrics,
feature-group comparisons, tuning history, interpretation tables, decision-tree
figures, a Markdown report and a manifest that fingerprints every dependency:

```text
uv run --locked python -m traffic_recovery.models.comparison --dataset data/local/model/event_features.parquet --dataset-manifest reports/local/model-dataset-manifest.json --output-dir reports/local/feature-group-comparison-v1
```

The output directory must not already exist. When any contract/config approval is
pending, the report is headed `EXPLORATORY — NOT APPROVED AS FINAL RESULTS` and
explicitly prohibits treating synthetic or pending-approval measurements as
empirical findings. Once the real cohort is available, use a new output directory;
do not replace the synthetic software-validation artifacts.

Run manifests also record a unique run ID, start/recorded time, runtime, seed,
temporal boundaries, `uv.lock` hash, Git commit/dirty state and Python version.

## Scientific gate

The speed-ratio threshold is a predeclared software baseline, not an empirically
validated traffic threshold. The team must approve the event cohort, split policy,
external/spatial source evidence and model configurations before reporting real
values. The synthetic test outputs validate software behavior only and must not
appear in the research results or presentation as empirical performance.
