# Long-window data access and separation from the short pilot

This dataset is 2023-01-01 through 2026-09-30 (HKT), 24 selected lane units and 7,597 events. PR #6 is the separate October 7–21, 2026 short pilot with 73 events. Never combine their event tables, cohort/reference fits, configurations or measured results.

Use `configs/long_window.json` and the long-window scripts exclusively for this study. Keep its data root separate from the short pilot root. See [long-window methods](long_window_data.md) and [measured results](../reports/long_window/README.md).

## Obtaining the prepared data

The prepared dataset is published as a [GitHub Release](https://github.com/CityuHK-wyj/hk-traffic-recovery-prediction/releases/tag/data-long-window-2023-2026-v1). Download the [prepared-data ZIP](https://github.com/CityuHK-wyj/hk-traffic-recovery-prediction/releases/download/data-long-window-2023-2026-v1/HK_Traffic_Long_Window_Prepared_Data.zip) (1,669,288,966 bytes, approximately 1.67 GB) and the adjacent `.sha256` asset. Collaborators can download it directly; access to the owner's D: drive is unnecessary.

Whole-ZIP SHA-256: `53688e6e095798f50c124376da1f0f354ca4b2aedf9e83e960fef04fc7298bc9`.

The release contains daily cleaned observations, five-minute bins, event labels, metadata, reports and a per-file SHA-256 manifest. The approximately 47.07 GB original archives are not included. The auto-generated Source code ZIP is a separate code snapshot and does not contain the prepared data.

Download that bundle from the Release page and extract into your own separate data root. It preserves `processed/derived/events.parquet`, `processed/derived/cohort_bins.parquet`, daily cleaned/binned Parquet files, `metadata/` and `reports/`. Verify the SHA-256 values in `SHARED_DATA_MANIFEST.json`. The shared package supplies prepared inputs, not raw ZIP archives or reusable ingestion checkpoints. Absolute provenance paths describe the owner's original run; they are not paths on your machine.

The bundle is approximately 1.64 GB of Parquet data before ZIP overhead/reports. GitHub Releases distribute binary assets separately from Git commits; the large bundle must not be committed to this branch.

## Independent reproduction

To rebuild independently instead of downloading the published prepared bundle, obtain all authentic source archives and reproduce the data using the commands in `long_window_data.md` (Python 3.12, locked dependencies). This downloads about 47.07 GB of compressed original archives and takes substantial processing time. Use your own data root instead of copying the owner's D: path literally. Original inputs remain traceable to the official DATA.GOV.HK archive.

The source code and small reports in this PR do not include large data, do not change the short-pilot configuration, and do not train models. All event definitions and split proposals remain provisional.
