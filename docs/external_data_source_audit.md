# External context source audit

**Audit date:** 2026-10-28

**Scope:** official Hong Kong sources for calendar/public holidays, weather,
incidents/roadworks and major events. This is a source-feasibility decision, not
evidence that any feature has already been integrated or validated.

## Decision summary

| Feature family | Pilot decision | Reason |
|---|---|---|
| Calendar | **GO** | The official 1823 calendar is machine-readable and covers the 2026 pilot year. Preserve the retrieved version and use Hong Kong local dates. |
| Temperature and wind | **GO for the archive-backed pilot window** | DATA.GOV.HK historical snapshots exist at useful sub-hourly frequency for the checked 2026-10-19 to 2026-10-21 period. Coverage and actual observation-to-archive lag still need measurement. |
| Rainfall | **CONDITIONAL** | The official live API has the required observation semantics, but archive retrieval for query-parameter APIs was not established in this audit. Use only if exact historical responses can be replayed or independently preserved. |
| Weather warnings | **GO with warning-history intervals; CONDITIONAL for live-API snapshots** | HKO publishes an official historical warning database, but the live API describes only warnings currently in force. Preserve issue/cancel times and do not backfill later verification state. |
| Special Traffic News (STN) | **GO for a limited archive-backed pilot** | Historical archive versions were directly verified for the checked three days. The feed is textual and selective, so spatial matching needs uncertainty and missing cannot mean no incident. |
| Roadworks | **CONDITIONAL** | The official geospatial feed is narrowly scoped and only two archive versions were found in the checked three days. Treat it as incomplete context, not a complete absence indicator. |
| Major events | **CONDITIONAL** | Official calendars exist, but they are curated, mutable subsets rather than a complete versioned event register. Use only editions demonstrably published before prediction time. |

All candidates remain subject to the project rule `available_at <= prediction_time`
and a backward as-of join. A date or start time inside a file is not proof that the
file was already available then.

## Shared access and licence conditions

