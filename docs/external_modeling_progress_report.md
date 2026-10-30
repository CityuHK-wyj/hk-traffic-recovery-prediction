# External context and modeling progress report

**Report date:** 2026-10-30

**Scope:** collaboration setup, external context integration, experiment contract,
model dataset assembly, benchmarks, supervised models, feature-group comparison,
and experiment handoff.

**Excluded:** Tableau data preparation, dashboard construction, and Tableau results.

## 1. Executive summary

The software path for the assigned calendar, weather, incident, major-event,
benchmark, logistic-regression, decision-tree, and feature-group comparison work is
implemented locally. The code validates prediction-time availability, preserves
unknown labels, separates training/validation/test use, records hashes and software
versions, and refuses to overwrite evidence artifacts.

This is currently an **implementation milestone, not a completed empirical study**.
The repository does not yet contain the team-approved, complete real
`events.parquet`, external context table, and spatial feature table needed for the
research run. Consequently, no synthetic metric has been promoted as a finding and
no real model performance is reported here. This does not prevent a GitHub progress
update, provided the update says that the pipeline is software-verified and that
empirical results remain blocked by the real-data approval gate.

The latest local verification on 2026-10-30 used Python 3.12.3 in the requested
`basic_env` environment:

- dependency check: `No broken requirements found`;
- non-Tableau branch test suite: **125 passed, 2 dependency deprecation warnings**;
- lock check: `uv lock --check` resolved successfully with 46 locked packages;
- Git whitespace check: no errors; line-ending conversion warnings only.

## 2. Completion status by phase

| Phase | Work completed | Current status |
|---|---|---|
| 0 | Added repository collaboration instructions and domain/issue/triage documentation; established reproducibility and ownership gates. | Complete locally; changes are uncommitted and have not been pushed. |
| 1 | Added an executable experiment contract and validator for event keys, horizons, labels, splits, feature allowlists, and availability watermarks. | Software complete; Member 1/4 scientific review is pending. |
| 2 | Added prediction-time-safe calendar, weather, incident, and major-event feature builders plus an integrated context-table CLI and source audit. | Software complete; authentic staged source fixtures and coverage approval are pending. |
| 3 | Added the unified model-dataset builder with strict one-to-one joins and manifests. | Software complete; approved real input tables are pending. |
| 4 | Added majority-class, training-prevalence, and predeclared speed-ratio benchmarks with shared evaluation. | Software complete; no real benchmark metrics have been generated. |
| 5 | Added logistic regression with train-only preprocessing, validation-only selection, horizon-specific fitting, and coefficient/odds-ratio export. | Software complete; real-cohort run pending. |
| 6 | Added decision trees with validation selection, feature importance, depth/leaf summaries, text trees, and PNG tree export. | Software complete; real-cohort run pending. |
| 7 | Added eight predeclared feature sets and an orchestrator comparing logistic regression, decision trees, and benchmarks against local-only features. | Software complete; comparison values await real inputs. |
| 8 | Added reproducible output manifests, a human-readable experiment report, interpretation artifacts, and handoff documentation. | Handoff complete at software level; scientific approval and final research run remain pending. |

## 3. Python implementation reference

### 3.1 External context package

| File | Responsibility |
|---|---|
| `src/traffic_recovery/external/_validation.py` | Shared schema, timezone, string-ID, provenance, availability, and numeric validation helpers. It makes invalid inputs fail explicitly instead of silently coercing them. |
| `src/traffic_recovery/external/calendar.py` | Builds Hong Kong civil-date and public-holiday context from a calendar edition that was already published by `prediction_time`. |
| `src/traffic_recovery/external/weather.py` | Performs backward station-level as-of selection using both `observed_at` and `available_at`, with a configured maximum observation age. It never selects a future or bidirectionally nearest record. |
| `src/traffic_recovery/external/incidents.py` | Replays versioned incident snapshots, selects the latest already-available state, checks effective intervals and distance, and avoids backfilling later closure information. |
| `src/traffic_recovery/external/major_events.py` | Builds active, upcoming, and recent major-event context only from calendar editions published by prediction time. |
| `src/traffic_recovery/external/build.py` | Combines the individual context groups into exactly one row per event and attaches the configured context version. |
| `src/traffic_recovery/external/pipeline.py` | Command-line entry point that reads staged Parquet sources, builds the integrated context table, hashes inputs/config/output, writes a manifest, and refuses to overwrite existing artifacts. |
| `src/traffic_recovery/external/__init__.py` | Exposes the supported external-context interfaces without requiring callers to import internal helpers. |

