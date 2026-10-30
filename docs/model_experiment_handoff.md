# Model experiment handoff

This is the stage 8 handoff for the calendar, weather, incident, major-event and
spatial feature experiments. The implementation is complete; empirical results
remain blocked by the absence of the approved complete real model inputs.

## Run gate

Before a research run, obtain team approval for all of the following:

- the event cohort and 15/30/60-minute labels;
- temporal boundaries and purged overlap windows;
- calendar, weather, incident and major-event provenance/availability evidence;
- upstream/downstream spatial matches and coverage rules;
- the versioned benchmark, supervised-model and comparison configurations.

Do not change parameters after viewing test results. Configuration changes require
a new version and a new output directory.

## Reproduction sequence

From the repository root, using Python 3.12:

```text
uv lock --check
uv sync --locked
uv run --locked pytest
uv run --locked python -m traffic_recovery.models.dataset --events data/local/pilot/derived/events.parquet --context data/local/external/event_context.parquet --spatial data/local/pilot/derived/spatial_features.parquet --output data/local/model/event_features.parquet --manifest reports/local/model-dataset-manifest.json
uv run --locked python -m traffic_recovery.models.comparison --dataset data/local/model/event_features.parquet --dataset-manifest reports/local/model-dataset-manifest.json --output-dir reports/local/feature-group-comparison-v1
```

Never reuse an existing output path. The comparison run verifies the dataset hash
before fitting and refuses to overwrite an earlier evidence directory.

## Output interpretation

| Artifact | Purpose |
|---|---|
| `predictions.parquet` | Event-level labels, probabilities/rule scores and split metadata |
| `metrics.csv` | Long-form metrics by model, horizon, feature set and split |
| `feature-group-comparisons.csv` | Test values and direction-normalised change from local features |
| `tuning.csv` | Every validation candidate and the selected candidate |
| `interpretation.csv` | Logistic coefficients/odds ratios and tree feature importance |
| `tree-figures/*.png` | Selected tree structure for each feature set and horizon |
| `report.md` | Human-readable evidence, metrics, differences and limitations |
| `manifest.json` | Input/config/output hashes, software versions and model summaries |

Use `improvement_vs_reference` for a consistently oriented comparison: positive is
better than local-only. Retain `raw_delta` when reporting the metric's original
scale. Do not interpret either as statistical significance.

## Presentation boundary

Until every approval field is `approved`, present only the implemented method,
leakage controls, planned comparisons and current data blocker. Do not put
synthetic test values in a results table, chart, abstract or conclusion. After an
approved real run, verify its manifest and report before copying any number into
the poster; keep model, horizon, feature set, split and sample size attached to
every value.
