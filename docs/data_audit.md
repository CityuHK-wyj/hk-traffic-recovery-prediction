# Real-data feasibility audit — milestone 1

**Decision:** GO for a **coverage-filtered pilot**, not yet GO for finalized recovery
labels, spatial matching or full-scale ML. Real historical retrieval and parsing
work. Temporal coverage, validity, publication delay, ambiguous lanes and network
version mismatches materially affect the research design.

Audit date: **October 27, 2026**. Primary numerical evidence:
[`reports/data_audit.json`](../reports/data_audit.json). Source definitions and links:
[data_sources.md](data_sources.md). Reproduction commands: [README](../README.md).
This report contains measured data-quality statistics, **not model performance**.

## What actually ran

Real HTTP GETs retrieved the three official pages, live raw and processed XML,
detector/segment CSVs, traffic PDF/XSD, road file list/specification ZIP/GFS, the
full CENTERLINE GML, archive resource/coverage listings and three daily raw ZIPs.
All these government requests succeeded with HTTP 200 after automatic redirects
where relevant; no authentication or credentials were needed. Bodies, response
metadata, retrieval times and checksums were preserved. No synthetic research
observations were used. See the response manifest and
[`reports/evidence/http/requests.jsonl`](../reports/evidence/http/requests.jsonl).

A broad historical query was followed by complete **daily partitions**, avoiding
the API's 10,000-timestamp cap. The first day ZIP was downloaded as a discovery
probe, then the remaining two consecutive days were retrieved. The full network
resource was inspected by streaming actual CityGML features. It was unexpectedly
large (484.2 MB); subsequent reproduction makes this download opt-in.

## Verified historical sample

Archive dates below are **capture dates in Hong Kong time**, not exact observation
date boundaries. All listed XML versions in each ZIP were processed.

| Archive date | Listed and parsed snapshots | ZIP bytes | Source XML bytes |
|---|---:|---:|---:|
| 2026-10-19 | 1,044 | 35,963,886 | 734,226,070 |
| 2026-10-20 | 1,029 | 37,001,446 | 725,910,124 |
| 2026-10-21 | 1,048 | 37,904,710 | 742,711,746 |
| **Total** | **3,121** | **110,870,042** | **2,202,847,940** |

- **12,935,754** source lane-period rows; **782** observed detectors.
- **6,064** conflicting rows (3,032 proposed observation keys) quarantined;
  **12,929,690** retained rows. Zero within-snapshot exact duplicates.
- **2,120** distinct `(detector_id, direction, lane_id)` series in retained data.
- Retained observation period ends span
  **2026-10-18 23:53:30 through 2026-10-21 23:53:00, Asia/Hong_Kong**.
- Every retained observation interval is 30 seconds. This does **not** mean the
  archive sampled continuously at that frequency.
- Cleaned export is only the **first snapshot per day**, totaling **12,503** rows,
  not the full 12.9-million-row audit. It is saved as CSV locally and losslessly
  gzipped under `data/sample/verified/cleaned_sample.csv.gz` for Git.

### Broader availability is not usable coverage

The query 2010-01-01 through 2026-10-21 reports 2,161,940 raw and 1,387,868
processed versions. Both individual timestamp arrays are truncated to 10,000.
First returned versions are `20210329-0908` and `20210330-0909`, respectively.
Those are inventory bounds only; no multi-year continuous observation claim follows.

Boundary downloads were also actually performed:
- First raw version: HTTP 200 XML, **empty detector lists**, parser reports
  `Empty traffic dataset`. Not a network error and not usable training data.
- First processed version: HTTP 200, **63 rows, all offline (`valid=N`)**; all
  cleaned speeds missing. This is not usable evidence of traffic in March 2021.
- `20261026-2359` raw version: HTTP 200, **4,164** parsed rows; observation end
  2026-10-26 23:53:00+08:00, four offline rows.

Exact requests, outcomes and checksums:
[`reports/evidence/history_boundaries.json`](../reports/evidence/history_boundaries.json).
Other periods' usable coverage and historical processed sequences remain unverified.

## Field quality and invalid values

Counts below use the **12,929,690 retained per-snapshot rows**, after full-key
conflict quarantine. Missing input numeric tags are treated as schema failures,
not silently converted to missing values. Present blank/null strings are missing.

| Measurement | Blank/null raw values | Numeric-domain invalid | Missing after validity masking |
|---|---:|---:|---:|
| Speed | 0 | 0 | 150,272 (**1.1622%**) |
| Occupancy | 0 | 12,640 | 162,827 (**1.2593%**) |
| Volume | 0 | 0 | 150,272 (**1.1622%**) |
| Speed SD | 0 | 0 | 150,272 (**1.1622%**) |

150,272 rows were explicitly offline; no unknown validity codes were observed.
Occupancy violations exceed the physical [0,100] percent domain. Invalid occupancy
and offline counts can overlap, so their union is not their simple sum. The cleaner
preserves raw values/flags, masks invalid normalized measurements and never turns
missing values into zero. No arbitrary maximum-speed cutoff is imposed.

**Conflicting keys:** first seen at archive version `20261020-1204`, detector
`TDS90026`, West, `Middle Lane`, each of two period ends. For 11:57:30, for example,
one source row reports speed 66 and another 43 for the same proposed key. This
may indicate non-unique lane naming; physical lane identity is not established.
The original strict audit exited 1, with errors preserved in
[`reports/evidence/initial_failure.json`](../reports/evidence/initial_failure.json)
and `initial_failure_trace.txt`. The completed audit explicitly quarantines **all**
variants and records examples. It does not average or arbitrarily select them.