Important semantics implemented by these modules:

- all event times must be timezone-aware and compatible with Hong Kong time;
- source information must satisfy `available_at <= prediction_time`;
- every nonempty staged source row carries its source URL, retrieval time, and source SHA-256;
- numeric identifiers are rejected rather than silently converted after possible leading-zero loss;
- weather is joined backward in time, not by future nearest observation;
- selective feeds distinguish “not observed by this source” from a verified zero;
- an unknown road-closure state leaves the closure count missing and sets an explicit flag;
- empty staged sources remain distinguishable through observation/missingness flags;
- the integrated table preserves one row for every input event.

### 3.2 Experiment and model package

| File | Responsibility |
|---|---|
| `src/traffic_recovery/models/contract.py` | Loads and validates the experiment contract. It checks unique event keys, aware timestamps, nullable monotone 15/30/60-minute labels, purged temporal splits, feature allowlists, and availability watermarks. |
| `scripts/validate_experiment_contract.py` | CLI for validating the handed-off event cohort and writing a non-overwriting manifest with hashes, label counts, approval state, and software versions. |
| `src/traffic_recovery/models/dataset.py` | Builds the unified event-level model table from event, context, and spatial inputs. It requires exact `(event_id, prediction_time)` key agreement, rejects duplicates/collisions, applies the feature allowlist, and writes a provenance manifest. |
| `src/traffic_recovery/models/evaluation.py` | Shared metric implementation for accuracy, balanced accuracy, ROC-AUC, PR-AUC, Brier score, and log loss. Undefined metrics are null with an explicit reason rather than fabricated values. |
| `src/traffic_recovery/models/benchmarks.py` | Implements majority class, training-label prevalence, and a predeclared speed-ratio rule. Constants are derived from training labels only; validation/test labels cannot influence them. |
| `src/traffic_recovery/models/supervised.py` | Shared supervised-model engine. It builds scikit-learn pipelines, fits preprocessing only on training rows, selects candidates on validation log loss, evaluates test once, and exports tuning and interpretation artifacts. |
| `src/traffic_recovery/models/logistic.py` | Thin CLI wrapper for horizon-specific logistic-regression runs and coefficient/odds-ratio output. |
| `src/traffic_recovery/models/decision_tree.py` | Thin CLI wrapper for horizon-specific decision-tree runs, feature importance, text summaries, and tree figures. |
| `src/traffic_recovery/models/comparison.py` | Runs all configured feature sets for both supervised models, adds benchmark results, calculates change from local-only features, writes the report and artifacts, and verifies the model-dataset manifest hash before fitting. |
| `src/traffic_recovery/models/provenance.py` | Records run ID, timing, seed, split boundaries, lock hash, Git commit/dirty state, and Python version in experiment manifests. |
| `src/traffic_recovery/models/__init__.py` | Exposes stable model interfaces at the package boundary. |

### 3.3 Model behavior and leakage controls

The supervised implementation trains separate models for 15, 30, and 60 minutes.
Each candidate pipeline—including imputation, categorical encoding, and logistic
scaling—is fitted on training rows only. Validation log loss chooses the candidate.
The selected train-fitted pipeline is applied unchanged to the test split; the code
does not refit on train plus validation after seeing validation performance.

The comparison feature sets are:

1. `local`;
2. `local + calendar`;
3. `local + weather`;
4. `local + incident`;
5. `local + major_event`;
6. `local + spatial`;
7. `local + all_context`;
8. `local + all` (all context plus spatial).

