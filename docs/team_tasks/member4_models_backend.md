# Member 4 — modelling, evaluation and backend

## Mission and scope
Own `src/traffic_recovery/models/`, `src/traffic_recovery/api/`, corresponding tests,
and evaluation protocol. API currently reads verified medium-pilot Parquet via
bounded queries; it does not train/serve models. Scientific model fitting is gated
on Member 1 labels/cohort/splits. No production server or database required.

## P0 by October 29
1. Independently specify chronological train/validation/test windows, event/lane
   grouping, 60-minute window purge/embargo, training-only baselines/transforms,
   label eligibility/censoring, 15/30/60-minute metrics and uncertainty. Treat
   overlapping lane episodes as correlated; no endpoint-only label substitution.
2. Implement offline synthetic contract tests for split/group leakage, temporal
   availability, null/censor exclusions and deterministic minimal baseline
   interface; no fabricated research results. Ask Member 1 to approve definitions.
3. Maintain the read-only API contract in `integration_plan.md` and robust local
   404/503/schema handling; support Member 3 integration. Keep all SQL parameterized,
   paths local and local evidence checksummed. API binds localhost; no deployment.
4. Design a prediction-artifact interface that requires genuine frozen model ID,
   code/input/version hashes, train/reference cutoff, prediction time, event ID and
   horizon; only emit `available` for compatible genuine out-of-sample outputs.
   Otherwise `unavailable` with null values. Implement under reviewed PR.

## P1 after scientific gates
- Train simple traffic-only baseline using Member 1's approved audited cohort;
  freeze chronological splits and feature transformations first. No full-scale
  training until explicitly agreed. Report class balance, coverage/censoring,
  sample sizes, metrics, confidence limitations, hardware, runtime and provenance.
- Spatial ablation only if Member 2 supplies approved mappings/transitions and
  enough genuinely observed neighbors. Compare on **identical common events,
  horizons, splits and nonspatial features**. Otherwise NO-GO; never replace
  topology with geographic proximity under the RQ2 label.

## Run and acceptance

```text
uv sync --locked
uv run --locked pytest -q tests/test_api.py
uv run --locked pytest
uv run --locked uvicorn traffic_recovery.api.app:app --host 127.0.0.1 --port 8000
```

See `docs/medium_pilot.md` for verified real-data inputs and root README for UI.
Current tests use labelled synthetic files and do not establish scientific validity.
Acceptance: API returns real evidence or clear 503; unknown ID 404; no mock
prediction exposed as genuine; no leakage; tests cover corrupt input, missing bins,
nulls and split boundaries. Report results, hashes and not-run checks. Start
`feature/member4-models-api-<topic>`; coordinate API contract with Member 3 and data
schema with Members 1/2; draft PR and no push/merge without authorization.
