"""Day/detector-group coverage with bounded Arrow scanning and atomic checkpoints.

One process, at most one observation-day and one detector group in pandas. Original
Parquet files are immutable. All capture partitions are scanned by observation time:
late arrivals are included rather than discarded or assumed to fall within a window.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from traffic_recovery.data.coverage import deduplicate, make_bins, profile_day
from traffic_recovery.data.events import UNIT
from traffic_recovery.data.http import sha256_file

VERSION = "bounded-coverage-v1"
COLUMNS = UNIT + ["timestamp", "speed_kmh", "volume_count", "valid", "conflict", "signature", "available_at"]


def _atomic_json(path: Path, record: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _scan(dataset: ds.Dataset, columns: list[str], expression: ds.Expression,
          batch_size: int) -> ds.Scanner:
    return dataset.scanner(columns=columns, filter=expression, batch_size=batch_size,
                           batch_readahead=1, fragment_readahead=1, use_threads=False)


def _time_filter(start: pd.Timestamp, end: pd.Timestamp) -> ds.Expression:
    return (ds.field("timestamp") > pa.scalar(start.to_pydatetime())) & (ds.field("timestamp") <= pa.scalar(end.to_pydatetime()))


def run_bounded(source: Path, output: Path, start: pd.Timestamp, end: pd.Timestamp,
                *, detectors: list[str] | None = None, group_size: int = 2,
                batch_size: int = 32768) -> pd.DataFrame:
    """Profile [start,end] by observation day, with one group in memory.

    start/end must be aware HKT midnights, with a next-day capture partition.
    Scans *all* provided capture partitions for every day, including late records.
    Exact/conflicting duplicates are reconciled across all captures before binning.
    Every selected lane observation is retained; detector selection is explicit.
    Day checkpoints are reused only with matching inputs, config and file hashes.
    Derived files are atomic; a crash before the checkpoint triggers a full day redo.
    Memory scales with detector group and per-detector observation density, not days.
    """
    if start.tzinfo is None or end.tzinfo is None or start >= end or start != start.floor("D") or end != end.floor("D"):
        raise ValueError("Require aware, ordered local midnight boundaries")
    if group_size < 1 or batch_size < 1:
        raise ValueError("group_size and batch_size must be positive")
    paths = sorted(source.glob("*.parquet"))
    expected = {d.strftime("%Y%m%d") for d in pd.date_range(start, end, freq="D")}
    if not expected <= {p.stem for p in paths}:
        raise ValueError("Missing capture partitions, including next-day boundary")
    if detectors is not None and (not detectors or len(set(detectors)) != len(detectors)):
        raise ValueError("Detector filter must be a nonempty unique list")
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = {"version": VERSION, "start": start.isoformat(), "end": end.isoformat(),
                   "detectors": sorted(detectors) if detectors is not None else None,
                   "group_size": group_size, "batch_size": batch_size,
                   "implementation": {p.name: sha256_file(p) for p in
                       [Path(__file__), Path(__file__).with_name("coverage.py")]},
                   "sources": {p.name: sha256_file(p) for p in paths}}
    fingerprint_hash = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    config_path = output / "run.json"
    if config_path.exists():
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        if previous != fingerprint:
            raise ValueError("Checkpoint inputs/config changed; choose a fresh output directory")
    else:
        if any(output.iterdir()):
            raise ValueError("Nonempty output without run manifest; quarantine it or choose a fresh directory")
        _atomic_json(config_path, fingerprint)
    dataset = ds.dataset([str(p) for p in paths], format="parquet")
    # Compact inventory only. Each batch is bounded; no observation histories retained.
    if detectors is None:
        inventory: set[str] = set()
        for batch in _scan(dataset, ["detector_id"], _time_filter(start, end), batch_size).to_batches():
            inventory.update(batch.column(0).to_pylist())
        detector_ids = sorted(inventory)
    else:
        detector_ids = sorted(detectors)
    if not detector_ids:
        raise ValueError("No detectors in requested observation period")
    daily_profiles = []
    for day in pd.date_range(start, end, freq="D", inclusive="left"):
        token = day.strftime("%Y%m%d")
        bins_path, profile_path = output / f"bins-{token}.parquet", output / f"profile-{token}.parquet"
        checkpoint = output / f"checkpoint-{token}.json"
        if checkpoint.exists():
            record = json.loads(checkpoint.read_text(encoding="utf-8"))
            if (record.get("input_hash") != fingerprint_hash or
                any(not p.exists() or sha256_file(p) != record["outputs"].get(p.name) for p in [bins_path, profile_path])):
                raise ValueError(f"Corrupt checkpoint: {checkpoint}; use a fresh directory or investigate")
            daily_profiles.append(pd.read_parquet(profile_path))
            continue
        bin_tmp = output / f"bins-{token}.partial"
        profile_tmp = output / f"profile-{token}.partial"
        # A previous interrupted temporary is not trusted; originals are unchanged.
        bin_tmp.unlink(missing_ok=True)
        profile_tmp.unlink(missing_ok=True)
        writer = None
        summaries = []
        scanned_rows = unique_rows = 0
        try:
            for offset in range(0, len(detector_ids), group_size):
                group = detector_ids[offset:offset + group_size]
                expression = _time_filter(day, day + pd.Timedelta(days=1)) & ds.field("detector_id").isin(group)
                batches = [batch for batch in _scan(dataset, COLUMNS, expression, batch_size).to_batches() if batch.num_rows]
                if not batches:
                    continue
                table = pa.Table.from_batches(batches)
                scanned_rows += table.num_rows
                frame = table.to_pandas(categories=UNIT + ["valid", "signature"])
                del batches, table
                available = frame.loc[frame.available_at <= frame.timestamp.dt.ceil("5min") + pd.Timedelta(minutes=10)]
                binned = make_bins(deduplicate(available))
                quality = deduplicate(frame)
                unique_rows += len(quality)
                summary = profile_day(quality, day)
                binned["day"] = day
                stats = binned.groupby(UNIT + ["day"], observed=True).agg(
                    valid_5m_bins=("valid_slots", lambda x: x.ge(2).sum()), usable_5m_bins=("usable", "sum")).reset_index()
                summaries.append(summary.merge(stats, on=UNIT + ["day"], how="left"))
                binned = binned.drop(columns="day")
                # Stable Arrow types across groups, regardless of categorical dictionaries.
                for col in UNIT:
                    binned[col] = binned[col].astype(str)
                arrow = pa.Table.from_pandas(binned, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(bin_tmp, arrow.schema, compression="zstd")
                writer.write_table(arrow.cast(writer.schema))
        finally:
            if writer is not None:
                writer.close()
        if summaries:
            profile = pd.concat(summaries, ignore_index=True)
        else:
            # Empty day is a legitimate outage, not a failure or fabricated data.
            tz = str(start.tz)
            schema = pa.schema([(name, pa.string()) for name in UNIT] + [
                ("timestamp", pa.timestamp("ns", tz=tz)), ("present_slots", pa.int64()),
                ("valid_slots", pa.int64()), ("flow_slots", pa.int64()), ("speed_kmh", pa.float64()),
                ("last_source_available_at", pa.timestamp("ns", tz=tz)), ("offline_slots", pa.int64()),
                ("conflict_slots", pa.int64()), ("repeat_rows", pa.int64()),
                ("available_at", pa.timestamp("ns", tz=tz)), ("usable", pa.bool_())])
            pq.write_table(pa.Table.from_batches([], schema=schema), bin_tmp, compression="zstd")
            profile = pd.DataFrame(columns=UNIT + ["day", "present_slots", "valid_slots", "offline_slots",
                "conflict_slots", "repeat_rows", "first_present", "last_present", "first_valid", "last_valid",
                "max_absent_gap_seconds", "max_invalid_or_absent_gap_seconds", "valid_5m_bins", "usable_5m_bins"])
        profile.to_parquet(profile_tmp, index=False, compression="zstd")
        os.replace(bin_tmp, bins_path)
        os.replace(profile_tmp, profile_path)
        _atomic_json(checkpoint, {"input_hash": fingerprint_hash, "scanned_rows": scanned_rows,
            "unique_keys": unique_rows, "outputs": {p.name: sha256_file(p) for p in [bins_path, profile_path]}})
        daily_profiles.append(profile)
    nonempty = [frame for frame in daily_profiles if not frame.empty]
    if not nonempty:
        raise ValueError("No observations for requested detectors in observation period")
    profile = pd.concat(nonempty, ignore_index=True)
    inventory = profile[UNIT].drop_duplicates()
    days = pd.DataFrame({"day": pd.date_range(start, end, freq="D", inclusive="left")})
    profile = inventory.merge(days, how="cross").merge(profile, on=UNIT + ["day"], how="left")
    for col in ["present_slots", "valid_slots", "offline_slots", "conflict_slots", "repeat_rows", "valid_5m_bins", "usable_5m_bins"]:
        profile[col] = profile[col].fillna(0).astype(int)
    for col in ["max_absent_gap_seconds", "max_invalid_or_absent_gap_seconds"]:
        profile[col] = profile[col].fillna(86400).astype(int)
    for col in ["first_present", "last_present", "first_valid", "last_valid"]:
        profile[col] = pd.to_datetime(profile[col], utc=True).dt.tz_convert(start.tz)
    profile["expected_slots"] = 2880
    profile["valid_coverage"] = profile.valid_slots / 2880
    profile["offline_fraction_expected"] = profile.offline_slots / 2880
    profile["offline_fraction_present"] = profile.offline_slots.div(profile.present_slots.replace(0, float("nan")))
    profile["valid_5m_coverage"] = profile.valid_5m_bins / 288
    profile["usable_5m_coverage"] = profile.usable_5m_bins / 288
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/local/pilot/lane_snapshots"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--detector", action="append", dest="detectors")
    parser.add_argument("--group-size", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32768)
    args = parser.parse_args()
    start, end = (pd.Timestamp(value, tz="Asia/Hong_Kong") for value in (args.start, args.end))
    result = run_bounded(args.source, args.output, start, end, detectors=args.detectors,
                         group_size=args.group_size, batch_size=args.batch_size)
    print(json.dumps({"status": "completed", "lane_days": len(result), "detectors": result.detector_id.nunique(),
                      "present_slots": int(result.present_slots.sum()), "valid_slots": int(result.valid_slots.sum()),
                      "conflict_keys": int(result.conflict_slots.sum())}, indent=2))


if __name__ == "__main__":
    main()
