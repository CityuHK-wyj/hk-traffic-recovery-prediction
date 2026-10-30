"""Validate and fingerprint a frozen event cohort before model work."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from traffic_recovery.models.contract import (
    ExperimentContract,
    validate_event_table,
    validation_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument(
        "--contract", type=Path, default=Path("configs/experiment_contract.json")
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(f"Refusing to overwrite existing report: {args.report}")
    contract = ExperimentContract.from_path(args.contract)
    events = pd.read_parquet(args.events)
    report = validate_event_table(events, contract)
    manifest = validation_manifest(args.events, args.contract, contract, report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
