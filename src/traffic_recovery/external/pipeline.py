"""Reproducible Parquet-to-Parquet external context build."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from traffic_recovery.data.http import sha256_file

from .build import ContextRules, build_context_features


def build_context_dataset(
    *,
    events_path: Path,
    holidays_path: Path,
    weather_path: Path,
    incidents_path: Path,
    major_events_path: Path,
    config_path: Path,
    output_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    """Build one external feature row per event and fingerprint every input."""
    for target in (output_path, manifest_path):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing artifact: {target}")
    inputs = {
        "events": events_path,
        "holidays": holidays_path,
        "weather": weather_path,
        "incidents": incidents_path,
        "major_events": major_events_path,
    }
    missing = [name for name, path in inputs.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing context input files: {missing}")
    rules = ContextRules.from_path(config_path)
    context = build_context_features(
        pd.read_parquet(events_path),
        holidays=pd.read_parquet(holidays_path),
        weather_observations=pd.read_parquet(weather_path),
        incidents=pd.read_parquet(incidents_path),
        major_events=pd.read_parquet(major_events_path),
        rules=rules,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    context.to_parquet(output_path, index=False)
    manifest = {
        "manifest_version": "external-context-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context_version": rules.version,
        "rows": len(context),
        "inputs": {
            name: {"path": path.as_posix(), "sha256": sha256_file(path)}
            for name, path in inputs.items()
        },
        "config": {"path": config_path.as_posix(), "sha256": sha256_file(config_path)},
        "output": {"path": output_path.as_posix(), "sha256": sha256_file(output_path)},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--holidays", type=Path, required=True)
    parser.add_argument("--weather", type=Path, required=True)
    parser.add_argument("--incidents", type=Path, required=True)
    parser.add_argument("--major-events", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/external_features.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    build_context_dataset(
        events_path=args.events,
        holidays_path=args.holidays,
        weather_path=args.weather,
        incidents_path=args.incidents,
        major_events_path=args.major_events,
        config_path=args.config,
        output_path=args.output,
        manifest_path=args.manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
