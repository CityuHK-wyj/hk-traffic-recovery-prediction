# Shared data contract — pilot interfaces, version 0.2 (review pending)

**Status:** TD parsing/cleaning, incremental Parquet coverage, provisional lane
congestion/recovery labels and a small spatial matching pilot are implemented.
These pilot interfaces are **not team-approved final scientific definitions**.
Changes in this version require Member 1/2/4 review before ML adoption. External
context, dynamic spatial features and final ML/metrics tables remain proposals.
Owners/review process: [ownership.md](ownership.md). Verified field differences and
limitations: [data_sources.md](data_sources.md), [data_audit.md](data_audit.md).
Do not promote a proposal to stable until source records and owner handoffs pass review.

## Global conventions

- IDs are strings, including numeric-looking road IDs; do not strip leading zeros.
- Internal datetimes are timezone-aware **Asia/Hong_Kong** (UTC+08:00). CSV writes
  explicit offsets; readers must parse with `pd.to_datetime(..., utc=True)` then
  `.dt.tz_convert("Asia/Hong_Kong")`, not leave naive local timestamps.
- `timestamp` = observation period **end**, `period_start` = interval start.
  `archive_time` = archive version/capture time, `retrieved_at` = this project's
  retrieval time in UTC. Neither is silently interchangeable with observation time.
- `prediction_time` = time at which a decision could actually be made. Candidate
  feature observations must end by it **and be available by it**. Sample archives
  lag observations by 5–8 minutes: treating period end as immediate availability
  would be invalid. An archive-time replay is a conservative candidate, not a
  verified exact publication-time model. Keep that policy in each dataset manifest.
- Raw source intervals are 30 seconds per lane, two periods per snapshot. Archive
  capture spacing is irregular. A downstream 1- or 5-minute grid is **provisional**;
  resampling must preserve coverage counts, never silently interpolate long gaps.
- Numeric missingness is pandas nullable NA; CSV uses empty cells, JSON uses null
  (never NaN). Zero remains an observed zero. Source-invalid and numeric-invalid
  reasons remain separate. Unknown label is null, never a negative example.
- Raw/source values and derived values must be distinguishable. Preserve original
  bytes and per-resource URL, checksum, retrieval time, source/version timestamps.
- Coordinates: official detector Easting/Northing use HK1980 Grid; road GML/GFS
  explicitly use **EPSG:2326**, metres. Detector latitude/longitude are provided,
  but their datum is not explicitly stated in the examined PDF: EPSG:4326 export
  is a proposal requiring verification. Never use degrees for metre distances.
- Versioned manifests must list source hashes, parser/schema version, sampling,
  exclusions, availability rule and any fitted transformations. No implicit joins.

## 1. Raw traffic observations (source-preserving adapter)

Original XML bytes are authoritative. The parser flattens without aggregating.

### Raw lane feed — verified XML paths

| Field | Internal type | Origin / constraint |
|---|---|---|
| `detector_id` | string, required | `periods/period/detectors/detector/detector_id` |
| `direction` | string, required | Detector `direction`; observed eight compass labels |
| `lane_id` | string, required | `lanes/lane/lane_id`; lane names, not stable global IDs |
| `period_start` | aware datetime | Derived from root `date` and `period_from` |
| `timestamp` | aware datetime | Derived from `date` + `period_to`; midnight rollover handled |
| `speed_raw` | string | Lane `speed`; specification: integer km/h |
| `occupancy_raw` | string | Lane `occupancy`; percentage of interval occupied |
| `volume_raw` | string | Lane `volume`; specification calls it traffic volume, no explicit unit. Treat as a source interval count, vehicle/count semantics still to confirm; **not vehicles/hour** without justification. |
| `sd_raw` | string | Actual XML tag `s.d.`; PDF calls this `sd`; speed SD, km/h inferred from speed |
| `valid` | string | Y = online, N = offline; unknown/blank is flagged |
| `source_file`, `archive_time` | string, aware datetime | Added by audit export; archive member and version time |

