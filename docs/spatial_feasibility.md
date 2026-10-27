# Hong Kong road-network and neighboring-traffic feasibility

## Decision: **NO-GO — verified spatial features are not yet reliable**

The official road data can be parsed into a useful **candidate directed subset**,
and real detector/road candidates can be generated. This assessment has **not**
verified any detector mapping or navigable upstream/downstream relationship for
historical use. Consequently **0 of 40** medium-pilot event rows have a permitted
verified spatial feature, and the dataset is **not ready for the traffic-only vs
traffic-plus-network ablation**. This is a verification/coverage blocker, not proof
that Hong Kong's road data or all potential matches are unusable.

The project can continue with a carefully validated traffic-only study while the
network owner reviews the evidence. Separately labelled geographic-proximity
features could be investigated later, but they must not be called upstream or
downstream. Do **not** close the spatial feasibility gate or start integrated
full-stack development on the assumption that the spatial experiment is ready.
No model training, frontend work, deployment, commit, push or merge was performed.

## Real sources and scoped pilot

- CENTERLINE: official [TD Road Network (2nd Generation)](https://data.gov.hk/en-data/dataset/hk-td-tis_15-road-network-v2),
  actual local `data/local/audit-20261019-21/network_centerline.gml`, **484,207,756
  bytes**, SHA-256 `4fad0303e65c759ac7abe8eea3920b3ffcfcd5149c978fa9540bf032933a32c2`.
  The digest is this analysis's network snapshot identifier, not an official
  historical network-version ID. Request metadata is retained in
  `reports/evidence/http/network_centerline.gml.meta.json`.
- Official TURN and INTERSECTION GML from the same catalogue were acquired via
  the government static endpoints and retained with response metadata in
  `data/local/pilot/network_http/`. All input hashes are in
  [quality.json](../reports/spatial_feasibility/quality.json).
- Detector locations/directions come from the current official TD metadata,
  `data/sample/verified/detectors.csv`, which uses HK1980 Grid Easting/Northing.
  Current metadata is **not** a verified historical detector-location snapshot.
- Traffic uses the existing three checksummed medium-pilot 5m bin partitions and
  the real 40-event Parquet. See [medium_pilot.md](medium_pilot.md); these are
  provisional lane-level labels with a two-day history, not the full study dataset.
- Scope is the **39 observed detector-direction units** from the medium pilot's
  first-40-ID convenience sample. The program retains actual road lines within
  500 metres of at least one of these detector coordinates. This corridor-biased
  sample includes Aberdeen/Wong Chuk Hang, the Canal Road/Waterloo corridor,
  Lion Rock Tunnel and Sha Tin; it is not representative of all Hong Kong roads,
  detectors, road classes, dense intersections or low-coverage areas. One
  deterministic lane per detector-direction is selected for mapping; the 40
  real event rows include other lanes and are not independent road events.

The network dataset's `DATA_LAST_UPDATED_DATE.csv` reports a **2026-10-08 revision
cut-off**, not proof that each route was valid on the October 18–20 traffic days.
The medium historical raw feed has no official detector-to-segment crosswalk.
The separately sampled current processed segment XML declares `irn_version`
**20221210**. The milestone-1 ID audit found **23 of 4,525** processed IDs absent
from the downloaded full CENTERLINE. In this subset, **38 of 39** selected
candidate route IDs occur among the sampled current processed IDs; candidate
`AID01202 -> 107699` does not. This is an identifier overlap check only, **not**
a detector match, a temporal version match or a spatial accuracy estimate.

## Directed graph construction and limitations

`src/traffic_recovery/network/feasibility.py` streams the actual 484 MB source
GML; it accepts EPSG:2326 LineStrings and continuous Curve LineStringSegments,
preserving source vertices, source `ROUTE_ID`, elevation, permitted direction,
record dates and WKB geometry. It does not reproject metre distances to degrees.
A rejected unexpected CRS, malformed geometry or noncontinuous curve is an
explicit error. Shapely and pandas suffice for this scoped analysis; no additional
GeoPandas or NetworkX dependency was needed.

The subset contains **3,197 source road segments**, with total source geometry
length **303,697.84 m**, and **4,017 directed arcs**. Source direction `1` creates
both orientations; `3` creates the digitised orientation only. The endpoint graph
has **2,709 nodes**, **156 weak components**, and a largest weak component of
**771 nodes**. Weak components ignore turn restrictions and direction and are
not legal-route reachability. Subset-buffer boundaries can artificially fragment
components. **223** endpoint coordinate pairs occur at more than one source
elevation; node keys retain elevation, so those are not merged. Interior geometric
crossings are never connected automatically. This also means genuine connections
requiring source-interior segment splitting can be missed.

Candidate transitions require matching 1 cm-rounded **source endpoints**, the
same elevation, correct arc directions, and are checked against the actual TURN
records. The subset overlaps **2,485** source intersection records and **950**
turn records. Of **7,146** candidate transitions:

| Automatic evidence category | Count | Interpretation |
|---|---:|---|
| Source INTERSECTION membership within 1 m, no conservative block | 4,952 | Source-supported **candidate**, manual movement review pending; not verified legal turns |
| Conservatively blocked by a TURN route pair | 1,100 | Algorithmically rejected; restrictions may be vehicle-, time-, orientation-, position- or path-specific |
| Same-route U-turn suppressed | 1,094 | Algorithmically rejected, not independently reviewed |
| Human-verified navigable connections | **0** | None reviewed/approved |

The conservative implementation blocks consecutive route pairs of multi-edge or
conditional restrictions without resolving fractional positions, time, vehicle
classes or orientation. It can therefore **over-restrict**. Conversely, absence
of a matching restriction is not proof a turn is lawful or complete. Actual
navigability, temporal validity and grade/surface details require independent
review against authoritative topology and applicable restrictions.

[connection_review_sample.csv](../reports/spatial_feasibility/connection_review_sample.csv)
contains **30** source-backed candidates: 15 intersection-supported pending
review and 15 conservative rejects; **16** touch automatically selected detector
arcs. Review statuses are deliberately `pending`: **0 verified, 15 ambiguous/
pending, 15 algorithmically rejected**, with no human decisions implied.
The complete candidate graph lives in ignored local
`data/local/spatial-feasibility/source_roads.parquet`, `directed_arcs.parquet`
and `directed_transitions.csv`. The first is WKB with an explicit `crs` column,
not GeoParquet CRS metadata. Source intersection and restriction extracts are
linked from [the output directory](../reports/spatial_feasibility/).

## Detector matching evidence

Candidate selection considers 50 m radius, the direction-specific local line
tangent (<=45° error), official permitted travel orientation, and whether the
source road name occurs in the detector description. A name-compatible candidate
is preferred, not merely the closest line; all 300 candidates and their attributes
are preserved. These are heuristic tolerances and name checks, not validation.

| Measure | Observed subset result |
|---|---:|
| Detector-direction units in scope | 39 |
| Automatically chosen directional/name-compatible candidates | **39 / 39 (100%)** |
| Unmatched by these permissive candidate rules | 0 |
| Candidate matches independently verified | **0 / 39 (0%)** |
| Ambiguous nearby compatible routes (within chosen distance +10 m) | 23 / 39 (59.0%) |
| Literal observed-feed vs current-metadata direction mismatch | 8 / 39 (20.5%) |
| Ambiguous **or** metadata-direction mismatch | 26 / 39 (66.7%) |
| Alternative route candidates / direction-incompatible | 300 / 162 |
| Selected candidate distance min / median / 90th percentile / max | 0.03 / 4.24 / 9.22 / 15.25 m |
| Selected local bearing error median / max | 22.20° / 43.78° |

All 39 chosen source names are substrings of their detector description under the
simple normalization; generic shared names and flyovers mean that is not proof of
correct carriageway or elevation. The metadata disagreement cases include
`AID01107` (observed North East vs current South East), `AID01109` (North East vs
North), and `AID01124` (North East vs South East). We do not know which direction
semantics are correct; no override is silently applied. Chosen matches include
parallel/flyover/tunnel risks, and detector placement may be off the actual sensed
carriageway. Nearby or name-compatible ≠ verified sensor-to-road mapping.

See [detector_mapping.csv](../reports/spatial_feasibility/detector_mapping.csv),
[all matching candidates](../reports/spatial_feasibility/matching_candidates.csv),
[overview map](../reports/spatial_feasibility/detector_map.png), and detailed
candidate review maps [1](../reports/spatial_feasibility/detector_review_1.png),
[2](../reports/spatial_feasibility/detector_review_2.png),
[3](../reports/spatial_feasibility/detector_review_3.png),
[4](../reports/spatial_feasibility/detector_review_4.png). Red arrows show the
observed compass direction, blue arrows the chosen candidate orientation; map
inspection here is **not** independent sign-off. All candidates carry network and
mapping version and `pending` review status; historical validity intervals are
unknown, not invented.

## Neighbor observations and event-level sample

Under the automatic, **unverified** mapping choices there are **6** directed
source-intersection-supported detector-pair candidates, recorded in
[candidate_detector_connections.csv](../reports/spatial_feasibility/candidate_detector_connections.csv).
Some detectors share a selected route, and proximity, a source intersection or
shared name does not establish their relation. These six are review leads, not
verified upstream/downstream pairs; no spatial feature is computed from them.

`src/traffic_recovery/network/spatial_features.py` implements a fail-closed
feature interface. A mapping and each directed transition must have explicit
`human_verified` status, nonempty reviewer, matching network version and
historically justified `[valid_from, valid_to)` interval. For approved neighbors,
it takes only same detector/direction/lane observations that are usable, at most
10 minutes old, and whose observation and archive-closure availability are no
later than prediction time. Future data is excluded. The neighbor reference must
be fitted no later than the explicitly supplied training cutoff. It computes
upstream/downstream mean speed, congestion fraction (ratio <=0.5), observed and
eligible detector counts, coverage among *reviewed mapped* neighbors, arc degree
and latest availability watermark. Missing speed/ratio remains null; zero is only
used for counts. No usable neighbor denominator produces null coverage.

The measured [local-versus-spatial table](../reports/spatial_feasibility/spatial_features_review.csv)
contains **40 real events**, their original local speed/ratio/reference, and
explicitly null neighbor measurements with `mapping_unverified`. The Parquet sample
is `data/local/spatial-feasibility/spatial_features.parquet`. **0 detectors** have
verified usable upstream observations, **0** have verified usable downstream
observations, and **0 / 40 event rows** qualify for spatial comparison under the
review gate. These are counts of currently *verified usable* items, not a claim
that the actual network has no neighbors or observations. Numerical neighbor
feature calculation is covered only by labelled synthetic tests; it has not been
demonstrated on independently verified real relationships. There is no silent
proximity-based fallback or fabricated feature value.

## Validation, performance and reproduction

`uv run --locked python -m traffic_recovery.network.verify_feasibility` passed
checks on **3,197** road geometries, **4,017** directed arcs, **7,146** candidate
transitions, **39** candidate mappings and **40** event rows. It recomputes source
endpoint/elevation keys, direction permissions, line lengths, TURN blocks, INTERSECTION
membership/position, candidate match distance/bearing, hashes and the all-null
unreviewed feature output. Results: [automated_checks.json](../reports/spatial_feasibility/automated_checks.json).
These are **automated source-field invariants**, not independent manual verification
of navigability, historical validity or match correctness.

The latest foreground construction run exited 0 in **20.45 seconds**, peak RSS
**482,560 KiB** (~471 MiB), no swaps, on the observed WSL2 environment; detailed
measurement: [runtime.txt](../reports/spatial_feasibility/runtime.txt). The
program streams original GML once and loads only the small subset plus already
validated medium bin outputs; it does not reread historical XML or rescan the
large traffic partitions. Local derived files are approximately 15 MB (excluding
preserved initial-run copies); portable review output is approximately 2.7 MB.
No new network requests were made.

From the repository root, with the previously acquired source evidence and medium
pilot outputs present:

```text
uv sync --locked
/usr/bin/time -v -o reports/spatial_feasibility/runtime.txt uv run --locked python -m traffic_recovery.network.feasibility
uv run --locked python -m traffic_recovery.network.verify_feasibility
uv run --locked pytest -q
```

`/usr/bin/time -v` is Linux/WSL-specific; the Python path handling is portable.
The program re-generates derived outputs and leaves original evidence and
checkpoints untouched. Source acquisition and medium-pilot reproduction are in
[data_sources.md](data_sources.md) and [medium_pilot.md](medium_pilot.md).
Latest actual checks: `uv sync --locked` exit 0, **80 pytest passed in 4.76s**,
`git diff --check` exit 0. Synthetic tests cover directional one-way/bidirectional
arcs, grade separation, TURN blocking, CRS and Curve handling, fail-closed review,
missingness, 10-minute as-of availability, frozen training-reference cutoff and
future-leakage prevention. Native Windows and hosted CI remain unverified.

## Required next verification before changing the decision

1. Member 2 independently reviews the map, 30 sampled transitions, ambiguous
   parallel-road cases and mismatched directions against versioned official
   evidence; record reviewer, method, explicit decision and effective interval.
2. Confirm graph topology/turn restrictions (including time, class, multi-edge,
   fractional-position and grade-separated cases) and detector carriageway mapping
   for a *sufficiently connected* set. Review historical version compatibility.
3. Re-run the feature builder on that approved subset; quantify actual observed
   upstream/downstream coverage and eligible events, with leakage checks and the
   same event rows for both ablation arms.
4. Member 1/4 review the provisional labels, fit references, event separation,
   horizon embargo and sample bias. Quantify censoring and threshold sensitivity.
   Only then reconsider a limited or full spatial-modelling GO.

Poster limitations: narrow geographically biased subset, current-vs-historical
metadata/version uncertainty, lane and direction disagreements, ambiguous
parallel roads/flyovers, conservative/incomplete turn graph, sparse traffic
coverage, publication lag, provisional thresholds and censored event labels.
