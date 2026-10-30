# Long-window data access and separation from the short pilot

This dataset is 2023-01-01 through 2026-09-30 (HKT), 24 selected lane units and 7,597 events. PR #6 is the separate October 7–21, 2026 short pilot with 73 events. Never combine their event tables, cohort/reference fits, configurations or measured results.

Use `configs/long_window.json` and the long-window scripts exclusively for this study. Keep its data root separate from the short pilot root. See [long-window methods](long_window_data.md) and [measured results](../reports/long_window/README.md).

## Obtaining the prepared data

The prepared data currently live on the data owner's computer. A local D: path is **not accessible to collaborators**. No hosted download link exists yet. The owner has a `HK_Traffic_Long_Window_Prepared_Data.zip` bundle, with daily cleaned observations, five-minute bins, event labels, metadata, reports and a SHA-256 file manifest. It can be distributed as a GitHub Release asset or through a shared drive. Until the asset is actually published, do not claim the repository includes this dataset.

Download that bundle from the owner and extract into your own separate data root. It preserves `processed/derived/events.parquet`, `processed/derived/cohort_bins.parquet`, daily cleaned/binned Parquet files, `metadata/` and `reports/`. Verify the SHA-256 values in `SHARED_DATA_MANIFEST.json`. The shared package supplies prepared inputs, not raw ZIP archives or reusable ingestion checkpoints. Absolute provenance paths describe the owner's original run; they are not paths on your machine.

The bundle is approximately 1.64 GB of Parquet data before ZIP overhead/reports. GitHub Releases distribute binary assets separately from Git commits; the large bundle must not be committed to this branch.

## Independent reproduction

If no prepared bundle is available, obtain all authentic source archives and reproduce the data using the commands in `long_window_data.md` (Python 3.12, locked dependencies). This downloads about 47.07 GB of compressed original archives and takes substantial processing time. Use your own data root instead of copying the owner's D: path literally. Original inputs remain traceable to the official DATA.GOV.HK archive.

The source code and small reports in this PR do not include large data, do not change the short-pilot configuration, and do not train models. All event definitions and split proposals remain provisional.
