# Hong Kong Traffic Recovery Prediction

Four-member MSc Data Science project: predict recovery **within 15, 30 and 60
minutes**, and test whether neighboring-road conditions improve on local-only
features. Core experiments: **November 4, 2026**; poster: **November 6–7**.
Reproducible, authentic evidence takes priority over complexity.

## Local event explorer — first vertical slice

A read-only FastAPI + DuckDB API and React/TypeScript/Vite + MapLibre/ECharts
frontend can browse **real, provisional medium-pilot events** when the local
checksummed Parquet evidence is present. This is a local development prototype,
not a deployment, final research dataset, live traffic feed or trained model.
It deliberately shows **prediction unavailable** and does not show unverified
upstream/downstream relationships. Shared API/task contracts and parallel work:
[team handoff](docs/team_tasks/README.md).

From the repository root, in separate terminals:

```text
uv sync --locked
uv run --locked uvicorn traffic_recovery.api.app:app --host 127.0.0.1 --port 8000
npm ci --prefix frontend
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the local backend. The API
requires `data/local/pilot/medium-40/medium_events.parquet`, three corresponding
`bins-*.parquet`, `reports/medium_pilot/statistics.json` and
`data/sample/verified/detectors.csv` with checksum manifest. These inputs are
verified at each request; missing or changed files return **503**, never synthetic
fallbacks. Reproduce missing local data using [medium_pilot.md](docs/medium_pilot.md)
and [pilot_memory_verification.md](docs/pilot_memory_verification.md). Event outcomes
and curves include future observations and must never be treated as model features.
The map uses external OpenStreetMap raster tiles (network and tile-provider policy
apply); current detector coordinates and their datum/historical validity remain
unverified. If tiles/WebGL fail, coordinates and event details still display.

```text
uv run --locked pytest
npm run build --prefix frontend
```

Do not expose the development servers publicly or deploy them; no authentication,
production hardening or prediction-serving registry exists. See the handoff for
API schemas, known risks and next steps. Six spatial candidates remain pending
human review: [review packets](reports/spatial_pair_review/README.md).

## Milestone 2 — provisional coverage/event/spatial pilot

The pilot implementation adds incremental Parquet ingestion, historical-only
cohort/reference selection, censored 15/30/60-minute **within-horizon** labels,
threshold sensitivity, real-event curves and a small source-topology matching pilot.
The full pipeline was interrupted before completion; these are implemented capabilities,
not verified full-pilot results. The [memory investigation](docs/pilot_memory_verification.md)
records a successful limited real-data coverage benchmark and safe resumption.
No approved real-cohort ML result or dashboard result exists. Definitions and
[contract v0.2](docs/data_contract.md) remain pending team review.

Large raw and derived data stay ignored in `data/local/pilot/`. The intended event
output is `data/local/pilot/derived/events.parquet`, which has **not yet been produced**.
Reports/figures are intended for `reports/milestone2/` after a validated full run.

```text
uv sync --locked
uv run --locked python -m traffic_recovery.data.pilot_ingest --start 2026-10-07 --end 2026-10-21
uv run --locked python -m traffic_recovery.data.pilot
uv run --locked python -m traffic_recovery.network.pilot --acquire
uv run --locked python scripts/verify_pilot.py
uv run --locked pytest
```

Do not restart the full multi-day pipeline before reviewing the bounded-memory
benchmark and constraints in [pilot_memory_verification.md](docs/pilot_memory_verification.md).
The ingestion command acquires **15 archive dates** to cover 14 complete HKT
observation days plus boundary records. Existing milestone-1 ZIPs are checksum-
verified and reused automatically. Others use the official API with preserved
HTTP evidence. Allow tens of minutes; XML is never bulk-extracted. `--acquire`
fetches official TURN/INTERSECTION files and CENTERLINE if not already available
(the latter is ~484 MB). Each module supports `--help` and portable `Path` options.
To resume after interruption, rerun the identical pilot command in the foreground.
Daily coverage checkpoints are fingerprinted and checksum-verified. The optional
`--reuse-coverage` also verifies the aggregate coverage manifest and all daily
checkpoints; it still rebuilds historical references and labels.

**Important:** 90/95% coverage of sparse 5m bins is not continuous 30s coverage.
Bins close at end +10m and require two positive-flow valid slots; a lane-based
pilot is not road-segment ground truth. No spatial match or upstream/downstream
pair is certified from proximity. Inspect the reports before using any labels.

## Milestone 1 — historical verification

Architecture, provisional contracts and a **real official-data feasibility audit**
are implemented. No events/labels, ML training, dashboard or deployment yet.

On October 27, 2026, the audit retrieved and parsed all **3,121** raw traffic
snapshots archived October 19–21: **12,935,754 source lane-period rows**, **782
detectors**, **6,064 conflicting rows quarantined**. Coverage is not continuous:
**28.67%** of expected per-series slots between observed bounds are absent;
archive capture lags observations by **5–8 minutes**. These are quality findings,
not model metrics. Read [the audit](docs/data_audit.md) before designing labels.

## Environment and offline verification

Use Python **3.12** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root, in WSL2 Ubuntu or native Windows PowerShell:

```text
uv sync --locked
uv run --locked python --version
uv run --locked pytest
uv run --locked traffic-audit --help
```

Commands are intentionally single-line and shell-independent. `tzdata` is locked
for systems without an OS timezone database. Python uses `pathlib.Path`, UTF-8
and aware Asia/Hong_Kong times. Milestone 2 adds PyArrow (Parquet), Matplotlib
(offline figures) and Shapely (metre geometry/topology) to pandas/tzdata; pytest
is a development dependency. Stages 5–6 use scikit-learn for leakage-safe
logistic-regression and decision-tree experiments. No GeoPandas, NetworkX, API
keys, database or Docker is required.

## Reproduce a small live audit first

**These commands make live requests** and download authentic public government
records. Choose a past inclusive archive date range; yesterday is the documented
latest archive date. Example dates are verified, not fixed inside the pipeline.
Use new output/report names for new runs to avoid replacing recorded findings.

```text
uv run --locked traffic-audit --start 2026-10-19 --end 2026-10-21 --snapshots-per-day 3 --output data/local/smoke-audit --report reports/local/smoke-audit.json
```

This lists versions for each day and parses three selected snapshots per day,
not a continuity audit. It also retrieves catalogues, specifications, CSV metadata,
current raw/processed snapshots and broad historical inventory counts. Empty,
unexpected or incomplete responses fail explicitly; successful HTTP alone does
not imply valid data. Broad timestamp arrays may be truncated and are never used
as a complete acquisition list.

## Reproduce the measured three-day audit

```text
uv run --locked traffic-audit --start 2026-10-19 --end 2026-10-21 --daily --network --output data/local/audit-20261019-21 --report reports/local/reproduced-audit.json
```

`--daily` downloads all three daily raw ZIPs (~111 MB compressed / 2.2 GB XML)
and streams their 3,121 XML members. `--network` adds the **484 MB CENTERLINE
GML** download and a schema/identifier audit, **not spatial matching**. Omit
`--network` to avoid that resource. Allow several minutes for full parsing.
Date ranges are limited to 31 days per run to discourage accidental bulk jobs.

Add `--reuse` to an identical later run to use successful responses only after
URL and SHA-256 verification. Existing originals otherwise cause an explicit
refusal to overwrite. Use a fresh directory to fetch a fresh current snapshot.
Network failures preserve error evidence and yield nonzero exits; partial-stage
failures appear in JSON, never substituted with synthetic records.

The output directory contains unchanged response bodies, `.meta.json` response
metadata, per-attempt metadata/error bodies, `requests.jsonl`, archive listings,
original `sample_YYYYMMDD.xml` files and `cleaned_sample.csv` (**first snapshot
of each day only**). JSON includes aggregate quality, coverage, lag, storage,
conflict examples, errors and response provenance. ZIPs are read without extracting
unsafe URL-shaped directory paths.

### Boundary probes and sample profile

```text
uv run --locked python scripts/probe_archive.py --source raw --time 20210329-0908 --time 20261026-2359 --output data/local/raw-boundary-probe --report reports/local/raw-boundaries.json
uv run --locked python scripts/probe_archive.py --source segment --time 20210330-0909 --output data/local/segment-boundary-probe --report reports/local/segment-boundary.json
uv run --locked python scripts/profile_sample.py --sample data/sample/verified/cleaned_sample.csv.gz --detectors data/sample/verified/detectors.csv --report reports/local/sample-profile.json
```

The first probe deliberately returns exit **1** because the earliest listed raw
file has empty detector lists; the recent version parses. The earliest processed
file parses 63 rows, but **all are offline**, so cleaned speeds are all missing.
Recorded evidence: `reports/evidence/history_boundaries.json`.
The profile describes only the supplied sample, not the full audited period.

## Collaboration and layout

```text
src/traffic_recovery/
  data/        Member 1: acquisition, coverage, provisional events/labels
  network/     Member 2: source topology/matching pilot; certified features pending
  external/    Prediction-time-safe context adapters; real-source handoff pending
  models/      Contract, dataset, baselines, supervised models and ablation runner
