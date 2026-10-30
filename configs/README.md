# Configuration policy

This milestone uses explicit CLI parameters rather than an unused configuration
framework. Dates are inclusive **archive dates in Asia/Hong_Kong**, not an implied
continuous observation period. Commands run unchanged in PowerShell and Ubuntu.

Verified audit parameters:

| Parameter | Recorded value | Interpretation |
|---|---|---|
| `--start` / `--end` | `2026-10-19` / `2026-10-21` | Three consecutive days to test feasibility, not final research dates |
| `--daily` | enabled | Parse every returned daily raw XML snapshot |
| `--network` | enabled | Download/inspect large actual CENTERLINE GML |
| `--coverage-start` | `2010-01-01` (default) | Broad archive inventory probe; not claimed usable coverage |
| `--timeout` | 90 seconds | Timeout for each HTTP operation, with bounded retries |
| `--reuse` | enabled after original retrieval | Only identical URL, successful status and verified SHA-256 bodies |

A quick run omits `--daily` and `--network`; `--snapshots-per-day` defaults to 3,
evenly selected from the ordered version listing. Such a sample cannot establish
continuity. New runs should use new output directories and report names.

No congestion thresholds, recovery persistence, resampling grid, free-flow
reference, model parameters or temporal split dates are finalized here. Add
versioned experiment configurations only after the four owners approve these
rules using `docs/data_contract.md`. Record data/lock hashes and availability
semantics, not just a random seed.

## Executable candidate configurations

- `pilot.json` contains the provisional lane-event pilot settings.
- `experiment_contract.json` freezes the executable model-table candidate and
  retains `pending_member_1_4_review` as its scientific approval state.
- `external_features.json` versions availability joins and tolerances from the
  official-source audit; conditional source families remain disabled as research
  evidence until authentic fixtures and coverage pass review.
- `benchmarks.json` fixes the constant-baseline decision threshold and the simple
  `speed_ratio` rule before any validation/test result is inspected.
- `supervised_models.json` fixes train-only preprocessing, validation-log-loss
  selection, logistic-regression and decision-tree grids, seed and threshold.
  It explicitly disables refitting after model selection so the test set is
  evaluated once with the unchanged train-fitted selected pipeline.
- `feature_group_comparison.json` predeclares the local reference, incremental
  context/spatial feature sets, compared model families, test metrics and whether
  higher or lower values indicate improvement. Its approval remains pending until
  the real cohort and all source/spatial evidence pass team review.

Changing a split boundary, horizon, feature allowlist, availability rule or spatial
tolerance is a shared contract change and requires a reviewed PR. Experiment
manifests must hash the exact configuration used.