Proposed logical observation key: `(detector_id, direction, lane_id, timestamp)`.
**Not globally guaranteed unique**: verified conflicting Middle Lane records for
TDS90026. Never add a positional lane number and pretend its physical meaning is
verified. Strict cleaning raises; the audit explicitly quarantines every variant
of a conflicting key and counts it. Lane identities/that detector need review.
Archive version + source position provides provenance identity even when the
proposed scientific key is ambiguous. Raw originals remain unchanged.

### Processed segment feed — separate, verified adapter

| Field | Type | Source |
|---|---|---|
| `segment_id` | string | `segments/segment/segment_id` |
| `timestamp` | aware datetime | Root `date` + `time` |
| `irn_version` | string | Root `irn_version` (current sample: `20221210`) |
| `speed_raw`, `valid` | string | Segment `speed` (float km/h) and Y/N flag |

Logical key within one network version: `(segment_id, timestamp)`; consolidated
multi-version storage must include `irn_version`. There is **no volume, occupancy,
lane ID or detector ID** in this processed feed. Do not invent those joins.

## 2. Cleaned traffic observations (implemented lane/segment adapters)

Retain raw fields and add:

| Field(s) | Type | Validation / derivation |
|---|---|---|
| `source_valid` | bool | True only for `valid == "Y"` |
| `speed_kmh` | nullable float | Nonnegative finite source speed; raw lane feed requires an integer |
| `occupancy_pct` | nullable float | Raw lane only; integer in [0,100] |
| `volume_count` | nullable float | Raw lane only; nonnegative integer-valued count; unit caveat above |
| `speed_sd_kmh` | nullable float | Raw lane only; finite, nonnegative |
| `{speed,occupancy,volume,sd}_missing_raw` | bool | Raw field blank/null |
| `{speed,occupancy,volume,sd}_invalid_numeric` | bool | Nonfinite, unparseable, negative or violated field bounds/type |

Only speed flags exist for processed segments. Offline/unknown validity masks
all normalized measurements even if the raw number looks plausible. Exact
identical rows collapse and are counted; conflicting keys raise unless the caller
explicitly requests full-key quarantine. Missing tags/columns, missing keys,
naive/wrong-zone times and nonpositive intervals fail validation.

No speed upper bound/congestion threshold is imposed. Occupancy >100 is a physical
percentage-domain violation, not a congestion definition. No imputation yet.

**Proposed downstream additions:** `segment_id` plus versioned mapping provenance,
`available_at`, aggregation `valid_lane_count`, `expected_lane_count`,
`coverage_fraction`, `quality_reason` and aggregation version. Aggregation of lane
speeds/volume/occupancy and detector-to-segment assignment remain unresolved.
Do not silently average mismatched directions or treat offline lanes as zero flow.

Public implemented APIs:
- `parse_traffic(payload: bytes) -> DataFrame`: raw lane or processed segment XML.
- `clean_traffic(frame, *, conflicts="raise") -> (DataFrame, dict)`: validates a
  copy and returns counts; explicit `"quarantine"` is used by the audit.
- `EvidenceClient.fetch/json`, `list_versions`: evidence-preserving acquisition;
  listings are partitioned by date to avoid silent 10,000-result truncation.

## 3. Implemented pilot coverage, bins, events and labels — PROVISIONAL

**Unit:** `(detector_id, direction, lane_id)`, not a road segment or a detector
aggregate. Exactly one historical-coverage-ranked lane per detector/direction is
selected. No lane-to-road or detector-to-segment equivalence is implied.
Configuration: [`configs/pilot.json`](../configs/pilot.json). Measured results and
rationale: [milestone2.md](milestone2.md). Freeze requires team review.

### Files and measurement rules

- `data/local/pilot/lane_snapshots/YYYYMMDD.parquet`: compact source-linked rows,
  raw-value signature, archive availability and explicit conflict flags. Original
  XML ZIPs remain authoritative. Ingestion reads at most 32 snapshots/batch.
- `derived/coverage_lane_day.parquet`: one observed-inventory lane/day, including
  absent days. Denominator **2,880** 30-second interval ends per full HKT day.
  Offline fraction is reported against both present and expected slots. Conflict
  variants are all quarantined, identical repeats use earliest capture. Daily and
  full-period missing gaps include edges and multi-day outages. Inventory is the
  union of observed lane units, not a verified historical detector/lane register.
