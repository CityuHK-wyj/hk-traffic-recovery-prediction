# External context feature integration v1

The implemented adapters build prediction-time-safe features from preserved source
tables. Source feasibility and official citations are recorded in
[`external_data_source_audit.md`](external_data_source_audit.md); tolerances and
source-family decisions are versioned in `configs/external_features.json`.

No external raw data are committed. The adapters do not claim that optional source
coverage exists for every event. Missing from a selective incident or major-event
feed means "not observed by that source", not proof of absence.
The calendar, incident and major-event outputs therefore include explicit
`*_source_observed` or `*_records_observed` indicators alongside counts.

## Common event input

All builders require unique, nonempty `event_id` and aware `prediction_time`.
Weather additionally requires `weather_station_id`; incident and major-event joins
require a pre-reviewed `segment_id`. The integration builder returns exactly one
row per event and adds `context_version`.

## Source staging tables

Every nonempty staged source table also requires `source_url`, aware
`source_retrieved_at`, and a 64-character `source_sha256`. These fields identify
the preserved source response; the pipeline additionally hashes each complete
staged Parquet file. Numeric identifiers are rejected rather than coerced to
strings, so lost leading zeroes cannot pass validation unnoticed.

Calendar rows require `holiday_id`, Hong Kong civil `local_date`, `holiday_name`
and aware `available_at`. Only a calendar edition already published by prediction
time contributes to holiday, day-before or day-after features.

Weather rows require `station_id`, `observed_at`, `available_at` and declared value
columns. `available_at` cannot precede observation time. Selection is backward by
station and availability, constrained by an explicit maximum observation age. No
future or bidirectional nearest join is supported.

Incident rows are versioned snapshots keyed by `incident_id`, with `segment_id`,
`available_at`, `effective_start`, nullable `effective_end`, `distance_m` and
`is_road_closure`. For each prediction the latest already-available snapshot is
selected before testing whether the incident is active. Later CLOSED/end updates
therefore cannot rewrite earlier feature rows.
If an active record has unknown closure state, the closure count remains missing
and `active_road_closure_status_missing` is true; unknown is never counted as zero.

Major-event rows require `major_event_id`, `segment_id`, edition `available_at`,
`start_time`, `end_time` and `distance_m`. Active/upcoming/recent windows are
configurable. Only editions published by prediction time are eligible; final
post-event dates, venues or attendance must not be backfilled.

## Pilot source decisions

- GO: official 1823 general-holiday calendar.
- GO for checked archive window: HKO temperature and wind snapshots.
- Limited GO: archive-backed Transport Department Special Traffic News, with
  explicit spatial-match uncertainty.
- Conditional: rainfall replay, roadworks completeness and curated major-event
  editions.

Conditional groups remain optional until authentic preserved bytes, a source
manifest, parser tests, coverage measurement and an availability proof pass the
acceptance gate in the source audit.

## Offline verification

`tests/test_external_features.py` uses explicitly synthetic records to verify
civil-date handling, backward weather joins, incident snapshot replay,
publication-time filtering, distance tolerances and one-row-per-event integration.
Synthetic fixtures demonstrate behavior only and are never research evidence.

After source-specific parsers produce the five staged Parquet inputs, build and
fingerprint the integrated table with:

```text
uv run --locked python -m traffic_recovery.external.pipeline --events data/local/pilot/derived/events.parquet --holidays data/local/external/holidays.parquet --weather data/local/external/weather.parquet --incidents data/local/external/incidents.parquet --major-events data/local/external/major-events.parquet --output data/local/external/event_context.parquet --manifest reports/local/external-context-manifest.json
```

The command refuses to overwrite outputs and hashes every input, the configuration
and the resulting Parquet. An explicitly empty staged source is allowed and remains
distinguishable through missing/observed indicators.
