"""Adapters for verified TD XML schemas; no aggregation, imputation or labels.

Raw source values are retained as strings in *_raw columns. `timestamp` is the
end of the observation interval, not its publication/retrieval time.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Literal
import xml.etree.ElementTree as ET

import pandas as pd

HK = ZoneInfo("Asia/Hong_Kong")
RAW_KEY = ["detector_id", "direction", "lane_id", "timestamp"]
SEGMENT_KEY = ["segment_id", "timestamp"]
MEASUREMENTS = {"speed": "speed_kmh", "occupancy": "occupancy_pct",
                "volume": "volume_count", "sd": "speed_sd_kmh"}


class SchemaError(ValueError):
    """Source structure or observation keys violate the verified schema."""


def _text(element: ET.Element, name: str, *, allow_empty: bool = False) -> str:
    field = element.find(name)
    if field is None or (not allow_empty and not (field.text or "").strip()):
        raise SchemaError(f"Missing field: {name}")
    return (field.text or "").strip()


def parse_traffic(payload: bytes) -> pd.DataFrame:
    """Parse raw lane XML or processed segment XML, preserving source strings.

    Raises SchemaError on malformed XML, missing tags, unknown roots, empty
    observations or invalid dates/times. HK source times become aware datetimes.
    A period ending after midnight rolls forward one day.
    """
    try:
        root = ET.fromstring(payload)
        day = date.fromisoformat(_text(root, "date"))
        rows: list[dict] = []
        if root.tag == "raw_speed_volume_list":
            for period in root.findall("./periods/period"):
                start = datetime.combine(day, time.fromisoformat(_text(period, "period_from")), HK)
                end = datetime.combine(day, time.fromisoformat(_text(period, "period_to")), HK)
                if end < start:
                    end += timedelta(days=1)
                if end <= start:
                    raise SchemaError("Non-positive observation interval")
                for detector in period.findall("./detectors/detector"):
                    identifier = _text(detector, "detector_id")
                    direction = _text(detector, "direction")
                    for lane in detector.findall("./lanes/lane"):
                        row = {"detector_id": identifier, "direction": direction,
                               "lane_id": _text(lane, "lane_id"), "period_start": start,
                               "timestamp": end, "valid": _text(lane, "valid", allow_empty=True)}
                        for source, field in [("speed", "speed"), ("occupancy", "occupancy"),
                                              ("volume", "volume"), ("s.d.", "sd")]:
                            row[f"{field}_raw"] = _text(lane, source, allow_empty=True)
                        rows.append(row)
        elif root.tag == "segment_speed_list":
            stamp = datetime.combine(day, time.fromisoformat(_text(root, "time")), HK)
            version = _text(root, "irn_version")
            for segment in root.findall("./segments/segment"):
                rows.append({"segment_id": _text(segment, "segment_id"), "timestamp": stamp,
                             "irn_version": version, "valid": _text(segment, "valid", allow_empty=True),
                             "speed_raw": _text(segment, "speed", allow_empty=True)})
        else:
            raise SchemaError(f"Unexpected XML root: {root.tag}")
    except (ET.ParseError, ValueError) as exc:
        raise SchemaError(f"Invalid TD XML: {exc}") from exc
    if not rows:
        raise SchemaError("Empty traffic dataset")
    frame = pd.DataFrame(rows)
    for column in ["timestamp"] + (["period_start"] if "period_start" in frame else []):
        frame[column] = pd.to_datetime(frame[column], utc=True).dt.tz_convert("Asia/Hong_Kong").dt.as_unit("ns")
    return frame


def clean_traffic(frame: pd.DataFrame, *, conflicts: Literal["raise", "quarantine"] = "raise") -> tuple[pd.DataFrame, dict]:
    """Validate, flag and clean one parsed frame; return (copy, quality counts).

    Exact duplicates collapse; conflicting values for a key raise SchemaError
    by default. Explicit `conflicts="quarantine"` excludes ALL conflicting
    variants and reports their counts, never selecting a measurement silently.
    No rows with invalid measurements are dropped: derived values become NA.
    N/unknown validity masks all measurements. Nonfinite, negative, fractional
    count/int fields and occupancy >100 are invalid, not congestion thresholds.
    """
    if conflicts not in {"raise", "quarantine"}:
        raise ValueError("Unknown conflict policy")
    raw = "detector_id" in frame.columns
    key = RAW_KEY if raw else SEGMENT_KEY
    measurements = MEASUREMENTS if raw else {"speed": "speed_kmh"}
    required = set(key + ["valid"] + [f"{m}_raw" for m in measurements])
    if raw:
        required.add("period_start")
    else:
        required.add("irn_version")
    missing = required - set(frame.columns)
    if missing:
        raise SchemaError(f"Missing columns: {sorted(missing)}")
    if frame.empty:
        raise SchemaError("Empty traffic dataset")
    if frame[key].isna().any().any() or any(
        frame[c].astype(str).str.strip().eq("").any() for c in key
    ):
        raise SchemaError("Null/blank observation key")
    for column in ["timestamp"] + (["period_start"] if raw else []):
        if not isinstance(frame[column].dtype, pd.DatetimeTZDtype):
            raise SchemaError(f"{column} must be timezone-aware")
        if str(frame[column].dt.tz) != "Asia/Hong_Kong":
            raise SchemaError(f"{column} must use Asia/Hong_Kong")
    if raw and (frame.period_start.isna().any() or (frame.timestamp <= frame.period_start).any()):
        raise SchemaError("Invalid observation interval")
    result = frame.drop_duplicates().copy()
    exact_duplicates = len(frame) - len(result)
    conflicting = result.duplicated(key, keep=False)
    conflict_keys = len(result.loc[conflicting, key].drop_duplicates())
    quarantine_rows = int(conflicting.sum())
    if conflict_keys and conflicts == "raise":
        raise SchemaError("Conflicting duplicate observation keys; quarantine rather than choose a value")
    result = result.loc[~conflicting].copy()
    report = {"input_rows": len(frame), "exact_duplicate_rows": exact_duplicates,
              "conflicting_keys_quarantined": conflict_keys,
              "conflicting_rows_quarantined": quarantine_rows,
              "output_rows": len(result), "source_offline_rows": int(result.valid.eq("N").sum()),
              "unknown_validity_rows": int((~result.valid.isin(["Y", "N"])).sum()),
              "measurements": {}}
    result["source_valid"] = result.valid.eq("Y")
    for field, normalized in measurements.items():
        source = result[f"{field}_raw"]
        missing_raw = source.isna() | source.astype(str).str.strip().eq("")
        numeric = pd.to_numeric(source, errors="coerce").astype("Float64")
        invalid = (~missing_raw) & (numeric.isna() | numeric.isin([float("inf"), -float("inf")]) | numeric.lt(0)).fillna(True)
        if field == "occupancy":
            invalid |= numeric.gt(100).fillna(False)
        if raw and field in ["speed", "volume", "occupancy"]:
            invalid |= numeric.mod(1).ne(0).fillna(False)
        result[f"{field}_missing_raw"] = missing_raw
        result[f"{field}_invalid_numeric"] = invalid
        result[normalized] = numeric.mask(missing_raw | invalid | ~result.source_valid)
        report["measurements"][field] = {
            "missing_raw": int(missing_raw.sum()), "invalid_numeric": int(invalid.sum()),
            "clean_missing": int(result[normalized].isna().sum()),
            "clean_missing_rate": float(result[normalized].isna().mean()) if len(result) else None,
        }
    return result.reset_index(drop=True), report