DATA.GOV.HK permits free browsing, downloading, distribution and reproduction for
commercial and non-commercial purposes, provided the source, Government/relevant
organisation ownership and DATA.GOV.HK are attributed. The data are supplied
"AS IS" without a guarantee of accuracy, completeness, timeliness or continued
availability; the terms may change. Store the terms/version checked with the run
manifest and attribute each provider in reports. See the official
[DATA.GOV.HK Terms and Conditions, version 1.2](https://data.gov.hk/en/terms-and-conditions).

The official historical archive API retrieves previous file versions, uses GMT+8,
and says the latest historical data are from the previous day. It exposes a file
listing, version listing and `get-file` download endpoint. Archive capture time is
therefore a conservative `available_at` candidate, not proof of the provider's
exact publication latency. See the official
[Historical Archive API specification](https://data.gov.hk/en/help/api-spec).

For every accepted source preserve original bytes, requested and final URLs,
response headers/status, retrieval time, archive version time, checksum, schema
version and parser version. Re-check per-resource notices before redistribution.

## 1. Calendar and public holidays

### Recommended source and semantics

Use the Digital Policy Office/1823
[Hong Kong Public Holidays dataset](https://data.gov.hk/en-data/dataset/hk-dpo-statistic-cal),
which is updated yearly and currently covers 2025--2027. The English resource is
the official [1823 JSON calendar](https://www.1823.gov.hk/common/ical/en.json).
Its [data specification](https://www.1823.gov.hk/datagovhk/statistics/1823_cal_dictionary.pdf)
defines calendar timezone metadata and `vevent` properties including `dtstart`,
`dtend`, `dtstamp`, `uid` and `summary`; `dtstamp` is the component's last revision
time. Keep the raw event values and derive `is_public_holiday` only after converting
`prediction_time` to `Asia/Hong_Kong`.

The 1823 public-holiday page says its data follow the Gazette and that the next
year is normally updated within two weeks after gazettal around May. It also
explains that when a holiday falls on Sunday, only the gazetted substitute holiday
is listed. See [1823 Hong Kong Public Holidays iCal](https://www.1823.gov.hk/en/hong-kong-public-holidays-ical).
The general-holiday calendar must not be silently substituted with the separate
[Labour Department statutory-holiday list](https://www.labour.gov.hk/eng/news/holidays_list.htm),
because the concepts and legal coverage differ.

### Availability and leakage controls

- Store the retrieved calendar bytes and `retrieved_at`; the archive API returned
  no versions for the checked JSON resource and period, so do not assume automatic
  historical versioning.
- Calendar date, weekend, hour and pre-declared holiday features are safe only when
  sourced from a version published by prediction time. Later corrections must not
  be retroactively applied to old predictions.
- Join by Hong Kong civil date, never by the UTC date of `prediction_time`.

## 2. Weather observations and warnings

### Temperature and wind

HKO's regional temperature dataset is provisional, updated every ten minutes and
contains the latest one-minute mean air temperature. The current CSV has
`Date time`, station and temperature in degrees Celsius; see the official
[dataset catalogue](https://data.gov.hk/en-data/dataset/hk-hko-rss-latest-one-minute-mean-air-temp)
and [live CSV](https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/latest_1min_temperature.csv).

HKO's wind dataset is provisional and updated every ten minutes. Its CSV contains
observation time, station, ten-minute mean compass direction, ten-minute mean speed
and maximum gust in km/h; see the official
[dataset catalogue](https://data.gov.hk/en-data/dataset/hk-hko-rss-latest-ten-minute-wind-info)
and [live CSV](https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/latest_10min_wind.csv).

Direct historical-archive checks for 2026-10-19 through 2026-10-21 found:

- temperature: **433** versions, first `20261019-0009`, last `20261021-2358`;
- wind: **432** versions, first `20261019-0009`, last `20261021-2358`.

These figures are reproducible with the official
[`list-file-versions` API](https://app.data.gov.hk/v1/historical-archive/list-file-versions)
using each live CSV URL plus `start=20261019&end=20261021`. They establish archive
inventory, not usable station coverage or exact producer publication time.

Use archive capture as `available_at`, retain the source `Date time` as
`observed_at`, and compute `weather_age_minutes = prediction_time - observed_at`.
Join only the latest observation whose archive capture is no later than prediction
time, with an explicit maximum age. Never use nearest/bidirectional joins, future
interpolation or a later corrected file.

### Rainfall

The official HKO
[past-hour rainfall dataset](https://data.gov.hk/en-data/dataset/hk-hko-rss-rainfall-in-the-past-hour)
is updated every 15 minutes. It is the automatic-weather-station rainfall measured
over the one-hour period **ending at the observation time**; HKO calls it
provisional and warns that the Hong Kong Observatory station value differs from
the climatological database and some bulletins. The official endpoint is
[`hourlyRainfall.php?lang=en`](https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en),
documented in the
[HKO Open Data API specification](https://data.weather.gov.hk/weatherAPI/doc/HKO_Open_Data_API_Documentation.pdf).

Because the historical archive check for this query-parameter endpoint returned
404, its historical replay was **not established** here. Do not replace it with a
final daily rainfall total: a same-day total includes observations after an
intraday prediction and leaks the future. Admit rainfall only after an exact
archive URL/version method or a source-preserving prospective capture is verified.

### Weather warnings

The HKO warning-information API provides details of warning signals **currently in
force** and updates when a warning changes; it is not itself documented as a
historical query. See the official
[warning-information resource](https://data.gov.hk/en-data/dataset/hk-hko-rss-weather-warning-information/resource/65718d0c-b363-49f7-accb-3797e967a73f).

For historical warning features use HKO's official
[Warnings and Signals Database](https://www.weather.gov.hk/en/wxinfo/climat/warndb/warndba.shtml),
which provides historical series by warning type. Preserve the issue and cancel
times and construct an interval active only after issuance and before cancellation.
HKO notes on the
[rainstorm warning history](https://www.weather.gov.hk/en/wxinfo/climat/warndb/warndb3.shtml)
that recent records may be provisional and are normally verified after cancellation;
do not expose that later verification state as an earlier feature.

## 3. Incidents, closures and roadworks

### Special Traffic News

Transport Department's
[Special Traffic News (2nd Generation)](https://data.gov.hk/en-data/dataset/hk-td-tis_19-special-traffic-news-v2)
is a real-time feed of the latest special traffic and transport arrangements during
incidents. The official
[v4 data dictionary](https://static.data.gov.hk/td/special-traffic-news/en/Data_Specification_for_STN_Eng_v4.0.pdf)
defines identifiers, announcement date, incident status (`NEW`, `UPDATED`,
`CLOSED`), heading/details, district, location, direction and near/between
landmarks. Location is principally text, not a guaranteed coordinate.

Direct archive checks of the official English v2 URL for 2026-10-19 through
2026-10-21 found **231** versions, from `20261019-0010` to `20261021-2051`.
The older English resource had **117** versions over the same dates. These counts
come from the official
[`list-file-versions` API](https://app.data.gov.hk/v1/historical-archive/list-file-versions)
for `https://www.td.gov.hk/en/special_news/trafficnews.xml` and
`http://resource.data.one.gov.hk/td/en/specialtrafficnews.xml`.

Use the v2 feed and archive capture as the conservative availability boundary.
An update or `CLOSED` state is usable only from the first archive version containing
it; never treat the final closed record as the incident's known end throughout its
history. Preserve all versions by incident ID. Geocoding must retain method,
candidate locations and uncertainty. No matched message means "not observed in
this selective feed", not "no incident".

### Roadworks

The official
[Roadworks Location dataset](https://data.gov.hk/en-data/dataset/hk-td-tis_18-roadworks-location)
only covers Highways Department works involving a lane closure on a public road
with speed limit at least 70 km/h. It includes works in progress or due to start
within 12 hours and is updated ad hoc. Its
[data specification](https://static.data.gov.hk/td/roadworks-location/dataspec/roadworks_location_data_specification.pdf)
defines work ID/source/type/status, affected road/bound/lane, work start/end,
last-update time and WGS84 latitude/longitude. The official
[GeoJSON endpoint](https://resource.data.one.gov.hk/td/roadworks-location/get_all_the_roadworks.geojson)
is the preferred spatial resource.

For 2026-10-19 through 2026-10-21, the historical archive exposed only **two**
GeoJSON versions (`20261020-1042`, `20261021-1031`), measured through the official
[`list-file-versions` API](https://app.data.gov.hk/v1/historical-archive/list-file-versions).
This may be consistent with ad-hoc updates but is too sparse to infer continuous
publication state without inspecting each snapshot.

Use only work records present in an archive captured by prediction time. Do not
download the latest file and backfill its start/end interval into the past: it can
contain later revisions or cancellations. The dataset's narrow road/speed/lane-
closure scope makes `0` an invalid encoding for "no roadworks anywhere"; retain a
coverage/scope indicator and missing state.

## 4. Major events

No single complete official historical event register was identified. The sources
below are useful only as explicitly incomplete calendars.

- The Culture, Sports and Tourism Bureau publishes the
  ["M" Mark Events CSV](https://data.gov.hk/en-data/dataset/hk-cstb-cstbdiv011-result-of-m-mark-events/resource/89bafddf-2d42-4469-bb88-332b6a38812f),
  an event calendar updated as necessary. The historical archive returned no
  versions for the checked resource/period, so preserve each retrieved edition.
- Brand Hong Kong publishes a curated
  [What's On in Hong Kong](https://www.brandhk.gov.hk/en/mega-event/what%27s-on-in-hong-kong)
  page and official half-year calendars, such as the
  [second-half mega-events calendar](https://www.brandhk.gov.hk/docs/default-source/default-document-library/calendar-of-mega-events-second-half-en.pdf),
  with date, title, nature, venue and organiser. These PDFs are auditable editions,
  but not proof of complete city-wide event coverage.
- LCSD's
  [Cultural Programmes dataset](https://data.gov.hk/en-data/dataset/hk-lcsd-event-event-cultural)
  is updated daily and separates programme, schedule and venue XML resources.
- LCSD's
  [URBTIX event batches](https://data.gov.hk/en-data/dataset/hk-lcsd-event-urbtix-event/resource/dd8cb3ab-4635-4fd1-8d8a-e5cea3bca2ef)
  are daily XML files addressed by publication date (`YYYYMMDD`), which makes the
  publication edition explicit. They cover ticketed URBTIX events, not all major
  traffic-generating events.

For an event feature, retain the calendar edition/publication date, raw event and
venue text, scheduled start/end precision, source category and retrieval checksum.
Only an edition already published by prediction time may be used. Do not backfill
final dates, cancellations, venue changes, attendance, capacity or post-event
reports. If the source gives only a date, preserve date-level precision and do not
invent start/end times. A missing record means "not listed by this source", not
"no major event".

## Minimum acceptance gate for integration

Before any source enters `external/`, produce a source manifest and an offline test
fixture from authentic preserved bytes. The manifest must state:

1. exact resource URL and licence/attribution;
2. archive/retrieval coverage and checksum;
3. source observation/effective time and conservative `available_at` rule;
4. timezone, units, station/location system and validity flags;
5. join key/method, maximum age or event interval, and spatial uncertainty;
6. known scope exclusions and the meaning of missing;
7. proof that every feature value available to an event satisfies
   `source_available_at <= prediction_time`.

The phase-2 implementation should therefore begin with calendar, archive-backed
temperature/wind and archive-backed STN. Warning intervals can follow once the HKO
history parser is validated. Rainfall, roadworks and major events should remain
optional until their target-period version coverage passes this gate.
