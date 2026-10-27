# Medium-scale traffic coverage and recovery verification

**Status: controlled scalability test passed; full multi-day pilot not run.** No ML
training, dashboard, deployment, push or merge. These are real historical observations,
not synthetic data or model metrics. All thresholds and the normal-speed reference
remain provisional and require team review.

## Scope and provenance

Input: all 15 preserved `data/local/pilot/lane_snapshots/*.parquet` capture files;
SHA-256 per file and algorithm settings are preserved in
`data/local/pilot/medium-40/run.json`. Observation days are the three right-closed
HKT days October 18, 19 and 20, 2026, ending at October 21 00:00 HKT. The capture
files are searched by observation time, so late captures in the supplied files are
not silently ignored. Input bytes and existing checkpoints were not modified.

Convenience cohort: first 40 distinct IDs sorted lexically from the verified
current detector metadata; 39 are observed during the three days. This is not a
coverage-selected or geographically representative research cohort, and it is not
the full-pilot cohort. Lane units are retained rather than merged.

Measured: **297 lane-days**, **619,648 present** unique 30-second lane slots of
**855,360 expected** (72.44% presence), **618,182 valid-speed** slots (72.27%
of expected); **1,466 offline** slots, **0 conflicting keys**, **0 extra repeat
rows**. Denominator is observed-union lanes × full days, not the historical
inventory of every existing lane. The 30-second coverage and five-minute bin
coverage have different meanings.

## Scalability measurement

Actual foreground command and raw output: [coverage timing](../reports/medium_pilot/coverage_time.txt),
[coverage measurements](../reports/medium_pilot/coverage_measurements.json).
Two detectors per group; batch size 32,768, one scanner worker, read-ahead 1.

| Measurement | Fresh coverage run | Checkpoint replay |
|---|---:|---:|
| Total wall time (`/usr/bin/time -v`) | 40.10 s | see [resume timing](../reports/medium_pilot/resume_time.txt) |
| Coverage function elapsed | 38.50 s | 0.161 s |
| Maximum RSS | **340,692 KiB** (332.7 MiB) | **153,520 KiB** (149.9 MiB) |
| Process logical bytes read (`rchar`) | 2,066,235,484 | 412,531,937 |
| Process physical bytes read (`read_bytes`) | 424,345,600 | 0 (cached) |
| Process physical bytes written | 966,656 | 0 |
| Coverage outputs, including 3 checkpoints and run manifest | 926,997 bytes | unchanged |
| Swaps | 0 | 0 |

Counters are Linux `/proc/self/io` deltas inside the Python process, not total
system I/O. `/usr/bin/time -v` also reports process-family block I/O, which is a
different measurement. Cache and WSL2 configuration affect timings and physical
reads. A 411,281,798-byte input set is hashed on each run, even on resume.
Subtracting the roughly 412.5 MB replay read from the 2.066 GB fresh logical reads
leaves roughly **1.65 GB** additional logical reads to process 40 requested
IDs × 3 days. This is about **4×** the compressed input size over and above the
checksum pass: repeated scans are material. Physical traffic was substantially
lower in this run due to cache, but cannot be assumed in a cold or constrained
system. `rchar` is not a count of unique bytes read and includes metadata reads.

Each day produces an atomic bin/profile pair and checksum-verified checkpoint;
all **3** checkpoints were present. The identical replay produced the same
coverage counts and verified hashes without writing outputs. A missing checkpoint
causes that day to be recomputed; changed inputs/code/config or a corrupt
checkpoint fail closed. A day is the restart unit, not each detector group.
Never run two writers against one checkpoint directory.

### Reference-rule comparison

The first two detectors on October 18 were independently loaded from all supplied
capture files and evaluated with the existing unpartitioned pandas `deduplicate`,
`make_bins` and `profile_day` rules. Equality passed for **12,720 source rows,
12,720 unique keys, 1,728 bins and 6 lane-day profiles**, including all shared
columns after sorting. This confirms this slice, not all 40 detectors/days or
independence of the scientific definitions. Synthetic regressions separately
exercise cross-day duplicate conflicts, late arrivals, missing days and interruption.

## Real event verification

For event demonstration only, the 85th percentile of usable positive-flow 5m
median speed was fitted on **October 18–19**, requiring at least **300** reference
bins per lane and requiring observation and archive availability before October
20 00:00. **98 lanes / 39 detectors** had a reference. No October 20 outcomes
were used in the fit. Two historical days are too short to establish a robust
normal-speed baseline; this is a feasibility demonstration, not a final label.

Events were searched only on **October 20**, with the existing rules: prior three
usable recovered bins to arm, two consecutive bins at <=0.5 of the lane reference
to confirm onset, and three consecutive bins >=0.8 to confirm recovery. Prediction
is at onset-confirmation bin end +10 minutes. A positive is sustained recovery
**within** the horizon; an observed negative requires uninterrupted valid
follow-up through the horizon; otherwise the horizon is censored. Positive-flow
bins need only two valid source slots, so unobserved within-bin physical transitions
remain possible.

**40 witnessed lane-level onset rows** from **29 lanes / 13 detectors**:

| Horizon | Recovered within horizon (1) | Observed unrecovered within horizon (0) | Censored / unknown | Known labels |
|---|---:|---:|---:|---:|
| 15 min | 5 | 32 | 3 | 37 |
| 30 min | 8 | 28 | 4 | 36 |
| 60 min | 12 | 23 | 5 | 35 |

These 40 rows are **not independent road events**: there are only 28 distinct
`(detector, direction, onset)` groups, with simultaneous lane onsets. A road event
can also affect nearby detectors. The full pilot's coverage/cohort rules select
one lane per detector-direction; this benchmark intentionally did not, so its
counts must not be copied into the main study. `0` at 60 minutes means not
confirmed recovered *within that horizon*, not necessarily never recovered later.

