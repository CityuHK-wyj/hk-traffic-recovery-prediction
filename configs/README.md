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