For every supervised model, horizon, and test metric, the comparison output stores
both the raw difference from `local` and `improvement_vs_reference`. Positive
`improvement_vs_reference` always means better: it is positive for higher
classification/discrimination metrics and positive when error metrics decrease.
These differences are descriptive and are not confidence intervals or significance
tests.

The comparison runner also applies one shared cohort rule before any model is fit:
every compared row must have observed event-time `speed_ratio`. This keeps the
majority, prevalence, speed-rule, logistic, and tree metrics paired on identical
eligible rows instead of silently comparing different samples.

## 4. Configuration files

| File | Purpose | Scientific approval value |
|---|---|---|
| `configs/experiment_contract.json` | Event grain, horizons, split boundaries, feature groups, availability columns, and outcome-only fields. | `pending_member_1_4_review` |
| `configs/external_features.json` | Backward-join policy, source tolerances, weather age, incident distance, and major-event time windows. | `pending_source_fixture_and_team_review` |
| `configs/benchmarks.json` | Benchmark list, decision threshold, speed-ratio rule, and metrics. | `pending_team_review` |
| `configs/supervised_models.json` | Seed, selection metric, candidate grids, threshold, and no-refit policy for logistic regression and trees. | `pending_real_cohort_and_team_review` |
| `configs/feature_group_comparison.json` | Local reference, incremental feature sets, models, split, and comparison metrics. | `pending_real_cohort_and_team_review` |

`pyproject.toml` and `uv.lock` were updated to include the required scikit-learn
dependency while retaining the Python 3.12/locked-environment workflow.

## 5. Tests added for this work

| Test file | Verified behavior |
|---|---|
| `tests/test_external_features.py` | Calendar civil dates, backward weather joins, incident snapshot replay, provenance/string-ID validation, unknown closure state, publication filtering, tolerances, and one-row-per-event integration. |
| `tests/test_model_contract.py` | Contract loading, label monotonicity, temporal splits/purging, fail-closed feature watermarks, forbidden outcome features, and manifest generation. |
| `tests/test_model_dataset.py` | Exact-key joins, duplicate/missing-key failures, allowlist pruning, and dataset manifest hashes. |
| `tests/test_benchmarks.py` | Train-only benchmark constants, threshold rule behavior, missing/censored rows, long-form metrics, and undefined-metric reasons. |
| `tests/test_supervised_models.py` | Candidate selection, train-only preprocessing, independent horizons, deterministic outputs, interpretation files, and non-overwrite behavior. |
| `tests/test_feature_group_comparison.py` | Feature-set orchestration, local-reference deltas, dataset-hash verification, approval banners, and output manifests. |

Synthetic fixtures in these tests validate code behavior only. They are explicitly
not evidence about Hong Kong traffic recovery or model quality.

## 6. Reproduction workflow

Run from the repository root with Python 3.12. The portable project commands are:

```text
uv sync --locked
uv run --locked pytest
```

After the real event cohort is approved, validate its contract:

```text
uv run --locked python scripts/validate_experiment_contract.py --events data/local/pilot/derived/events.parquet --report reports/local/experiment-contract.json
```

After authentic staged external sources pass the source gate, build context:

```text
uv run --locked python -m traffic_recovery.external.pipeline --events data/local/pilot/derived/events.parquet --holidays data/local/external/holidays.parquet --weather data/local/external/weather.parquet --incidents data/local/external/incidents.parquet --major-events data/local/external/major-events.parquet --output data/local/external/event_context.parquet --manifest reports/local/external-context-manifest.json
```

Build the unified model table:

```text
uv run --locked python -m traffic_recovery.models.dataset --events data/local/pilot/derived/events.parquet --context data/local/external/event_context.parquet --spatial data/local/pilot/derived/spatial_features.parquet --output data/local/model/event_features.parquet --manifest reports/local/model-dataset-manifest.json
```

Run the complete benchmark/model/feature-group comparison:

