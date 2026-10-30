# Member 1 handoff: real traffic data and provisional labels

This change is limited to acquisition, preprocessing, coverage, events and labels.
It does not add model training, external-context integration or spatial evaluation.
Existing model software belongs to the downstream team. Any earlier local model
smoke run is excluded from this handoff and is not a research result.

## Actual scope and results

- Official raw traffic archives: October 7–21, 2026 inclusive capture days;
  15 ZIPs, 15,391 snapshots, 553,336,695 bytes. This is a short pilot, not the
  January 2023–September 2026 study proposed earlier.
- Select the first 40 current detector-metadata IDs lexically before inspecting
  recovery outcomes. This convenience sample is not geographically representative.
- All 15 selected-detector partitions were parsed: 3,031,553 rows before
  cross-partition deduplication and the observation-window coverage filters.
- Reuse the repository's existing cleaning, conflict, availability, coverage,
  historical-reference and episode rules; do not relax thresholds to obtain events.
- The original pilot selects a maximum of 24 detector/direction lane units after
  coverage checks. It produced 73 provisional event rows: 55 train, 5 validation,
  13 test. These counts are event rows, not proven independent road incidents.
- Known test labels are only 12 per horizon; positives are 1, 2 and 2 for 15/30/60
  minutes. Validation has only 5 rows and no positive 15-minute label.
  This is a dataset handoff and workflow demonstration, not a sufficient final
  empirical cohort or evidence that any model is good.

Measured summaries and source hashes are in `reports/selected_data_pilot/`.
Large original/derived files stay local. Missing and censored observations are
not converted to zero. Two source-selection regression tests compare filtered
parsing with the unchanged full parser using explicitly synthetic fixtures.

## Reproduce from the repository root

Use Python 3.12 and `uv sync --locked`. Replace `DATA_ROOT` with a local path;
commands accept Windows or Linux paths without source edits.

```text
uv run --locked python scripts/download_desktop_pilot.py --root DATA_ROOT
uv run --locked python scripts/prepare_selected_pilot.py --root DATA_ROOT --count 40 --workers 3
uv run --locked python scripts/run_selected_pilot.py --root DATA_ROOT --count 40
uv run --locked pytest
```

The preparation helper filters detector XML elements before applying the original
repository parser/cleaner. Original ZIP bytes remain authoritative. A selection
manifest records metadata hash, selected IDs and helper hash; daily ingestion
checks source/output hashes before reuse. Coverage uses the same explicit subset.
No network or context relationship is inferred by this helper.

Local outputs:

- `raw/`: original ZIPs, complete daily version lists and HTTP evidence;
- `metadata/`: detector locations, official specification and schema;
- `processed-40/lane_snapshots/`: compact source-linked partitions;
- `processed-40/derived/events.parquet`: provisional event/label handoff;
- `reports/pilot-40/`: coverage, cohort, sensitivity, event curves and manifests.

Scientific approval remains pending. The team must review reference/thresholds,
event independence, clock/availability semantics, and splits, and expand the
validation/test cohort before a final study. Members 2–4 retain their network,
external/baseline and ensemble/evaluation work; this change does not complete it.