- `derived/cohort_bins.parquet`: right-closed 5m bins `(t-5m,t]`, no interpolation.
  `present_slots`, `valid_slots`, `flow_slots`, `offline_slots`, `conflict_slots`,
  `repeat_rows` are counts, never inferred zeros for missing measurements.
  `speed_kmh` is the median of source-valid speed slots with positive interval
  volume. `usable` requires at least **two** such unique slots and no conflicts.
  This is a sparse-sampling rule (as little as 20% of 30s slots), **not 90/95%
  continuous observation coverage**. `valid_5m_coverage` only requires two valid
  speed slots; `usable_5m_coverage` additionally applies positive-flow/conflict rules.
- Feature-bin `available_at = bin_end + 10 minutes`, a fixed conservative archive
  replay closure. Only captures at or before closure enter bin deduplication or
  aggregation. `last_source_available_at <= available_at`; no retrospectively
  observed late correction can alter an already closed feature bin. This is not a
  verified producer publication latency. Raw-quality profiling retains late rows.
- Cohort filtering uses only days before `selection_end`; the baseline fits only
  `[observation_start, reference_end)` with **both** observation and availability
  before the fit boundary. Reference is each lane's positive-speed 85th percentile
  of usable positive-flow 5m medians, minimum 300 bins. It is a provisional normal
  speed reference, not a verified posted/free-flow speed. No validation/test fit.

### Event state machine and table

`derived/events.parquet` has one prediction per event; key `event_id`. All times
are aware HKT. Definition version: `lane-observed-confirmation-v1`.

| Field | Type / meaning |
|---|---|
| `event_id`, unit keys | Stable rule/unit/onset hash; string detector/direction/lane |
| `onset_time` | First low bin in a witnessed two-bin onset run |
| `onset_confirmed_at` | Second low bin end, never a future-derived backdate |
| `prediction_time` | Onset confirmation bin availability (bin end +10m) |
| `feature_max_available_at` | Source/derived feature availability watermark, <= prediction |
| `speed_kmh`, `speed_ratio`, `baseline_kmh`, `valid_slots`, `onset_observed_minutes` | **Only dynamic/numeric feature allowlist**; baseline is fitted history, duration is witnessed onset bins ×5m, not the true physical episode duration |
| `recovery_time` | Nullable **observed confirmation bin end** of first three consecutive usable high bins; outcome, never feature |
| `recovery_available_at` | Archive availability of that outcome bin, separate from observed recovery time |
| `followup_end` | Last uninterrupted usable observation bin end before recovery, missingness or period end |
| `termination_reason` | `recovered`, `missing_or_invalid_bin`, `period_end` |
| `episode_separated_at` | Recovery end or later witnessed rearming after censoring; split-only outcome, not a positive-label override |
| `label_{15,30,60}m` | Nullable Int8: 1/0/NA, with `reason_{h}m` |
| ratios, persistence counts, `definition_version`, `reference_fit_end` | Mandatory provisional-rule/fit provenance |
| `split_proposal` | `train`, `validation`, `test`, `purged`; not a finalized evaluation assignment |

An initially low/unknown state is left-censored, not a fresh onset. Arm onset only
following three consecutive usable recovery-ratio bins. Two consecutive bins at
speed/reference <=0.5 confirm onset. Three consecutive bins >=0.8 confirm recovery;
intermediate speeds keep an active episode open. Missing/invalid bins immediately
right-censor follow-up and disarm onset; later recovery can establish separation
but does not repair unknown earlier outcomes. A censored episode requires witnessed
recovery before rearming. After every event require new onset and strictly more
than 60 minutes between predictions on the same lane; suppress whole onsets during
embargo rather than shifting them later. No same-unit overlapping label windows.
Different detectors may still share roads/events; no statistical independence claim.

### WITHIN is not AT

