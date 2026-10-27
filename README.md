# Hong Kong Traffic Recovery Prediction

Four-member MSc Data Science project: predict recovery **within 15, 30 and 60
minutes**, and test whether neighboring-road conditions improve on local-only
features. Core experiments: **November 4, 2026**; poster: **November 6–7**.
Reproducible, authentic evidence takes priority over complexity.

## Milestone 1 status

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
and aware Asia/Hong_Kong times. Only pandas and tzdata are runtime dependencies;
pytest is a development dependency. No API keys, database, Docker or GIS/ML
framework installation is required for this milestone.

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
  data/        Member 1: acquisition, parsing, quality; events/labels next
  network/     Member 2: schema audit; matching/graph/spatial features next
  external/    Member 3: reserved for verified context features
  models/      Member 4: reserved for baselines/evaluation/ablation
tests/         Offline tests; labeled synthetic fixtures + real samples
configs/       Configuration/range policy; no finalized event thresholds
scripts/       Archive-boundary and exported-sample inspection CLIs
docs/          Contracts, ownership, sources, audit and verification
reports/       Portable measured audit JSON and request evidence
figures/       Figure policy; no generated experiment plots yet
data/sample/verified/  Small authentic source samples + cleaned export
data/local/           Ignored large evidence stores
```

- [Agent instructions](AGENTS.md) apply to Codex, Pi and contributors.
- [Ownership and handoffs](docs/ownership.md): four independent modules.
- [Initial shared contracts](docs/data_contract.md): keys, units, availability
  and provisional labels; recovery **within** versus **at** a horizon.
- [Official sources](docs/data_sources.md) and [feasibility findings](docs/data_audit.md).
- [Actual verification outcomes](docs/verification.md).

Use feature branches and reviewed PRs. Coordinate shared interfaces; test before
requesting merge. Never commit secrets, large raw/processed datasets or models.
Small authentic evidence is deliberately curated and checksummed. Synthetic
fixtures are explicitly labeled and never represented as research observations.

## Next milestone (not started)

Agree a coverage-filtered cohort, prediction unit and realistic availability policy;
resolve ambiguous lanes/network versions and manually inspect direction-aware
mapping; justify event/recovery/censoring rules and temporal/event split boundaries.
Only then begin a reproducible local baseline and controlled spatial ablation.
Optional context features require separate source verification.
