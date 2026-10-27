# Member 1 — acquisition, coverage, events and labels

## Mission and scope
Own `src/traffic_recovery/data/`, `tests/test_{data,coverage,events}*`,
`configs/pilot.json`, data audit/label documentation. Produce a trustworthy
coverage-filtered cohort and temporally valid labels for Member 4. Do not assume
medium convenience events are independent or production-ready.

## P0 by October 29
1. Inspect `docs/medium_pilot.md`, `docs/data_contract.md`,
   `docs/pilot_memory_verification.md`, `reports/medium_pilot/statistics.json` and
   existing checksummed ZIP/snapshot evidence. Inventory gaps, invalids, partial
   days and location/metadata vintage; report both exclusions and denominators.
2. Independently audit lane-event definition, overlapping/same-episode lanes,
   onset/prediction delay, null/censor reasons, horizon definitions (within,
   not at), last-observed time and 60-minute separation/embargo. Do not finalize
   thresholds without measured rationale and agreement.
3. Propose reference fit windows that use **training past only**, no future fit,
   and candidate chronological train/validation/test windows with embargo and
   event grouping. Document what can/cannot be evaluated at dataset boundaries.
4. Provide a versioned small manifest: input hashes, timezone, selection, quality,
   label definition, event keys, null policy, planned splits and exact commands.
   Coordinate changes to `docs/data_contract.md` with Member 4 by PR.

## P1 after gates
- Run bounded day/detector-group checkpointed pilot and inspect measured resources;
  no unrestricted full-data job. Preserve raw bytes and checksums. Obtain a broader
  representative cohort only if source and memory allow. Freeze versioned output
  and report eligibility/event counts per horizon and split.
- Transfer only reproducible commands and small manifests, not raw observations in Git.

## Interface and acceptance
Required per event: stable `event_id`, detector/direction/lane, HKT-aware onset,
confirmation and prediction time, maximum feature availability, baseline fit end,
quality, outcome/censor reason and nullable 15/30/60-minute labels. Provide split
assignment and excluded-group audit separately. Missing is null; all prediction
features have availability <= prediction time. Member 4 approves consumer schema.
Acceptance: source-hash replay, documented denominators, no leakage, unique keys,
boundary/censor/episode tests and honest failure status. No final metric claims
until both labels and split reviewed.

```text
uv sync --locked
uv run --locked pytest -q tests/test_coverage.py tests/test_bounded_coverage.py tests/test_events.py tests/test_medium_validation.py
uv run --locked python scripts/verify_pilot.py
```

The verification command requires local source/checkpoint evidence; report 503-like
missing-data blockers rather than reconstructing synthetic observations. Full
reproduction and measured resources: `docs/medium_pilot.md`.

## Collaboration and blocker policy
Create `feature/member1-data-<topic>` from agreed base, draft PR; do not alter
Member 2/3/4 modules without agreement. Run tests, report hashes, counts,
resource limits, failures and unverified assumptions. Do not push/merge without
team authorization. If data quality/reference cannot be validated by October 31,
freeze the explorer as a descriptive pilot and explicitly delay model claims.
