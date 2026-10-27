# Project instructions (Codex and Pi)

## Purpose and scope
Predict congestion recovery **within** 15/30/60 minutes on Hong Kong roads.
RQ1 compares horizons; RQ2 compares local-only with neighboring-road features.
Authentic, traceable data and valid reproducible experiments outrank complexity.
Core experiments: **November 4, 2026**. Poster: **November 6–7, 2026**.
Outputs: audited datasets, justified event/label definitions, temporal evaluation,
spatial ablation, documented limitations, reproducible reports and poster.
Current milestone is the coverage-filtered event/label and spatial matching pilot:
no full ML training, dashboard, deployment, database or Docker requirement.

## Engineering
- Python **3.12**, `uv`, `pyproject.toml` and committed `uv.lock`.
- Simple modular `src/traffic_recovery` package; pandas first. Add GeoPandas,
  NetworkX or ML dependencies only when the milestone needs them.
- Type public interfaces; document contracts, units, failure modes and return values.
- Use `pathlib.Path`, UTF-8 and timezone-aware timestamps; support WSL2 and Windows.
  No machine-specific absolute paths or shell-only assumptions in Python.
- Use structured logging fields and explicit errors. Never silently swallow failures.
- Document exact reproduction commands. Standard check: `uv sync --locked` then
  `uv run --locked pytest`. Routine tests are offline; label synthetic fixtures.

## Data integrity
- Never fabricate observations or metrics, or silently substitute synthetic data.
- Preserve original bytes, source URLs, source timestamps, retrieval times,
  response metadata and checksums. Keep observed and derived fields distinct.
- Missing is missing, **not zero**. Respect source validity flags and report
  coverage, invalid values, gaps, schema drift and quality limitations.
- Features must be available at prediction time: no future observations,
  retrospective context or full-dataset fitted transformations.
- Prevent temporal and event-level leakage; purge overlapping label windows.
- Do not finalize congestion/recovery thresholds without measured data and rationale.
  Recovery within a horizon is not recovery at its endpoint.

## Collaboration
See `docs/ownership.md` and follow `docs/data_contract.md`.
1. Member 1: `data/` — traffic acquisition, cleaning, events and labels.
2. Member 2: `network/` — roads, matching, direction and spatial features.
3. Member 3: `external/` — weather, holidays, verified incidents/context.
4. Member 4: `models/` — baselines, temporal evaluation, ablation, interpretation.
All four own research design, verification, documentation and poster work.
Avoid unnecessary edits to another member's module. Coordinate shared interface
changes in a PR before adoption; proposals in the contract are not final schemas.
Use feature branches and reviewed PRs; run tests before requesting merge.
Never commit credentials, large raw/processed datasets or large model artifacts.
Do not push or merge without authorization.

## Agent workflow
Inspect git status, code and docs first; preserve pre-existing user changes.
Make a short plan and implement one verifiable milestone at a time.
Run checks and inspect actual outputs. Distinguish succeeded, failed and unverified;
never claim tests ran when they did not. Keep provenance and blockers in reports.
Stop after the requested milestone; do not expand scope autonomously.
