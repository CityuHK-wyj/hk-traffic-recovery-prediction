# Integration and interface plan

## Scope and decision gates
The read-only explorer is independent of spatial modelling. Primary research path
is traffic-only. Directed spatial ablation is NO-GO unless Member 2 provides
independent evidence-backed, version-compatible, time-valid detector mappings and
transitions, and Member 4 verifies sufficient observed common-cohort coverage.
A geographic-proximity feature is not a directed network feature. Neither current
API nor frontend claims that six candidate pairs are verified.

Member 1 owns label/cohort gate; Members 1 and 4 jointly approve feature availability,
training-only baseline reference, event-level temporal splits and embargo before
fitting. Reference/threshold and medium pilot labels are provisional. If insufficient
data or review, report limitations rather than fabricate a model or result.

## Current HTTP contract (v0.1, local development)

All routes are read-only JSON; temporal strings are ISO-8601 offset-aware HKT.
`GET /api/health`: `{status, dataset, event_sha256, bin_partitions}`.
`GET /api/events?limit=100&offset=0`: `{dataset,total,items,notice}`. Limit
1–200; each item includes stable event/detector/direction/lane IDs, onset and
prediction times, termination reason and nullable integer `label_{15,30,60}m`.
`1` means observed recovery within horizon; `0` observed no recovery in horizon;
`null` censored/unknown, not zero. Rows are lane-level, not independent road events.

`GET /api/events/{event_id}` returns `{dataset,event,detector,predictions,notice}`.
`event` contains retrospective onset, reference, thresholds, recovery/followup and
label reasons from the source Parquet; `detector` gives current approximate lat/lon,
road and metadata direction with caveat. `predictions` currently exactly
`{status:"unavailable",reason:"No genuine trained model integrated.",values:null}`.
This **is not** an inference endpoint. Any future `available` contract must be a
reviewed joint API/UI change specifying values/units/horizons, model ID, fit and
prediction cutoffs, prediction artifact hashes and compatibility. UI cannot infer
probabilities from retrospective labels or synthetic data.

`GET /api/events/{event_id}/curve` returns `{event_id,grid_minutes:5,points,notice}`.
Each point contains time, availability, speed_kmh (nullable), usable, present/valid/
flow/offline/conflict slot counts. Missing bins are explicit with null speed and
unknown offline/conflict counts, not zero speed. Data after prediction time is
retrospective. Display raw unusable measurements only with usable=false; don't
interpolate as if observed. The server clips to the available event evaluation
window. 404 unknown event, 422 invalid paging, 503 evidence absent/checksum
mismatch/query schema failure. `/docs` provides route descriptions. Relative
`/api` uses the Vite local proxy. Sources/hashes are checked on each request.

## Data/artifact handoffs

1. Member 1 → Members 4/2: immutable input hashes, cohort/label definition version,
   lane/event ID, prediction time, reference cutoff, nullable labels and censor
   reasons, event group and split manifests, coverage and quality. Source evidence
   remains local; no large files in Git.
2. Member 2 → Member 4: mapping and transition records in exact
   `neighbor_features()` contract: independent reviewer and evidence, network
   version, historical validity, training reference cutoff and review status. Share
   eligibility/coverage report and limitations; pending never counts as verified.
3. Member 4 → Member 3: explicit model/prediction response contract and genuine
   out-of-sample artifact metadata, or unavailable. Reviewed mock responses remain
   clearly synthetic and never reach the real-data API as predictions.
4. Member 3 → team: reproducible UI commands, browser/OS/manual outcomes,
   accessibility and empty/error cases, screenshots only with source context.

Changes to shared `docs/data_contract.md`, endpoint schemas, dependencies/lockfiles,
common event keys, and definitions require a coordinated PR. Each member edits own
module and opens a draft PR; reviewers agree merging order. Preserve current working
changes; do not commit/push/merge unless authorized. Never commit local evidence,
credentials, node_modules or model binaries.

## Integration sequence and checks

1. PRs/tests run independently Oct 28–29. Member 3 consumes current API while 1/2
   validate data and 4 prepares evaluation design/tests.
2. Agree contracts and reviewed labels/splits; merge only with authorization and
   after `uv sync --locked && uv run --locked pytest`, `npm ci --prefix frontend`,
   `npm run build --prefix frontend`, and `npm audit --prefix frontend`.
3. Smoke local server/Vite with real checksummed evidence; separately manually test
   in target browsers including offline map behavior and errors. Verify no future
   data in model features, unknowns remain null, and only genuine predictions shown.
4. Run approved traffic-only experiments by Nov 4. Run matched-arm spatial ablation
   only after sign-off and adequate common sample; otherwise document NO-GO and
   show descriptive evidence. Poster Nov 6–7 includes provenance and limitations.

Known prototype risks: large frontend bundle, reliance on OSM external raster
service, map datum/historical location unverified, no authentication, no prediction
artifact registry, no interactive browser test in current environment, convenience
cohort bias and provisional thresholds. Local development only.