tests/         Offline tests; labeled synthetic fixtures + real samples
configs/       Configuration/range policy; no finalized event thresholds
scripts/       Archive-boundary and exported-sample inspection CLIs
docs/          Contracts, ownership, sources, audit and verification
reports/       Portable measured audit JSON and request evidence
figures/       Figure policy; pilot plots live in reports/milestone2/
data/sample/verified/  Small authentic source samples + cleaned export
data/local/           Ignored large evidence stores
```

- [Agent instructions](AGENTS.md) apply to Codex, Pi and contributors.
- [Ownership and handoffs](docs/ownership.md): four independent modules.
- [Initial shared contracts](docs/data_contract.md): keys, units, availability
  and provisional labels; recovery **within** versus **at** a horizon.
- [Official sources](docs/data_sources.md) and [feasibility findings](docs/data_audit.md).
- [Actual verification outcomes](docs/verification.md).
- [External/modeling progress report](docs/external_modeling_progress_report.md):
  implemented files, reproduction steps, validation status and remaining gates.

Use feature branches and reviewed PRs. Coordinate shared interfaces; test before
requesting merge. Never commit secrets, large raw/processed datasets or models.
Small authentic evidence is deliberately curated and checksummed. Synthetic
fixtures are explicitly labeled and never represented as research observations.

## After the pilot (not yet validated)

Review the measured censoring/sensitivity and sparse-bin interpretation; approve
prediction unit, reference/availability rules and event-separated temporal splits.
Manually verify detector matches and reconcile network versions before any spatial
ablation. See the milestone-2 recommendation before authorizing a local baseline.
Optional context features still require separate source verification.
