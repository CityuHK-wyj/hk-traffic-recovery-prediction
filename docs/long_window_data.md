# Long-window data preparation (local, not uploaded)

This is Member 1's data-only extension of the existing short-window pilot.
The observation window is 2023-01-01 through 2026-09-30 inclusive (HKT).
Original monthly archives are retained for the entire official detector inventory.
An extra 2026-10-01 capture-day archive supplies the end-of-window boundary; it
does not extend the evaluation period.

## Analysis cohort and availability

The existing provisional coverage filters and 24-unit cap are unchanged. Cohort
selection uses **all lane/detector identities observed during January 1–7, 2023**,
not current metadata and not future event outcomes. One lane per detector/direction
is chosen by historical positive-flow and valid coverage, with deterministic ID
ordering for the cap. The 24-unit cohort is a limited study cohort, not a
representative sample of Hong Kong's whole road network.

All lanes of those selected detectors are ingested across all 45 months. Other
members can expand spatial coverage from the retained full-inventory raw ZIPs.
January 2023 supplies the historical speed reference; event evaluation begins
February 2023. Proposed folds: training through 2024, validation in 2025, test
January–September 2026. References, site selection and thresholds never use test
outcomes. The 85th-percentile January reference may drift over several years;
monthly coverage and censoring reports must be reviewed before model experiments.

Prediction availability follows the existing conservative bin-end +10-minute
archive closure. Only source captures available by closure enter feature bins;
later revisions do not retroactively alter those features. Event labels describe
witnessed sustained recovery confirmation, not exact physical recovery or verified
traffic-accident clearance. Missing follow-up stays unknown.

For this long-window handoff, the existing chronological split proposal receives
an additional conservative label-availability guard. Training/validation episodes
are purged if `max(prediction_time +70m, episode_separated_at +10m)` reaches the
next fit boundary. The extra ten minutes allows archive closure for the 60-minute
outcome. `outcome_maturity_at` is outcome metadata, never an input feature.

## Source integrity and official ZIP anomalies

Sources are the Transport Department raw lane feed and DATA.GOV.HK's historical
archive API. Monthly inventory entries are checked for expected dates, bytes and
XML entry counts. Each original object is downloaded through byte ranges pinned
to its ETag, with Content-Range validation, per-range SHA-256 and restart prefix
checks. Original ZIP bytes are never rewritten. Parsing validates each consumed
member's CRC. Source flags and integer/nonnegative measurement domains follow the
repository cleaner; missing and offline values are not zero-filled.

Some official monthly ZIPs contain **duplicate member names**. Their entry
positions are preserved as `#zip_entry=...` in source provenance. Each ZipInfo is
read directly: Python's filename-based lookup would otherwise silently choose
one version. Conflicting observation keys are quarantined; exact archive repeats
use earliest capture. `archive_check.json` records duplicate-entry counts.

Malformed/truncated XML is excluded with member position, error and SHA-256 in
the capture manifest; originals stay in the ZIP. Out-of-month capture entries in
official archives are retained in `YYYYMMDD-from-YYYYMM.parquet` partitions and
joined by internal observation time. Empty days produce typed empty tables and
zero coverage, without fabricated measurements.

The old first-January capture partitions were generated before duplicate-name
support. They are reused only after verifying the recorded output and source
hashes, unchanged parser/cleaner module, archived previous wrapper hash, and the
absence of any duplicate ZIP names in that archive. Their original generation
identities remain intact; compatibility checks are recorded separately.

## Reproduction

Use Python 3.12 and the committed dependency lock. In this project directory:

```powershell
uv sync --locked
uv run --locked python scripts/download_long_window.py --root D:/HK_Traffic_Recovery_Long_Window --workers 6
uv run --locked python scripts/download_long_window.py --root D:/HK_Traffic_Recovery_Long_Window --boundary-only
uv run --locked python scripts/prepare_long_window.py --root D:/HK_Traffic_Recovery_Long_Window --workers 4
uv run --locked python scripts/label_long_window.py --root D:/HK_Traffic_Recovery_Long_Window --workers 4
uv run --locked python scripts/verify_long_window.py --root D:/HK_Traffic_Recovery_Long_Window
uv run --locked pytest
```

The root can be any user-chosen directory. It is a CLI argument, not a hard-coded
path in the data code. Acquisition can overlap ingestion: preparation waits for
each archive's integrity checkpoint. Failures remain explicit in logs/manifests.

## Handoff files

- `metadata/`: authentic inventory, detector locations, official specification/schema.
- `raw/YYYYMM/`: unchanged ZIP, HTTP/range evidence and integrity checks.
- `selection/`: historical full-inventory selection evidence (not evaluation data).
- `processed/lane_snapshots/`: compact per-capture-day records, preserving versions.
- `processed/derived/cleaned-YYYYMMDD.parquet`: deduplicated, conflict-masked daily observations.
- `processed/derived/bins-YYYYMMDD.parquet`: provisional 5-minute positive-flow speed bins.
- `processed/derived/events.parquet`: one row per witnessed onset with 15/30/60-minute labels.
- `processed/derived/cohort_bins.parquet`: selected-lane time series for downstream features.
- `reports/`: measured coverage, reference/cohort, events, training-only threshold
  sensitivity, figures, checksums and final validation.

Raw intervals, 5-minute bins and events have different grains; do not present the
raw row count as a number of independent events. Occupancy and interval volume
are retained in cleaned observations; the existing speed-bin semantics are
unchanged. Full 30-second coverage and sparse usable 5-minute bins are different
metrics. All scientific definitions and fold assignments remain provisional.

No network/spatial implementation, external-context engineering or machine
learning is added by this extension. No remote branch, PR or merge is created.
