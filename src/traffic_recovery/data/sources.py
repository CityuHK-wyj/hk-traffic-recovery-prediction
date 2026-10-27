"""Official resource identifiers and archive API contracts verified in the audit."""
from datetime import date
from urllib.parse import urlencode

from traffic_recovery.data.http import AcquisitionError, EvidenceClient

ARCHIVE = "https://app.data.gov.hk/v1/historical-archive/"
RAW = "https://resource.data.one.gov.hk/td/traffic-detectors/rawSpeedVol-all.xml"
SEGMENTS = "https://resource.data.one.gov.hk/td/traffic-detectors/irnAvgSpeed-all.xml"
TRAFFIC_STATIC = "https://static.data.gov.hk/td/traffic-data-strategic-major-roads/"
NETWORK_STATIC = "https://static.data.gov.hk/td/road-network-v2/"
RESOURCES = {
    "traffic_catalog.html": "https://data.gov.hk/en-data/dataset/hk-td-sm_4-traffic-data-strategic-major-roads",
    "archive_spec.html": "https://data.gov.hk/en/help/api-spec",
    "network_catalog.html": "https://data.gov.hk/en-data/dataset/hk-td-tis_15-road-network-v2",
    "detectors.csv": TRAFFIC_STATIC + "info/traffic_speed_volume_occ_info.csv",
    "segments.csv": TRAFFIC_STATIC + "info/speed_segments_info.csv",
    "traffic_spec.pdf": TRAFFIC_STATIC + "dataspec/dataspec-traffic-data-strategic-major-roads.pdf",
    "raw_schema.xsd": TRAFFIC_STATIC + "info/SpeedVolOcc-BR.xsd",
    "network_files.csv": NETWORK_STATIC + "dataspec/file_list.csv",
    "network_spec.zip": NETWORK_STATIC + "dataspec/rdnet_dataspec.zip",
    "network_centerline_schema.gfs": NETWORK_STATIC + "CENTERLINE.gfs",
    "raw_current.xml": RAW,
    "segment_current.xml": SEGMENTS,
}


def archive_url(action: str, **params: str | int) -> str:
    """Build encoded official archive GET URL (dates and times are GMT+8)."""
    if action not in {"list-files", "list-file-versions", "get-file"}:
        raise ValueError(f"Unsupported archive action: {action}")
    return ARCHIVE + action + "?" + urlencode(params)


def list_versions(client: EvidenceClient, source: str, start: date, end: date,
                  name: str, *, require_complete: bool = True) -> dict:
    """Query a date partition; refuse a silently truncated 10,000-item listing."""
    if start > end:
        raise ValueError("start must not follow end")
    result = client.json(archive_url("list-file-versions", url=source,
                                   start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d")), name)
    if (not isinstance(result.get("timestamps"), list)
            or not isinstance(result.get("version-count"), int)
            or not all(isinstance(t, str) for t in result["timestamps"])):
        raise AcquisitionError(f"Unexpected archive listing schema: {name}")
    if require_complete and len(result["timestamps"]) != result["version-count"]:
        raise AcquisitionError("Archive listing truncated/inconsistent; use smaller date partitions")
    return result
