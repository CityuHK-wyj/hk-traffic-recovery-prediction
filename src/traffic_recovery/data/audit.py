"""Reproducible official-data feasibility audit CLI; no training or labels."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import logging
from importlib.metadata import version
from pathlib import Path
import platform
import sys
import zipfile

import pandas as pd

from traffic_recovery.data.http import AcquisitionError, EvidenceClient, sha256_file
from traffic_recovery.data.quality import QualityAccumulator
from traffic_recovery.data.sources import (
    NETWORK_STATIC, RAW, RESOURCES, SEGMENTS, archive_url, list_versions,
)
from traffic_recovery.data.traffic import HK, RAW_KEY, SchemaError, clean_traffic, parse_traffic
from traffic_recovery.network.audit import inspect_centerline

LOGGER = logging.getLogger(__name__)


def _archive_time(member: str) -> datetime:
    return datetime.strptime(Path(member).name[:13], "%Y%m%d-%H%M").replace(tzinfo=HK)


def run_audit(args: argparse.Namespace) -> dict:
    """Execute bounded date partitions and preserve evidence, even on failures."""
    client = EvidenceClient(args.output, timeout=args.timeout, reuse=args.reuse)
    report: dict = {"schema_version": "0.1", "started_at": datetime.now(timezone.utc).isoformat(),
                    "software": {"python": platform.python_version(), "platform": platform.platform(),
                                 **{name: version(name) for name in ["pandas", "numpy", "tzdata", "hk-traffic-recovery-prediction"]}},
                    "uv_lock_sha256": sha256_file(Path("uv.lock")) if Path("uv.lock").exists() else None,
                    "requested_dates_hk": {"start": str(args.start), "end": str(args.end)},
                    "mode": "daily archives" if args.daily else "selected snapshots",
                    "evidence_directory": args.output.as_posix(), "errors": [], "resources": {},
                    "archive_days": [], "conflict_examples": [], "warnings": [
                        "All within-snapshot conflicting key variants explicitly quarantined; strict cleaning raises by default.",
                        "No congestion/recovery thresholds or labels finalized.",
                        "Current metadata is not verified as historically version-consistent.",
                        "Collection timestamps are not observation timestamps or guaranteed availability times.",
                        "No detector-to-road spatial matching performed.",
                    ]}
    paths: dict[str, Path] = {}

    def attempt(stage: str, function):
        try:
            return function()
        except (AcquisitionError, SchemaError, ValueError, OSError, zipfile.BadZipFile) as exc:
            report["errors"].append({"stage": stage, "type": type(exc).__name__, "error": str(exc)})
            LOGGER.exception("audit_stage_failed stage=%s", stage)
            return None

    for name, url in RESOURCES.items():
        path = attempt(name, lambda url=url, name=name: client.fetch(url, name))
        report["resources"][name] = {"url": url, "retrieved": path is not None}
        if path:
            paths[name] = path

    files = attempt("archive resource metadata", lambda: client.json(
        archive_url("list-files", start=args.start.strftime("%Y%m%d"), end=args.end.strftime("%Y%m%d"),
                    provider="hk-td", search="Traffic Data of Strategic", max=100), "archive_files.json"))
    if files is not None:
        report["archive_resource_metadata"] = files
    for name, source in [("raw", RAW), ("segment", SEGMENTS)]:
        listing = attempt(f"coverage {name}", lambda source=source, name=name: list_versions(
            client, source, args.coverage_start, args.end, f"coverage_{name}.json", require_complete=False))
        if listing is not None:
            stamps = listing["timestamps"]
            report[f"archive_coverage_{name}"] = {
                "queried_start": str(args.coverage_start), "queried_end": str(args.end),
                "version_count": listing["version-count"], "returned_timestamps": len(stamps),
                "truncated": len(stamps) < listing["version-count"],
                "first_returned_timestamp": min(stamps) if stamps else None,
                "last_returned_timestamp": max(stamps) if stamps else None,
                "total_uncompressed_bytes_reported": listing.get("total-size"),
                "total_packaged_bytes_reported": listing.get("total-size-zip"),
                "packaged_period_count": listing.get("version-count-zip"),
                "caveat": "Archive-reported availability, not proof of complete continuous measurements. Last returned timestamp may be truncated.",
            }
    # Current snapshots validate both feeds independently from historical sampling.
    current: dict[str, pd.DataFrame] = {}
    for name in ["raw_current.xml", "segment_current.xml"]:
        if name in paths:
            result = attempt(f"parse {name}", lambda name=name: clean_traffic(parse_traffic(paths[name].read_bytes())))
            if result:
                frame, stats = result
                current[name] = frame
                report[name] = {**stats, "observation_min": frame.timestamp.min().isoformat(),
                                "observation_max": frame.timestamp.max().isoformat()}

    accumulator = QualityAccumulator()
    sample_frames = []
    compressed = 0
    uncompressed = 0
    lag_counts: Counter = Counter()
    day = args.start
    while day <= args.end:
        token = day.strftime("%Y%m%d")
        listing = attempt(f"versions {token}", lambda day=day, token=token: list_versions(
            client, RAW, day, day, f"versions_{token}.json"))
        if listing is None:
            day += timedelta(days=1)
            continue
        stamps = listing["timestamps"]
        summary = {"date": str(day), "listed_versions": len(stamps), "parsed_snapshots": 0,
                   "listed_uncompressed_bytes": listing.get("total-size"),
                   "listed_packaged_bytes": listing.get("total-size-zip")}
        report["archive_days"].append(summary)

        def consume(payload: bytes, member: str, keep_sample: bool) -> None:
            parsed = parse_traffic(payload)
            frame, quality = clean_traffic(parsed, conflicts="quarantine")
            if quality["conflicting_keys_quarantined"] and len(report["conflict_examples"]) < 3:
                conflict = parsed.loc[parsed.duplicated(RAW_KEY, keep=False)].copy()
                for column in ["timestamp", "period_start"]:
                    conflict[column] = conflict[column].map(lambda t: t.isoformat())
                report["conflict_examples"].append({"source_file": member, "records": conflict.to_dict("records")})
            accumulator.add(frame, quality)
            archive_stamp = _archive_time(member)
            lag_counts[int((archive_stamp - frame.timestamp.max()).total_seconds())] += 1
            if keep_sample:
                original = args.output / f"sample_{token}.xml"
                if original.exists():
                    if original.read_bytes() != payload:
                        raise AcquisitionError(f"Existing sample differs: {original}")
                else:
                    original.write_bytes(payload)
                sample = frame.copy()
                sample["archive_time"] = archive_stamp
                sample["source_file"] = member
                sample_frames.append(sample)
                summary["saved_original_sample"] = original.name
                summary["saved_original_sample_sha256"] = sha256_file(original)
            summary["parsed_snapshots"] += 1

        def process_day() -> None:
            nonlocal compressed, uncompressed
            if not stamps:
                raise AcquisitionError(f"No archived observations for {day}")
            if args.daily:
                path = client.fetch(archive_url("get-file", url=RAW, time=token), f"raw_{token}.zip")
                compressed += path.stat().st_size
                with zipfile.ZipFile(path) as archive:
                    members = sorted(m for m in archive.namelist() if m.endswith(".xml"))
                    # No extraction: encoded URL paths in official ZIPs are not local paths.
                    if len(members) != len(stamps):
                        raise AcquisitionError(f"ZIP/list count mismatch: {len(members)} != {len(stamps)}")
                    uncompressed += sum(archive.getinfo(m).file_size for m in members)
                    for index, member in enumerate(members):
                        consume(archive.read(member), member, index == 0)
                        if index % 200 == 0:
                            LOGGER.info("audit_progress day=%s parsed=%s total=%s", token, index + 1, len(members))
            else:
                count = min(args.snapshots_per_day, len(stamps))
                indices = sorted({round(i * (len(stamps) - 1) / max(count - 1, 1)) for i in range(count)})
                for index in indices:
                    stamp = stamps[index]
                    name = f"raw_{stamp}.xml"
                    path = client.fetch(archive_url("get-file", url=RAW, time=stamp), name)
                    uncompressed += path.stat().st_size
                    consume(path.read_bytes(), f"{stamp}-rawSpeedVol-all.xml", index == indices[0])
        attempt(f"sample {token}", process_day)
        day += timedelta(days=1)

    report["historical_raw_quality"] = accumulator.report()
    report["archive_minus_latest_observation_seconds_counts"] = dict(sorted(lag_counts.items()))
    if sample_frames:
        saved = pd.concat(sample_frames, ignore_index=True)
        saved.to_csv(args.output / "cleaned_sample.csv", index=False)
        report["saved_cleaned_sample"] = {"file": "cleaned_sample.csv", "rows": len(saved),
                                           "scope": "First parsed snapshot of each sampled archive day, not the entire audit"}
    days = len(report["archive_days"])
    report["storage"] = {"downloaded_daily_zip_bytes": compressed,
                         "source_xml_bytes_in_downloaded_archives_or_snapshots": uncompressed,
                         "selected_archive_days": days,
                         "thirty_day_zip_bytes_extrapolation": round(compressed / days * 30) if compressed and days else None,
                         "thirty_day_xml_bytes_extrapolation": round(uncompressed / days * 30) if args.daily and days else None,
                         "caveat": "Linear extrapolation of selected dates only, not a quota or processed-data size estimate."}

    if "detectors.csv" in paths:
        def inspect_detectors() -> dict:
            locations = pd.read_csv(paths["detectors.csv"], encoding="utf-8-sig", dtype={"AID_ID_Number": str})
            required = {"AID_ID_Number", "Direction", "Easting", "Northing", "Latitude", "Longitude"}
            if not required <= set(locations):
                raise SchemaError(f"Detector metadata changed: {list(locations)}")
            ids = set(locations.AID_ID_Number)
            return {"rows": len(locations), "columns": list(locations), "unique_detector_ids": len(ids),
                    "duplicate_detector_ids": int(locations.AID_ID_Number.duplicated().sum()),
                    "missing_coordinates": int(locations[["Easting", "Northing", "Latitude", "Longitude"]].isna().any(axis=1).sum()),
                    "historical_observed_ids_absent_from_current_metadata": sorted(accumulator.detectors - ids),
                    "current_metadata_ids_not_seen_in_historical_sample": sorted(ids - accumulator.detectors),
                    "direction_values": sorted(locations.Direction.dropna().unique().tolist())}
        report["detector_metadata"] = attempt("inspect detectors", inspect_detectors)
    if "segments.csv" in paths:
        def inspect_segments() -> dict:
            info = pd.read_csv(paths["segments.csv"], dtype=str)
            if "irn_id" not in info:
                raise SchemaError(f"Segment metadata changed: {list(info)}")
            ids = set(info.irn_id)
            processed = current.get("segment_current.xml")
            return {"rows": len(info), "columns": list(info), "unique_irn_ids": len(ids),
                    "duplicate_irn_ids": int(info.irn_id.duplicated().sum()),
                    "current_processed_ids_absent_from_segment_csv": sorted(set(processed.segment_id) - ids) if processed is not None else None}
        report["segment_metadata"] = attempt("inspect segments", inspect_segments)
    if args.network:
        network_path = attempt("download centerline", lambda: client.fetch(
            NETWORK_STATIC + "CENTERLINE.gml", "network_centerline.gml"))
        if network_path:
            segment_ids = set(current["segment_current.xml"].segment_id) if "segment_current.xml" in current else set()
            report["road_network"] = attempt("inspect centerline", lambda: inspect_centerline(network_path, segment_ids))
    else:
        report["road_network"] = {"status": "full geometry not requested; use --network (large download)"}
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["status"] = "completed" if not report["errors"] else "partial_or_failed"
    if not accumulator.files:
        report["warnings"].append("No historical observations parsed; consult preserved errors and current snapshots.")
    # Include checksums/URLs/retrieval times in the portable report, not only local files.
    report["response_manifest"] = [json.loads(p.read_text(encoding="utf-8"))
                                   for p in sorted(args.output.glob("*.meta.json"))]
    return report


def main() -> int:
    """CLI entry point. Dates are inclusive archive dates in Hong Kong time."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--coverage-start", type=date.fromisoformat, default=date(2010, 1, 1))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("reports/data_audit.json"))
    parser.add_argument("--daily", action="store_true", help="Download/parse every snapshot in daily ZIPs")
    parser.add_argument("--network", action="store_true", help="Download full CENTERLINE GML (hundreds of MB)")
    parser.add_argument("--snapshots-per-day", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--reuse", action="store_true", help="Reuse identical checksum-verified successful responses")
    args = parser.parse_args()
    if args.start > args.end or args.snapshots_per_day < 1 or args.timeout <= 0 or args.coverage_start > args.end:
        parser.error("Invalid date range, snapshot count or timeout")
    if (args.end - args.start).days > 30:
        parser.error("This feasibility CLI is limited to 31 days per run")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        report = run_audit(args)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        LOGGER.exception("audit_unexpected_failure; original responses remain in %s", args.output)
        return 1
    print(json.dumps({"status": report["status"], "report": args.report.as_posix(),
                      "historical_files_parsed": report["historical_raw_quality"]["files_parsed"],
                      "errors": report["errors"]}, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
