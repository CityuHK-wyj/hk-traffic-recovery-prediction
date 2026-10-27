# Authentic, bounded official-data evidence

These are **real Hong Kong Transport Department responses**, not synthetic test
fixtures. They were retrieved October 27, 2026. Source registry and provenance:
`docs/data_sources.md`, `reports/data_audit.json`, `reports/evidence/http/`, and
`reports/evidence/history_boundaries.json` (paths relative to repository root).

- `sample_20261019.xml`, `sample_20261020.xml`, `sample_20261021.xml`: original
  bytes from the first XML member of each daily raw archive (`0000` capture time).
  Archive members and original-byte SHA-256 values are recorded in the report's
  `archive_days` entries. Their observation dates begin the preceding evening.
- `cleaned_sample.csv.gz`: derived, losslessly compressed CSV of those three
  snapshots only: 12,503 rows after explicit conflict quarantine. It is **not**
  the full three-day audit and is not an ML-ready/labelled dataset.
- `raw_current.xml`, `segment_current.xml`: unchanged current raw/processed
  snapshots; original retrieval times in the response metadata distinguish them
  from archived sample observations.
- `detectors.csv`, `segments.csv`: unchanged current location/segment metadata;
  headers and directions are not assumed historically correct.
- `raw_schema.xsd`, `network_centerline_schema.gfs`: original source schemas.
- `earliest_raw.xml`, `earliest_segment.xml`: unchanged first-listed historical
  boundary responses. The raw file is empty; processed rows are all offline.
- `checksums.json`: byte sizes and SHA-256 checksums for the above evidence files.

Large original daily ZIPs and full road GML remain in ignored `data/local/`, not
Git. Re-fetch them with the documented CLI to reproduce aggregate statistics.
No source bytes have been corrected or imputed. The cleaned CSV is explicitly a
derivative and retains raw values and quality flags. Synthetic fixtures elsewhere
are explicitly labelled `TEST*` and must never be added as research observations.
