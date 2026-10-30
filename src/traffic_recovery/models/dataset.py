"""Build one explicit, validated ML-ready row per traffic recovery event."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from traffic_recovery.data.http import sha256_file
from traffic_recovery.models.contract import ExperimentContract, validate_event_table


KEY = ["event_id", "prediction_time"]
IDENTIFIERS = [
    "detector_id", "direction", "lane_id", "segment_id", "weather_station_id",
]
PROVENANCE = [
    "definition_version", "reference_fit_end", "context_version",
    "network_version", "feature_status",
]
OUTCOME_AUDIT = [
    "recovery_time", "recovery_available_at", "followup_end",
    "termination_reason", "episode_separated_at",
]


def _normalise_split(events: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    if "split" in result and "split_proposal" in result:
        mismatch = result["split"].astype("string").ne(result["split_proposal"].astype("string"))
        if mismatch.any():
            raise ValueError("split and split_proposal disagree")
    elif "split" not in result and "split_proposal" in result:
        result["split"] = result["split_proposal"].astype("string")
    return result


def _merge_exact(base: pd.DataFrame, features: pd.DataFrame, name: str) -> pd.DataFrame:
    missing = set(KEY) - set(features.columns)
    if missing:
        raise ValueError(f"{name} missing merge keys: {sorted(missing)}")
    if features.duplicated(KEY).any():
        raise ValueError(f"{name} must contain one row per event key")
    base_keys = pd.MultiIndex.from_frame(base[KEY])
    feature_keys = pd.MultiIndex.from_frame(features[KEY])
    if set(base_keys) != set(feature_keys):
        raise ValueError(f"{name} event keys do not exactly match the event cohort")
    payload = [column for column in features.columns if column not in KEY]
    collisions = set(payload) & set(base.columns)
    if collisions:
        raise ValueError(f"{name} columns collide with existing data: {sorted(collisions)}")
    return base.merge(features, on=KEY, how="left", validate="one_to_one")


def build_model_dataset(
    events: pd.DataFrame,
    contract: ExperimentContract,
    *,
    context: pd.DataFrame | None = None,
    spatial: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Merge approved feature tables and enforce the executable event contract."""
    result = _normalise_split(events)
    for column in ["event_id", *IDENTIFIERS]:
        if column not in result:
            continue
        known = result[column].dropna()
        if not known.map(lambda value: isinstance(value, str)).all():
            raise ValueError(f"{column} must contain strings when present")
        if known.str.strip().eq("").any():
            raise ValueError(f"{column} must be nonempty when present")
    for name, feature_table in (("context", context), ("spatial", spatial)):
        if feature_table is not None:
            result = _merge_exact(result, feature_table, name)

    labels = [f"label_{horizon}m" for horizon in contract.horizons]
    reasons = [f"reason_{horizon}m" for horizon in contract.horizons]
    ordered = [
        *KEY, "split", *IDENTIFIERS, *labels, *reasons, *OUTCOME_AUDIT,
        *contract.feature_allowlist, *contract.availability_columns, *PROVENANCE,
    ]
    selected: list[str] = []
    for column in ordered:
        if column in result and column not in selected:
            selected.append(column)
    result = result[selected].copy()
    result.insert(0, "dataset_version", contract.version)
    report = validate_event_table(result, contract)
    present_groups = {
        group: [column for column in columns if column in result]
        for group, columns in contract.feature_groups.items()
    }
    report.update({
        "dataset_version": contract.version,
        "scientific_approval": contract.status,
        "feature_groups": present_groups,
    })
    return result, report


def build_model_dataset_files(
    *,
    events_path: Path,
    contract_path: Path,
    output_path: Path,
    manifest_path: Path,
    context_path: Path | None = None,
    spatial_path: Path | None = None,
) -> dict[str, object]:
    """Build and fingerprint a model dataset without overwriting evidence."""
    for target in (output_path, manifest_path):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing artifact: {target}")
    inputs = {"events": events_path}
    if context_path is not None:
        inputs["context"] = context_path
    if spatial_path is not None:
        inputs["spatial"] = spatial_path
    missing = [name for name, path in inputs.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing model-dataset inputs: {missing}")

    contract = ExperimentContract.from_path(contract_path)
    dataset, report = build_model_dataset(
        pd.read_parquet(events_path), contract,
        context=pd.read_parquet(context_path) if context_path else None,
        spatial=pd.read_parquet(spatial_path) if spatial_path else None,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(output_path, index=False)
    manifest = {
        "manifest_version": "model-dataset-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation": report,
        "inputs": {
            name: {"path": path.as_posix(), "sha256": sha256_file(path)}
            for name, path in inputs.items()
        },
        "contract": {"path": contract_path.as_posix(), "sha256": sha256_file(contract_path)},
        "output": {"path": output_path.as_posix(), "sha256": sha256_file(output_path)},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--spatial", type=Path)
    parser.add_argument("--contract", type=Path, default=Path("configs/experiment_contract.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    build_model_dataset_files(
        events_path=args.events, context_path=args.context, spatial_path=args.spatial,
        contract_path=args.contract, output_path=args.output, manifest_path=args.manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
