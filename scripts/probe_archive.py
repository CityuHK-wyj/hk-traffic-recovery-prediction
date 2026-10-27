"""Probe explicit archive version times, preserving empty/offline/error evidence.

Run with `uv run --locked python scripts/probe_archive.py --help`.
"""
import argparse
import json
from pathlib import Path

from traffic_recovery.data.http import AcquisitionError, EvidenceClient
from traffic_recovery.data.sources import RAW, SEGMENTS, archive_url
from traffic_recovery.data.traffic import SchemaError, clean_traffic, parse_traffic


def main() -> int:
    """Download named versions and report actual parser/quality outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["raw", "segment"], required=True)
    parser.add_argument("--time", action="append", required=True, help="YYYYMMDD-HHMM from list-file-versions; repeatable")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    client = EvidenceClient(args.output, reuse=args.reuse)
    results = []
    for stamp in args.time:
        # Validate before constructing local filenames.
        from datetime import datetime
        datetime.strptime(stamp, "%Y%m%d-%H%M")
        name = f"{args.source}_{stamp}.xml"
        record = {"file": name, "requested_time": stamp}
        try:
            path = client.fetch(archive_url("get-file", url=RAW if args.source == "raw" else SEGMENTS, time=stamp), name)
            frame, quality = clean_traffic(parse_traffic(path.read_bytes()))
            record.update(quality=quality, observation_min=frame.timestamp.min().isoformat(),
                          observation_max=frame.timestamp.max().isoformat())
        except (AcquisitionError, SchemaError) as exc:
            record.update(error=str(exc), error_type=type(exc).__name__)
        results.append(record)
    report = {"results": results, "response_manifest": [
        json.loads(path.read_bytes()) for path in sorted(args.output.glob("*.meta.json"))]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