For prediction `t` and witnessed sustained confirmation `T`:
`label_h = 1 iff t < T <= t+h`. Confirmation is **not backdated** to the first high
bin. A positive stays positive if congestion recurs before the horizon endpoint;
recovery exactly at the deadline counts. Outcomes may arrive after the horizon:
their observed confirmation time, not retrieval time, defines the target. The 10m
prediction lag is shorter than the minimum 15m recovery run, so the earliest
qualifying post-onset confirmation cannot already precede prediction. The builder
rejects a lag that violates this condition.

A negative requires uninterrupted usable follow-up through `t+h` with no qualifying
confirmation. A missing timestamp, offline bin, insufficient positive-flow slots,
conflict or data end before the horizon yields NA, never automatic 0. Earlier
fully observed horizons can remain 0 when longer horizons are censored. A confirmed
recovery permits 1 without follow-up after that recovery. All jointly known labels
are monotone. These labels concern sampled 5m sustained confirmation, **not proof
that no unobserved physical recovery occurred between source observations**.

## 4. Road network and spatial features — PROVISIONAL pilot, review pending

| Table / key | Proposed fields and types |
|---|---|
| Segments: `(network_version, segment_id)` | `segment_id` maps to source CENTERLINE `ROUTE_ID` (string-normalized); geometry LineString EPSG:2326; `length_m` float; source `TRAVEL_DIRECTION` int; `ELEVATION` int; source/update dates; lineage |
| Detector mapping: `(mapping_version, detector_id, direction, segment_id)` | `network_version`, `valid_from/to` datetimes; method string; distance_m float; directional/manual-review status; ambiguity reason; source metadata hash |
| Directed adjacency: `(network_version, from_segment_id, to_segment_id)` | relation string (upstream/downstream); distance_m float; turn-restriction evidence; construction version |
| Dynamic spatial features: `(segment_id, prediction_time, feature_version)` | Neighbor speed/volume summaries, neighbor count, coverage, `available_at` and source watermark |

Observed `TRAVEL_DIRECTION` values are 1 (both directions) and 3 (digitised direction
only), not compass bearings. Respect grade separation and turn restrictions; do not
connect crossing lines blindly. Current segment IDs and network versions have
mismatches. An ID overlap is not spatial matching accuracy. The implemented pilot
in `network/pilot.py` uses source EPSG:2326 lines and detector grid coordinates,
50m radius, local +/-10m tangent, 45-degree compass tolerance and a 10m ambiguity
margin. These tolerances are provisional. Export all candidates, selected route,
distance, bearing error, metadata disagreement, ambiguity and unmatched status.
No match is certified before manual review/version reconciliation.

`roads.parquet` holds source attributes and `geometry_wkb` (not GeoParquet CRS
metadata; consult spatial manifest). `directed_arcs.parquet` has F/R route arcs,
source direction codes and endpoint nodes rounded to 1cm plus source elevation.
Candidate transitions require **shared endpoints**, never interior crossings or
nearby detectors. Source TURN consecutive restricted route pairs are conservatively
blocked, including multi-edge/conditional restrictions without pretending to solve
path/time/vehicle conditions. U-turns are excluded. Fractional-position restrictions
and source INTERSECTION memberships are exported for review; this is an incomplete,
over-restricted endpoint graph, **not a validated routing/upstream network**.
Current metadata/network versions remain unresolved; no spatial ML features exist.

**Spatial feasibility extension, awaiting Member 1/2/4 review:**
[spatial_feasibility.md](spatial_feasibility.md) records the source-backed subset,
candidate maps and connection review table. `network/spatial_features.py` accepts
only explicit `human_verified` mappings and directed transitions with reviewer,
matching `network_version`, and a documented `[valid_from, valid_to)` interval.
It uses a fixed, aware training-reference cutoff; latest usable same-lane/direction
neighbor bins must both end and be available by prediction time and be no older
than the configured tolerance. Unavailable means null speed/ratio; zero observed
neighbors is a count, not an imputed traffic value. Coverage is observed divided
by the **reviewed mapped-neighbor** count, null when that denominator is zero;
it is not population-wide road coverage. Arc degree counts reviewed transitions
only. Duplicate approved neighbor lanes are rejected rather than silently averaged.
The medium real-event output contains **only null spatial measurements** until
independent mapping/topology review and historical-version approval. A candidate
or source-supported connection is not a `human_verified` connection.