Event termination across all 40 rows: **31 recovered eventually**, **8 stopped
at a missing/unusable bin**, and **1 reached the end of the observation period**.
The nine latter rows are episode-follow-up censored, but some already have known
shorter or even 60-minute labels; do not sum termination counts with horizon label
counts. Conversely, a recovered episode can have a negative 60-minute label if
recovery occurred later. No episode is proven permanently unrecovered.

An independent real-output check passed for all **40** rows: historical fit
boundary, onset and recovery persistence, available-at-prediction, uninterrupted
follow-up, within-horizon labels and censoring, label monotonicity, and >60-minute
same-lane prediction separation. The events are in ignored local
`data/local/pilot/medium-40/medium_events.parquet` (SHA-256 and per-day bin hashes
in [statistics.json](../reports/medium_pilot/statistics.json)); review table:
[events.csv](../reports/medium_pilot/events.csv); historical lane references:
[reference.csv](../reports/medium_pilot/reference.csv). Event computation plus
real-data reference comparison and plots took **4.10 s**, peak **301,024 KiB**
([timing](../reports/medium_pilot/events_time.txt)).

Six outcome-stratified, real speed-time plots, including explicit missing/unusable
bins (grey bands and x markers at the axis baseline, not zero-speed imputations),
onset, prediction, recovery/follow-up boundaries and both thresholds:

- [60m recovered: c6b9fb6e53f2497c0f6a](../reports/medium_pilot/figures/event-c6b9fb6e53f2497c0f6a.png)
- [60m recovered: 7af917722bed1f2795f2](../reports/medium_pilot/figures/event-7af917722bed1f2795f2.png)
- [60m unrecovered: 77d490078ad446ce761e](../reports/medium_pilot/figures/event-77d490078ad446ce761e.png)
- [60m unrecovered: 2b2a3b441264146df51c](../reports/medium_pilot/figures/event-2b2a3b441264146df51c.png)
- [60m censored: f8bdd6cdab3beafdd1e0](../reports/medium_pilot/figures/event-f8bdd6cdab3beafdd1e0.png)
- [60m censored: 20ba1bb4d1d1225c1106](../reports/medium_pilot/figures/event-20ba1bb4d1d1225c1106.png)

Plots are deterministic first two examples per outcome, not random or
representative. Source validity, no-flow exclusion, archive delay, the unreviewed
ratio thresholds, outlier/default speeds and lane naming remain scientific risks.

## Full-pilot readiness and extrapolation

**Recommendation: technically reasonable to attempt the full coverage stage in a
controlled foreground run with monitoring, not a guarantee of end-to-end success.**
The 40-requested-detector benchmark is substantially larger than the prior
four-detector test and stayed under 333 MiB RSS, but neither full inventory
scanning nor later full-pilot stages have been benchmarked. Onset/event validation,
cohort representativeness, temporal/event separation, threshold sensitivity and
spatial matching remain gates before baseline ML.

A rough linear extrapolation from **38.50 s for 40 requested detectors × 3 days**
to the milestone-1 observed **782 detectors × 14 days** gives **~3,512 s / 59 min**
for coverage alone. The baseline includes fixed setup; detector/lane mix, file
ordering, cache, checkpoint verification, inventory discovery, I/O contention and
larger later stages can change this substantially. It is **not** an observed full
run duration. Similarly, extrapolating the ~1.65 GB extra logical reads gives
~151 GB plus checksum/inventory reads, not predicted physical disk reads.

The 0.927 MB medium coverage outputs scale linearly to roughly **85 MB** for the
same 782×14 detector-day assumption; allow **at least several hundred MB** for
transient day files, event tables, plots, manifests and nonuniform lane counts,
plus existing ~411 MB input Parquet, ~553 MB raw ZIPs and the ~484 MB road GML.
These are order-of-magnitude planning estimates, not measured full-output size.
Observed free disk at run time was **937 GiB**, but WSL limits and future
availability can differ. Memory scales with one detector group/day plus small
inventory and summaries, but a detector can have unusually many lanes or duplicate
records and the full `pilot.py` downstream stages have not been stress-tested.

After review and authorization, from the repository root, **do not background**:

```text
/usr/bin/time -v uv run --locked python -m traffic_recovery.data.pilot
```

It uses the unchanged `configs/pilot.json`, all eligible observed detectors during
coverage, and new `data/local/pilot/derived/compact-bounded-v1/` day checkpoints;
it does not reuse the benchmark's restricted 40-detector checkpoints or the old
interrupted `compact/`. If interrupted, rerun the identical command; inputs and
completed day outputs are hash-verified. It may fail if actual coverage filters
select no units, data assumptions fail, or downstream stages use more memory.
Inspect output/error and provenance before any claim of successful full processing.

## Reproduction and tests

Requires existing checksummed source Parquet and Linux/WSL2 for `/proc/self/io` and
`/usr/bin/time -v`. All commands are foreground; no new network requests:

```text
uv sync --locked
/usr/bin/time -v -o reports/medium_pilot/coverage_time.txt uv run --locked python scripts/medium_pilot.py coverage
/usr/bin/time -v -o reports/medium_pilot/events_time.txt uv run --locked python scripts/medium_pilot.py events
uv run --locked pytest -q
```

The coverage command reuses existing identical checkpoints on replay; choose a
fresh `--output` directory for an independent fresh benchmark. The events command
recomputes the small reference comparison, labels and figures. Current results:
`uv sync --locked` exit 0; **73 pytest passed in 4.37s**; `git diff --check` exit 0.
The medium helper's synthetic test checks that a corrupted label is rejected.
Native Windows and hosted CI were not run.
