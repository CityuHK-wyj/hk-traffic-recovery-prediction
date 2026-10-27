# Official data source register

Audit retrieval date: **October 27, 2026**, UTC times retained per response.
All sources below were requested over real HTTP, not inferred from descriptions.
Request URLs, final redirect targets, status, headers, sizes and SHA-256 values:
[`../reports/data_audit.json`](../reports/data_audit.json),
[`../reports/evidence/http/`](../reports/evidence/http/).
Local full bodies: `data/local/audit-20261019-21/` (ignored). Small authentic
samples and checksums: [`../data/sample/verified/`](../data/sample/verified/).

## A. TD — Traffic Data of Strategic / Major Roads

[Official catalogue](https://data.gov.hk/en-data/dataset/hk-td-sm_4-traffic-data-strategic-major-roads)
returned HTTP 200. It links these resources, all retrieved with HTTP 200:

| Resource | Verified endpoint / evidence | What actually returned |
|---|---|---|
| Raw detector traffic | [rawSpeedVol-all.xml](https://resource.data.one.gov.hk/td/traffic-detectors/rawSpeedVol-all.xml) | Root `raw_speed_volume_list`, `date`, `periods/period`, `period_from`, `period_to`, `detectors/detector`, `detector_id`, `direction`, `lanes/lane`, `lane_id`, `speed`, `occupancy`, `volume`, **`s.d.`**, `valid` |
| Detector metadata | [traffic_speed_volume_occ_info.csv](https://static.data.gov.hk/td/traffic-data-strategic-major-roads/info/traffic_speed_volume_occ_info.csv) | UTF-8 BOM CSV; `AID_ID_Number,District,Road_EN,Road_TC,Road_SC,Easting,Northing,Latitude,Longitude,Direction,Rotation`; 807 unique detector rows |
| Processed road speed | [irnAvgSpeed-all.xml](https://resource.data.one.gov.hk/td/traffic-detectors/irnAvgSpeed-all.xml) | Root `segment_speed_list`; `date,time,irn_version`; segments with `segment_id,speed,valid`; 4,525 segment rows in current snapshot |
| Segment catalogue | [speed_segments_info.csv](https://static.data.gov.hk/td/traffic-data-strategic-major-roads/info/speed_segments_info.csv) | **`irn_id,ucase(route)`**, 4,255 unique IDs; does not enumerate all 4,525 current processed IDs (285 absent) |
| Data specification | [official PDF](https://static.data.gov.hk/td/traffic-data-strategic-major-roads/dataspec/dataspec-traffic-data-strategic-major-roads.pdf) | Downloaded and text-extracted for inspection; raw section dated Nov 30, 2022, processed section May 20, 2021 |
| Raw schema | [SpeedVolOcc-BR.xsd](https://static.data.gov.hk/td/traffic-data-strategic-major-roads/info/SpeedVolOcc-BR.xsd) | Retrieved schema, retained in curated sample; pipeline validates used fields, not a full XSD validation engine |

### Units and semantics

The PDF explicitly specifies speed in km/h, occupancy as percentage of time a
zone is occupied, 30-second periods (two per file), and Y/N online/offline flags.
It names volume but **does not explicitly state the volume unit**. Observations
are integer-valued per lane/interval; `volume_count` is a cautious normalization,
not a verified conversion to hourly vehicle flow. Speed SD has tag `s.d.` in the
actual XML, whereas the PDF labels it `sd`.

The PDF calls the detector metadata ID `Device_ID`, but actual CSV is
`AID_ID_Number`. It describes segment metadata with `segment_id` and road name,
but the live CSV headers are `irn_id` and `ucase(route)`. Adapters must verify
schema on each retrieval rather than silently force the PDF's column names.

Raw detector IDs include `AID...` and `TDS...` with longer alphanumeric variants;
never assume a fixed ID length. Raw observations have **no segment ID**. The
processed feed supplies segment IDs but not detector IDs, volume or occupancy.
No official detector-to-segment crosswalk was found in these downloaded resources.

Locations include HK1980 Grid Easting/Northing, coordinates also named Latitude/
Longitude, compass Direction and Rotation. The examined PDF does not explicitly
state the latitude/longitude datum or establish Rotation as a road travel bearing.
Eight compass categories occur, but some traffic/metadata directions disagree.
Do not assume an exact reliable matching relationship without further validation.

## B. DATA.GOV.HK Historical Archive API

[Official specification](https://data.gov.hk/en/help/api-spec) returned HTTP 200.
The documented timezone is **GMT+8** and the latest archive is described as yesterday.
Verified base URL: `https://app.data.gov.hk/v1/historical-archive/`.

| Action | Request parameters | Verified behavior |
|---|---|---|
| `list-files` | `start,end` YYYYMMDD inclusive; filters such as `provider=hk-td`, `search`; `skip` for pagination | HTTP 200 JSON, `file-count`, `files`; four associated traffic resources found. Source URLs must be encoded when passed to other actions. |
| `list-file-versions` | `url,start,end` | HTTP 200 JSON with `timestamps`, `version-count`, `total-size`; actual response also includes packaged `data-files`, `timestamps-zip`, `total-size-zip`, etc. **Only 10,000 individual timestamps returned**; broad queries are truncated. Use day partitions. |
| `get-file` | `url,time` | Date-only `time=20261019` redirected to official historical archive storage and downloaded a daily ZIP; `time=YYYYMMDD-HHMM` from the returned version list downloaded an individual XML. Preserve final URL rather than constructing storage paths. |

Example exact daily request:

```text
https://app.data.gov.hk/v1/historical-archive/get-file?url=https%3A%2F%2Fresource.data.one.gov.hk%2Ftd%2Ftraffic-detectors%2FrawSpeedVol-all.xml&time=20261019
```

Successful ZIP redirect host observed:
`historical-resource-archive-daily.oss-cn-hongkong.aliyuncs.com`.
This is a government-API redirect target, not a substituted third-party dataset.
ZIP members contain URL-encoded directory names; the pipeline reads members
without extracting them to OS paths.

**Coverage distinctions:**
- Broad queries through Oct 21 report 2,161,940 raw versions and 1,387,868 processed
  versions. First returned stamps: raw `20210329-0908`, processed `20210330-0909`.
  These are archive inventory bounds, **not usable-data start dates**.
- Individual boundary downloads verify that the first raw file has empty detector
  lists and that the first processed file has 63 rows, all `valid=N`.
- A separate raw request for `20261026-2359` retrieved and parsed 4,164 rows.
  See [`../reports/evidence/history_boundaries.json`](../reports/evidence/history_boundaries.json).
- All 3,121 raw archive snapshots for Oct 19–21 were downloaded and parsed.
  Continuity/quality for other dates and processed historical sequences is unverified.

No API key or authentication was required in this environment. No government
endpoint request failed with a network/authentication error during this audit.
Empty/offline content and conflicting keys are **data-quality failures**, not HTTP
unavailability. Future access is not guaranteed; preserve exact failure bodies if
that changes. The client records HTTP errors, retries 429/5xx/network errors with
bounded backoff and timeout, and rejects unexpected JSON/XML/empty content.

## C. TD — Road Network (2nd Generation)

[Official catalogue](https://data.gov.hk/en-data/dataset/hk-td-tis_15-road-network-v2)
returned HTTP 200. Downloaded actual resources:

- [File list](https://static.data.gov.hk/td/road-network-v2/dataspec/file_list.csv), CSV.
- [Data specifications ZIP](https://static.data.gov.hk/td/road-network-v2/dataspec/rdnet_dataspec.zip), containing FGDB, GML and KML PDFs. Inspected GML specification dated March 17, 2025.
- [CENTERLINE schema](https://static.data.gov.hk/td/road-network-v2/CENTERLINE.gfs),
  EPSG:2326, expected ID/direction/geometry attributes.
- [CENTERLINE.gml](https://static.data.gov.hk/td/road-network-v2/CENTERLINE.gml),
  **484,207,756 bytes**; streamed actual features, not just catalogue metadata.

Verified 36,525 features / unique `ROUTE_ID`s; fields include `OBJECTID`,
`STREET_ENAME`, `STREET_CNAME`, `ELEVATION`, `ST_CODE`, `ROUTE_ID`,
`TRAVEL_DIRECTION`, `CRE_DATE`, `LAST_UPD_DATE_V`, `SHAPE_Length`, aliases and
route/exit information. CRS is **EPSG:2326** in both GFS and GML envelope.
`TRAVEL_DIRECTION` is 1 (both directions) or 3 (digitised direction only), consistent
with the examined GML specification. These are not compass direction categories.

The traffic PDF defines processed `segment_id` as road `CENTERLINE.ROUTE_ID`.
Actual key comparison found 4,502 current processed IDs in the downloaded network
and **23 absent**. Current traffic XML declares `irn_version=20221210`; the network
resource is mutable and version reconciliation remains unresolved. Key overlap
is not a spatial matching success rate or connectivity validation.

Catalogue links also advertise TURN, INTERSECTION, SPEED_LIMIT and other GML/KMZ
resources plus a File Geodatabase ZIP. These were **not downloaded or validated**
in this milestone. Graph construction and turn/grade-separated connectivity remain
Member 2's next task. GeoPandas and NetworkX are intentionally not installed yet.

## Optional contextual data

Weather, holidays, incidents/closures, parking and attractions have **not** been
verified in this milestone. They remain optional research candidates, not dependencies
or claimed available features. Member 3 must preserve equivalent evidence and
prediction-time availability semantics before they enter the data contract.

## Source use and fallback

Attribute Transport Department and DATA.GOV.HK; review applicable government
terms and any per-resource notices before redistribution/publication. The curated
sample is authentic evidence, not a substitute for checking source terms.
If automated archive retrieval later fails, use the official portal's daily/monthly
historical downloads or contact the provider with the exact failed request. A
prospective official-feed collection is legitimate but cannot recreate past data;
a narrower verified period is preferable to synthetic replacement.