## 5. External contextual features — IMPLEMENTED ADAPTERS, scientific use pending

The prediction-time adapters and their synthetic behavior tests are implemented;
official source audit decisions, staging schemas and acceptance gates are recorded
in [external_features.md](external_features.md) and
[external_data_source_audit.md](external_data_source_audit.md). No real external
feature cohort has been produced, and conditional sources remain optional.

Key: `(event_id, prediction_time, context_version)`; source-specific
staging keys include station/incident/holiday IDs and observation/effective times.
Fields: weather variables with declared units, holiday/category, incident/closure
indicators and distance; each carries `observed_at`, `issued_at/available_at`,
validity interval and source URL/hash. Optional features may be entirely absent.
Unknown active-incident closure state keeps `active_road_closure_count` null and
sets `active_road_closure_status_missing`; it is never converted to zero.

Join by documented spatial assignment and a **backward as-of availability join**,
with maximum age/tolerance and explicit missingness. No nearest future weather,
retrospectively updated incident end time or post-event parking counts as features.
Known-in-advance calendar data needs an official version, not invented holidays.

## 6. Final ML-ready dataset — IMPLEMENTED BUILDER, approval pending

`configs/experiment_contract.json` and `traffic_recovery.models.contract` implement
the event key, nullable-label checks, temporal boundary checks, feature allowlist,
availability watermarks and cohort/config fingerprinting. See
[experiment_contract.md](experiment_contract.md). The underlying scientific event
and split definitions remain pending Member 1/4 review.
Each feature family activates its required watermark column; protected features
without their availability evidence fail validation rather than passing silently.

`traffic_recovery.models.dataset` implements exact one-to-one event/context/spatial
merges, allowlist pruning and SHA-256 manifests. Its interface and reproduction
command are documented in [model_dataset_and_benchmarks.md](model_dataset_and_benchmarks.md).

Key `(dataset_version, event_id, prediction_time)`; one row per approved unit-time.
Required: unit ID/direction, source watermark, feature schema version, nullable
three labels + censor masks, `split` enum {train,validation,test}, observed/derived
numeric/categorical features and coverage/missingness indicators. Labels, event end,
recovery time and future-derived durations live in outcome columns, excluded by an
explicit feature allowlist. Keep a separate manifest mapping feature names to source,
units, calculation window, fit period and availability rule.

Chronological train/validation/test dates are selected only after coverage checks.
No random row split. Do not split the same event across folds. Purge events/rows
whose label windows cross boundaries (at least the 60-minute maximum horizon), and
review overlapping events, shared roads and feature windows. Fit scalers, imputers,
feature selection and free-flow reference only on permitted training observations.
Local-only/spatial ablations must use identical eligible rows, splits and tuning
budgets. Document detector/road reuse and any spatial generalisation claim separately.

## 7. Experiment metrics — BENCHMARK PIPELINE IMPLEMENTED, no real results yet

Proposed long-form key `(run_id, split, horizon_min, feature_set, model, metric_name)`.
Fields: `metric_value` nullable float; `n_rows`, `n_events`, `n_positive`, `n_censored`
integers; prevalence; decision threshold/selection policy; dataset/config/lock hashes;
seed; commit + dirty state; split dates; software versions; runtime; recorded_at UTC.
Metric names may include precision/recall/F1, ROC-AUC, PR-AUC and calibration; decide
from imbalance and research protocol, not assumed results. Undefined single-class
metrics are null with a reason, never zero. Proposed intervals use event-aware
resampling and a documented method. Report results per horizon and paired spatial
ablation, including coverage and exclusions. No real-cohort metric is populated by
this milestone.

Stage 4 implements majority-class, training-prevalence and predeclared
`speed_ratio` rule predictions plus long-form classification metrics. Undefined
single-class metrics are null with a reason; non-probability rule scores do not
receive Brier or log-loss values. Configuration and commands are documented in
[model_dataset_and_benchmarks.md](model_dataset_and_benchmarks.md). No synthetic
test metric is a research result.
