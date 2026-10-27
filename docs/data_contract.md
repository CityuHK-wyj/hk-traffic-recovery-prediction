# Shared data contract — initial proposals, version 0.1

**Status:** Only TD traffic parsing/cleaning and audit reports are implemented.
Other tables below are proposed interfaces, not claims about available data.
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

## 3. Congestion events and recovery labels — PROVISIONAL, not implemented

Prediction unit is unresolved: direction-specific detector aggregate versus matched
road segment. Use `segment_id` only after its semantics and mapping are verified.

| Field | Proposed type | Meaning / constraint |
|---|---|---|
| `event_id` | string, primary key | Stable hash/ID from unit, onset and event-definition version |
| `segment_id` or `detector_id`, direction | string | Exactly one approved unit definition per dataset version |
| `onset_time` | aware datetime | First confirmed congestion onset under reviewed rules |
| `recovery_time` | nullable aware datetime | First **confirmed** sustained recovery time; future outcome, never a feature |
| `event_end`, `censored_at` | nullable aware datetime | Follow-up boundary / observation censoring |
| `definition_version`, `censor_reason` | string | Mandatory rule version; explicit unknown/insufficient coverage reason |

Proposed event-prediction table key: `(event_id, prediction_time)`. Add
`prediction_time`, elapsed congestion/severity known at that time, `label_15m`,
`label_30m`, `label_60m` (nullable Int8 in {0,1}), and per-horizon censor reasons.
Keep the entire event and its prediction rows within a single split.

### WITHIN is not AT

For an eligible still-congested prediction at time `t`, let `T` be the first
confirmed sustained recovery **after t**. Proposed target:

`label_h = 1 iff t < T <= t + h`, for h in {15,30,60} minutes.

This is **recovered at any qualifying time within the window**, even if congestion
recurs before its endpoint. It is NOT `is_recovered(t+h)`. A vehicle/road recovering
at t+10 and congesting again at t+14 is positive within 15 minutes, but may be
negative under an endpoint-state definition. A recovery exactly at t+h is included.

A proposed sustained-recovery rule would require consecutive sufficiently covered
samples. If confirmation needs multiple intervals, `T` is the confirmation time,
not a retrospectively backdated start that uses data beyond the horizon. Duration,
thresholds, free-flow reference, hysteresis, onset/end persistence, recurrence
merging, maximum permitted gaps and eligible prediction frequency are **unfixed**.
They require a measured pilot, training-only estimation where applicable, rationale
and sensitivity analysis. This milestone does not produce events or labels.

`label_h = 0` requires adequate observable follow-up to exclude qualifying recovery
through t+h; otherwise null/censored. Data ending before a horizon, gaps or offline
periods must not automatically become negative examples. Known confirmed recovery
may support a positive without complete later follow-up, subject to approved rules.
For jointly observed labels enforce `label_15m <= label_30m <= label_60m`.

## 4. Road network and spatial features — PROVISIONAL

| Table / key | Proposed fields and types |
|---|---|
| Segments: `(network_version, segment_id)` | `segment_id` maps to source CENTERLINE `ROUTE_ID` (string-normalized); geometry LineString EPSG:2326; `length_m` float; source `TRAVEL_DIRECTION` int; `ELEVATION` int; source/update dates; lineage |
| Detector mapping: `(mapping_version, detector_id, direction, segment_id)` | `network_version`, `valid_from/to` datetimes; method string; distance_m float; directional/manual-review status; ambiguity reason; source metadata hash |
| Directed adjacency: `(network_version, from_segment_id, to_segment_id)` | relation string (upstream/downstream); distance_m float; turn-restriction evidence; construction version |
| Dynamic spatial features: `(segment_id, prediction_time, feature_version)` | Neighbor speed/volume summaries, neighbor count, coverage, `available_at` and source watermark |

Observed `TRAVEL_DIRECTION` values are 1 (both directions) and 3 (digitised direction
only), not compass bearings. Respect grade separation and turn restrictions; do not
connect crossing lines blindly. Current segment IDs and network versions have
mismatches. An ID overlap is not spatial matching accuracy. No claimed reliable
matching exists yet; static topology also requires a version/time-validity policy.

## 5. External contextual features — PROVISIONAL, sources unverified

Proposed key: `(segment_id, prediction_time, context_version)`; source-specific
staging keys include station/incident/holiday IDs and observation/effective times.
Fields: weather variables with declared units, holiday/category, incident/closure
indicators and distance; each carries `observed_at`, `issued_at/available_at`,
validity interval and source URL/hash. Optional features may be entirely absent.

Join by documented spatial assignment and a **backward as-of availability join**,
with maximum age/tolerance and explicit missingness. No nearest future weather,
retrospectively updated incident end time or post-event parking counts as features.
Known-in-advance calendar data needs an official version, not invented holidays.

## 6. Final ML-ready dataset — PROVISIONAL

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

## 7. Experiment metrics — PROVISIONAL, no results yet

Proposed long-form key `(run_id, split, horizon_min, feature_set, model, metric_name)`.
Fields: `metric_value` nullable float; `n_rows`, `n_events`, `n_positive`, `n_censored`
integers; prevalence; decision threshold/selection policy; dataset/config/lock hashes;
seed; commit + dirty state; split dates; software versions; runtime; recorded_at UTC.
Metric names may include precision/recall/F1, ROC-AUC, PR-AUC and calibration; decide
from imbalance and research protocol, not assumed results. Undefined single-class
metrics are null with a reason, never zero. Proposed intervals use event-aware
resampling and a documented method. Report results per horizon and paired spatial
ablation, including coverage and exclusions. No metric is populated by this milestone.