```text
uv run --locked python -m traffic_recovery.models.comparison --dataset data/local/model/event_features.parquet --dataset-manifest reports/local/model-dataset-manifest.json --output-dir reports/local/feature-group-comparison-v1
```

Every output path must be new. The commands intentionally refuse to overwrite a
previous evidence directory or manifest.

## 7. Expected non-Tableau experiment outputs

The comparison run creates:

| Artifact | Meaning |
|---|---|
| `predictions.parquet` | Event-level labels, model probabilities/rule scores, split, horizon, and feature-set identifiers. |
| `metrics.csv` | Long-form metrics by model, horizon, feature set, and split. |
| `feature-group-comparisons.csv` | Test values, raw differences, and direction-normalized improvement from local-only features. |
| `tuning.csv` | Every candidate evaluated on validation data and the selected candidate. |
| `interpretation.csv` | Logistic coefficients/odds ratios and decision-tree feature importance. |
| `tree-figures/*.png` | Selected decision-tree structure for each feature set and horizon. |
| `report.md` | Human-readable run results, configuration state, and limitations. |
| `manifest.json` | Input, configuration, and output hashes plus software/model summaries. |

When any approval remains pending, generated experiment reports are marked
`EXPLORATORY — NOT APPROVED AS FINAL RESULTS`. A later approved real run must use a
new output directory so software-validation artifacts cannot be mistaken for final
evidence.

## 8. Current blockers and required handoffs

1. **Approved real events:** Member 1 and Member 4 must approve the prediction unit,
   label/censoring rules, reference fit, event separation, and temporal split policy.
2. **External source evidence:** authentic preserved source bytes, source manifests,
   parser fixtures, coverage measurements, and availability proofs are still needed.
3. **Spatial handoff:** reviewed segment matching, direction, version validity, and
   spatial feature coverage are required for RQ2 and the `local + spatial` runs.
4. **Complete model inputs:** the final real event, context, and spatial Parquet
   inputs are not currently available in the repository.
5. **Ownership confirmation:** `docs/ownership.md` still records a temporary Member 3
   frontend assignment, while this work spans the `external/` and `models/`
   packages. The team should reconcile this in the reviewed PR rather than silently
   changing ownership.

Until these gates pass, the team may report completed engineering, test coverage,
planned comparisons, and reproducibility controls. It must not report synthetic
metric values as empirical performance, place them in the poster's results table,
or use them to support a conclusion.

## 9. Suggested GitHub progress update

The following can be copied into an issue or pull-request description:

```markdown
## Progress: external context and recovery-model experiments

### Completed
- Implemented prediction-time-safe calendar, weather, incident, and major-event adapters.
- Added executable event/label/split/feature contract validation.
- Added strict unified event/context/spatial dataset assembly and SHA-256 manifests.
- Implemented majority-class, training-prevalence, and speed-ratio benchmarks.
- Implemented horizon-specific logistic regression and decision trees with train-only preprocessing and validation-only selection.
- Added local-only vs calendar/weather/incident/major-event/spatial/all feature-group comparison.
- Added coefficients, odds ratios, tree importance/figures, tuning history, long-form metrics, reports, and run manifests.
- Verified in Python 3.12.3: `pip check` clean, `125 passed` for the non-Tableau branch, and `uv lock --check` successful.

### Not yet a research result
- No approved complete real `events.parquet`, context table, and spatial feature table are available yet.
- No synthetic metric has been promoted as model performance.
- Scientific approval fields remain pending in the versioned configs.

### Review/handoff requested
- Member 1/4: approve event/label/censoring/split contract.
- External-data reviewers: approve authentic source manifests, availability evidence, and coverage.
- Member 2: approve spatial matches, direction, version, and coverage.
- Team: confirm module ownership and run the frozen real cohort in a new output directory.
```

## 10. Git state at report time

All described changes are prepared on `codex/external-modeling-progress`. Tableau
code, tests, documentation, and local output artifacts are outside this report and
outside the intended commit. Before merging, review the full pull-request diff and
confirm that no local data or model artifacts are included.