**Only the 12,503-row exported sample:** speed median 76 km/h, 95th percentile
112 km/h, maximum **235 km/h**. These are not full-period quantiles and midnight
snapshots are not representative of congestion. There are 3,177 valid zero-volume
rows, 3,172 with positive speed. Online status does not guarantee a fresh physically
meaningful speed under no flow. Investigate defaults, outliers and volume units
before choosing thresholds. No congestion or recovery threshold was finalized.
Reproducible details: `reports/evidence/cleaned_sample_profile.json` and
`scripts/profile_sample.py`.

## Temporal coverage and prediction-time availability

- Only **6,242** distinct period-end times were present among **8,640** expected
  30-second slots between global observation extrema: **2,398 absent time slots**.
- Across each series' own observed first/last bounds, there were **18,126,651**
  expected slots and **5,196,961 absent**: **28.6703% missing series slots**.
- This is not an uptime estimate against the entire detector inventory. It excludes
  missing periods before/after each series' bounds; source-invalid rows still occupy
  time slots. Actual usable speed coverage is worse than presence coverage alone.
- Gap histograms in JSON are based on **sorted observation times**, not capture
  arrival order. Some later archive files contain earlier observation times.
  A bounded recent-key cache detects repeats/conflicts; compact per-series times
  are retained for chronological gap accounting. Very late records (>10 minutes
  behind the stream watermark) fail rather than silently evade duplicate detection.
- Archive capture minus latest contained observation: **300 seconds (289 files),
  360 (2,114), 420 (711), 480 (7)**. This measures archive lag, not exact producer
  publication latency; the largest observed single-series gap is over 22 hours.

### Consequences for 15/30/60-minute labels

1. A one-minute-ish capture does not provide continuous 30-second observations.
   Recovery transitions may occur inside gaps; first recovery time can be
   interval-censored. Aggregation needs explicit coverage/persistence criteria.
2. A 5–8 minute delay is large relative to the 15-minute target. Replaying a
   prediction at observation end while using that snapshot would overstate timely
   knowledge. Agree a real-time/archived-availability policy before experiment design.
3. Missing/offline intervals, unobserved detectors, ambiguous lanes and follow-up
   ending before a horizon must not become negative labels automatically.
4. Recovery **within** a horizon differs from being recovered **at its endpoint**;
   recurrence and sustained confirmation must be specified. See the contract.
5. Detector-to-segment aggregation can change event timing. Do not finalize a
   detector-based threshold and later silently treat it as segment ground truth.
6. Train/validation/test need chronological and event-level isolation, purged
   outcome windows and training-only reference estimation. A three-day audit is
   not a defensible complete training/validation/test research period by itself.

## Spatial feasibility

- Current detector metadata: **807** rows / unique IDs, zero duplicate IDs and
  zero rows missing any of the four coordinate fields. All 782 historical observed
  IDs exist in current metadata; 25 current IDs were not seen in the historical
  sample. This does not establish historically correct locations/directions.
- In the **exported sample only**, **135 of 779 distinct detector-direction pairs**
  disagree literally with current metadata Direction (e.g. AID01107 North East
  versus South East). No claim is made about which is correct or whether one
  represents camera orientation versus road travel; do not override blindly.
- CENTERLINE: **36,525** unique routes; no duplicate IDs; EPSG:2326; direction
  codes 1 (11,555 features) and 3 (24,970). Elevation and turn constraints matter.
- Current processed XML: **4,525** segment rows with version `20221210`; 46 offline.
  The downloaded network contains **4,502** of these IDs; **23 absent**. The
  associated segment CSV has 4,255 IDs and misses 285 current processed IDs.
- **No detector-to-road spatial matching or directed graph was performed.**
  No matching accuracy/success rate is reported. Raw IDs have no direct segment
  crosswalk in the verified resources. Geometry/direction/version reconciliation
  and manually checked ambiguous matches are next-stage gates.

## Storage and reproducibility

Measured three-day raw archive: **110.87 MB ZIP**, **2.203 GB source XML** (decimal).
Linear 30-day extrapolation: **1.109 GB ZIP**, **22.03 GB XML**, excluding network,
processed/context data, replicas and derived outputs. This is a date-specific
estimate, not a retention guarantee. Streaming ZIP parsing avoids expanding all
source XML to disk; only small cleaned snapshots are retained. Full network GML
adds **484.2 MB**. Future processed storage must be measured on a selected cohort.

Local originals are never modified. `reports/data_audit.json` embeds a response
manifest; `reports/evidence/http/` holds API listings/metadata/logs. The initial
probe responses were copied byte-for-byte into the audit evidence store with their
original retrieval times and hashes; nonessential cookie headers were omitted.
`--reuse` accepts only identical URL + successful status + matching checksum.
It does not silently reuse a different date range or overwrite raw responses.

## Verification and remaining gates

Offline parsing, timezone/midnight behavior, raw/processed schema validation,
exact/conflicting duplicates, missingness, invalid measurements, validity masks,
paths with spaces/Unicode, recorded source checksums, transport retries/error
preservation and chronological gap accounting are covered by pytest.
Actual final commands/results are recorded in [verification.md](verification.md).
GitHub Actions is configured for Ubuntu/Windows Python 3.12; **native Windows
has not been executed locally and remains pending CI**. The local environment
identifies itself as Ubuntu 26.04 on a Microsoft WSL2 kernel, so WSL2 execution
is verified, not native Windows or hosted GitHub Actions.

Next milestone: select a modest adequately observed cohort/period; resolve ambiguous
lane IDs and metadata/version/direction mismatches; measure event/recovery candidate
rules and censoring; approve label and split contracts with all four members. Only
then implement a simple local baseline and a controlled spatial ablation. Optional
context sources need their own audit. No training, dashboard or infrastructure was
started here.
