# Milestone 2 coverage OOM investigation and bounded pilot

Status: **small real-data coverage pilot passed; full multi-day pipeline not rerun**.
This is not a label-quality or spatial-matching report and does not establish ML readiness.
Original traffic ZIPs, Parquet inputs and the interrupted derived files were preserved.

## Investigation

The interrupted coverage log `reports/local/pilot_resume.log` ended while reading
`20261009.parquet`, after reporting 3,557,591 and 4,082,586 unique keys for the
first two archive partitions. An earlier observed running process reached about
2.6 GiB RSS. The kernel log contains an OOM kill of another Python PID at roughly
3.18 GiB anonymous RSS; it does not conclusively attribute that kill to the logged
pilot process. The log does not include a Python exception or exit status, so the
exact termination mechanism of that specific run is not independently established.

The prior implementation in `data/coverage.py` materializes a full archive-day
Parquet table, then copies/sorts/groups millions of rows multiple times for
feature and quality deduplication, retains boundary carry, and rereads compact
slots across days. Compressed Parquet size is not its in-memory size. These are
credible high-memory operations regardless of the exact kill mechanism.

At inspection: 15 GiB RAM, 8 GiB swap, approximately 937 GiB free disk; earlier
WSL2 measurements in this session showed 3.8 GiB RAM / 1 GiB swap. These are
observations at different times, not a guarantee of future memory limits.
`data/local/pilot/derived/compact/` contains two pairs of interrupted outputs,
without a completed coverage manifest. They are **not trusted or reused**; the
new implementation writes separately to `compact-bounded-v1/`. Nothing was
removed from the interrupted directory or verified source evidence.

## Implementation and scientific boundaries

`data/bounded_coverage.py` uses an Arrow Dataset Scanner with projected columns,
observation-time and detector predicates, 32,768-row batches, read-ahead 1,
`use_threads=False` and one processing worker. It holds at most a single day and
one detector group (default **two** detectors) in pandas for duplicate
reconciliation and five-minute bin aggregation. Input is scanned for each group;
this trades I/O/CPU for lower memory. There is no fixed absolute RSS limit: an
unusually dense detector/day or later stages could require more memory.

All provided capture partitions are searched for observations in each day, not
only the identically named archive day. Thus late cross-archive rows are included
in quality deduplication, and only rows available before the unchanged +10-minute
bin closure enter features. Cross-day observations are binned on right-closed
observation dates, retaining midnight bins. The downstream event constructor reads
all selected-cohort bins together, so event persistence can cross midnight.
This is not a claim that archive captures outside the supplied source files were
available or examined.

The selected detector inventory, per-day full-denominator coverage, conflict
quarantine, positive-flow criteria, feature availability and missing/censoring
semantics are unchanged. Explicit detector subsets are solely for benchmarking,
not a replacement for scientific cohort selection. A fully absent day is an empty
observation day, with zero present/valid slots against expected slots for the
observed inventory; no measurements are imputed.

A run manifest fingerprints source Parquet SHA-256, algorithm files, observation
range and batch/group settings. Bins and profile are written to temporary files
then atomically renamed; a day checkpoint is published last. On resumption, input
and output hashes are checked; a day lacking a checkpoint is recomputed and stale
temporary files are replaced. A corrupted checkpoint fails closed. Interrupted
or changed runs require investigation or a fresh directory, never silent reuse.
The implementation is single-writer: do **not** run two processes against the
same checkpoint directory. The event dataset and final reports have not yet been
validated under this refactor.

## Actual foreground benchmark — October 19, 2026 HKT

Input: all 15 existing real archived lane-snapshot Parquet partitions, explicitly
restricted to detectors AID01101, AID01102, AID01103 and AID01104, 2 per group.
Result: **4 detectors, 11 lane-days, 22,953 present slots, 22,935 valid-speed
slots, 0 conflicting keys** for this limited selection. These are not cohort-wide
or event statistics. `/usr/bin/time -v` measured **267,464 KiB peak RSS**
(~261 MiB), **2.08 s** wall time, **0 swaps**, exit 0. Resume: **124,356 KiB**,
**0.47 s**, 0 swaps, exit 0. Measurements include the CLI process and depend on
platform/cache; no full-run RSS claim follows.

Independent fresh recomputation in `bounded-benchmark-v6/` produced the same
Parquet SHA-256 as `bounded-benchmark-v5/`:

- bins: `8aef725b956d881e0b17ce42a87f52a21a54b89070bf6e2b5a1087c4c4bebc28`
- profile: `db06dbe86b7b6bfa8f31f2590634080ba13a8925c9e1e8d3a2176da17668a8be`

The second invocation against v5 reused and verified its checkpoint. Differential
synthetic tests compare lane/day metrics and bins against the previous small
reference, test cross-archive duplicates/late conflicts, missing days, corrupted
checkpoints and event persistence across midnight. Latest complete offline suite:
`uv run --locked pytest -q` — **72 passed in 4.93s**; `uv sync --locked` and
`git diff --check` also exited 0. Native Windows remains unverified.

## Reproduce the small benchmark (foreground, no network)

Use a fresh output name if the example already exists with different inputs/code:

```text
uv sync --locked
/usr/bin/time -v uv run --locked python -m traffic_recovery.data.bounded_coverage --start 2026-10-19 --end 2026-10-20 --detector AID01101 --detector AID01102 --detector AID01103 --detector AID01104 --group-size 2 --output data/local/pilot/bounded-benchmark-v5
uv run --locked pytest
```

`/usr/bin/time -v` is Linux/WSL-specific; the Python command itself uses pathlib.
Requires the already-acquired `data/local/pilot/lane_snapshots/` source partitions.
Rerunning the identical command validates and reuses checkpoints. Run the same
command with a different fresh output directory to independently recompute.

## Safe next step — not yet run

After reviewing the limited benchmark, run in the foreground with one worker:

```text
/usr/bin/time -v uv run --locked python -m traffic_recovery.data.pilot
```

This runs the configured **full** multi-day selection, labels and reports; it was
**not** run during the memory-fix task. On interruption, invoke the same command
again to validate and reuse completed daily coverage checkpoints. It does not
reuse old `compact/` outputs. Inspect peak memory and result validity before
claiming the full milestone complete. Some downstream stages may still require
further memory optimization, and the final artifacts/label counts/spatial matches
remain unverified. No background job, ML training, push or merge was performed.
