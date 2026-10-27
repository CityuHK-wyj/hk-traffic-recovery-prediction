"""Coverage and 5-minute candidate bins; missing remains missing, not zero."""
from pathlib import Path
import logging

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from traffic_recovery.data.events import UNIT
from traffic_recovery.data.traffic import RAW_KEY

LOGGER = logging.getLogger(__name__)


def deduplicate(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse identical archive repeats; quarantine cross-file conflicting keys.

    Earliest archive capture is availability for identical observations. Source
    signature covers all raw measurements, not only speed. Returns one row/key;
    conflicting keys occupy a missing slot and remain explicitly counted.
    """
    frame = frame.sort_values("available_at")
    for column in UNIT + ["valid", "signature", "source_file"]:
        if column in frame:
            frame[column] = frame[column].astype("category")
    groups = frame.groupby(RAW_KEY, observed=True, sort=False)
    flags = groups.signature.nunique().gt(1) | groups.conflict.any()
    counts = groups.size()
    result = frame.drop_duplicates(RAW_KEY).set_index(RAW_KEY)
    result["conflict"] = flags.reindex(result.index).to_numpy()
    result["repeat_rows"] = counts.reindex(result.index).to_numpy() - 1
    result.loc[result.conflict, ["speed_kmh", "volume_count"]] = float("nan")
    return result.reset_index()


def make_bins(frame: pd.DataFrame) -> pd.DataFrame:
    """Right-closed 5m bins, >=2 unique valid positive-flow lane slots required.

    Median speed uses ONLY positive-flow, valid speed observations. This avoids
    interpreting no-flow default speeds as traffic recovery; incurs censoring and
    is a provisional measurement choice, not continuous 5-minute completeness.
    Availability is a fixed bin-end +10m closure, using only rows captured by
    that cutoff. Late rows are excluded before deduplication by the caller.
    """
    frame = frame.loc[frame.available_at <= frame.timestamp.dt.ceil("5min") + pd.Timedelta(minutes=10)].copy()
    frame["bin_end"] = frame.timestamp.dt.ceil("5min")
    frame["valid_slot"] = frame.speed_kmh.notna() & ~frame.conflict
    frame["flow_slot"] = frame.valid_slot & frame.volume_count.gt(0)
    frame["flow_speed"] = frame.speed_kmh.where(frame.flow_slot)
    frame["offline_slot"] = frame.valid.eq("N")
    result = frame.groupby(UNIT + ["bin_end"], observed=True, sort=False).agg(
        present_slots=("timestamp", "size"), valid_slots=("valid_slot", "sum"),
        flow_slots=("flow_slot", "sum"), speed_kmh=("flow_speed", "median"),
        available_at=("available_at", "max"), offline_slots=("offline_slot", "sum"),
        conflict_slots=("conflict", "sum"), repeat_rows=("repeat_rows", "sum")).reset_index()
    result = result.rename(columns={"bin_end": "timestamp", "available_at": "last_source_available_at"})
    result["available_at"] = result.timestamp + pd.Timedelta(minutes=10)
    result["usable"] = result.flow_slots.ge(2) & result.speed_kmh.notna() & result.conflict_slots.eq(0)
    return result


def missing_run_seconds(times: pd.Series, start: pd.Timestamp, end: pd.Timestamp,
                        step_seconds: int = 30) -> int:
    """Longest missing run including day edges; times denote interval ends."""
    values = np.sort(pd.to_datetime(times, utc=True).astype("int64").unique())
    left, right = start.value, end.value
    values = values[(values > left) & (values <= right)]
    edges = np.r_[left, values, right + step_seconds * 1_000_000_000]
    return int(max(0, np.diff(edges).max() // 1_000_000_000 - step_seconds))


def profile_day(frame: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """Per lane/day 2880-slot denominator, explicit offline and conflicts.

    Active-series inventory is later expanded across all days, so absent series
    days become zero coverage, not omitted from selection.
    """
    end = day + pd.Timedelta(days=1)
    selected = frame.loc[(frame.timestamp > day) & (frame.timestamp <= end)].copy()
    selected["valid_slot"] = selected.speed_kmh.notna() & ~selected.conflict
    selected["offline"] = selected.valid.eq("N")
    rows = []
    for unit, group in selected.groupby(UNIT, observed=True):
        valid = group.loc[group.valid_slot, "timestamp"]
        rows.append(dict(zip(UNIT, unit)) | {"day": day, "present_slots": len(group),
            "valid_slots": int(group.valid_slot.sum()), "offline_slots": int(group.offline.sum()),
            "conflict_slots": int(group.conflict.sum()), "repeat_rows": int(group.repeat_rows.sum()),
            "first_present": group.timestamp.min(), "last_present": group.timestamp.max(),
            "first_valid": valid.min(), "last_valid": valid.max(),
            "max_absent_gap_seconds": missing_run_seconds(group.timestamp, day, end),
            "max_invalid_or_absent_gap_seconds": missing_run_seconds(valid, day, end)})
    return pd.DataFrame(rows)


def profile_period(profile: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Join daily edge gaps, including multi-day outages, into per-lane summaries."""
    rows = []
    for unit, group in profile.groupby(UNIT, observed=True):
        group = group.sort_values("day")
        measured = {}
        for mode, first, last, gap in [
            ("absent", "first_present", "last_present", "max_absent_gap_seconds"),
            ("unusable_speed", "first_valid", "last_valid", "max_invalid_or_absent_gap_seconds")]:
            observed = group.loc[group[first].notna()]
            if observed.empty:
                maximum = int((end - start).total_seconds())
            else:
                # Only inter-day last->first gaps, not the spans inside each day.
                bridges = [(observed.iloc[0][first] - start).total_seconds() - 30,
                           (end - observed.iloc[-1][last]).total_seconds()]
                for i in range(1, len(observed)):
                    bridges.append((observed.iloc[i][first] - observed.iloc[i - 1][last]).total_seconds() - 30)
                maximum = int(max(group[gap].max(), *bridges))
            measured[f"max_{mode}_gap_seconds"] = maximum
        rows.append(dict(zip(UNIT, unit)) | measured | {
            "expected_slots": int(group.expected_slots.sum()), "present_slots": int(group.present_slots.sum()),
            "valid_slots": int(group.valid_slots.sum()), "offline_slots": int(group.offline_slots.sum()),
            "conflict_slots": int(group.conflict_slots.sum())})
    return pd.DataFrame(rows)


def process_partitions(source: Path, output: Path, start: pd.Timestamp,
                       end: pd.Timestamp) -> pd.DataFrame:
    """One archive partition in memory; retain only 20m boundary carry-over.

    Reconcile duplicate keys before finalizing bins. Observation lateness beyond
    the 20m carry window fails rather than silently corrupting finalized data.
    Full 30-second observations are not loaded across multiple days.
    """
    output.mkdir(parents=True, exist_ok=True)
    expected_dates = {d.strftime("%Y%m%d") for d in pd.date_range(start, end, freq="D")}
    present_dates = {p.stem for p in source.glob("*.parquet")}
    if not expected_dates <= present_dates:
        raise ValueError(f"Missing capture partitions (need next-day boundary): {sorted(expected_dates - present_dates)}")
    for pattern in ["bins-*.parquet", "slots-*.parquet"]:
        for old in output.glob(pattern):
            old.unlink()  # explicit rebuild of derived cache, never raw evidence
    profiles = []
    carry = None
    finalized_until = None
    for path in sorted(source.glob("*.parquet")):
        LOGGER.info("coverage_partition_start path=%s", path)
        frame = pq.read_table(path).to_pandas(categories=UNIT + ["valid", "signature", "source_file"])
        capture_day = pd.Timestamp(path.stem, tz=start.tz)
        if finalized_until is not None and frame.timestamp.le(finalized_until).any():
            raise ValueError("Late observation exceeds 20-minute finalization window")
        if carry is not None:
            frame = pd.concat([carry, frame], ignore_index=True)
        boundary = capture_day + pd.Timedelta(days=1) - pd.Timedelta(minutes=20)
        ready = frame.loc[frame.timestamp <= boundary].copy()
        carry = frame.loc[frame.timestamp > boundary].copy()
        del frame
        feature_ready = ready.loc[ready.available_at <= ready.timestamp.dt.ceil("5min") + pd.Timedelta(minutes=10)]
        bins = make_bins(deduplicate(feature_ready))
        del feature_ready
        ready = deduplicate(ready)
        # Partial day profiles are reconciled by recomputing from compact pieces
        # below: keep deduplicated daily-boundary chunks, not giant XML frames.
        compact = ready[UNIT + ["timestamp", "speed_kmh", "valid", "conflict", "repeat_rows"]]
        compact.to_parquet(output / f"slots-{path.stem}.parquet", index=False, compression="zstd")
        bins.to_parquet(output / f"bins-{path.stem}.parquet", index=False, compression="zstd")
        finalized_until = boundary
        LOGGER.info("coverage_partition_end path=%s unique_slots=%s bins=%s", path, len(ready), len(bins))
        del ready, compact, bins
    if carry is not None:
        feature_ready = carry.loc[carry.available_at <= carry.timestamp.dt.ceil("5min") + pd.Timedelta(minutes=10)]
        make_bins(deduplicate(feature_ready)).to_parquet(output / "bins-tail.parquet", index=False)
        ready = deduplicate(carry)
        ready[UNIT + ["timestamp", "speed_kmh", "valid", "conflict", "repeat_rows"]].to_parquet(output / "slots-tail.parquet", index=False)
    # Per-day read uses Parquet predicate filters; full-period slots never loaded.
    slot_files = [str(p) for p in sorted(output.glob("slots-*.parquet"))]
    day = start
    while day < end:
        LOGGER.info("coverage_profile_day day=%s", day)
        daily = pq.read_table(slot_files, filters=[("timestamp", ">", day), ("timestamp", "<=", day + pd.Timedelta(days=1))]).to_pandas(categories=UNIT + ["valid"])
        profiles.append(profile_day(daily, day))
        day += pd.Timedelta(days=1)
    profile = pd.concat(profiles, ignore_index=True)
    inventory = profile[UNIT].drop_duplicates()
    days = pd.DataFrame({"day": pd.date_range(start, end, freq="D", inclusive="left")})
    profile = inventory.merge(days, how="cross").merge(profile, on=UNIT + ["day"], how="left")
    for col in ["present_slots", "valid_slots", "offline_slots", "conflict_slots", "repeat_rows"]:
        profile[col] = profile[col].fillna(0).astype(int)
    for col in ["max_absent_gap_seconds", "max_invalid_or_absent_gap_seconds"]:
        profile[col] = profile[col].fillna(86400).astype(int)
    for col in ["first_present", "last_present", "first_valid", "last_valid"]:
        profile[col] = pd.to_datetime(profile[col], utc=True).dt.tz_convert(start.tz)
    profile["expected_slots"] = 2880
    profile["valid_coverage"] = profile.valid_slots / 2880
    profile["offline_fraction_expected"] = profile.offline_slots / 2880
    profile["offline_fraction_present"] = profile.offline_slots.div(profile.present_slots.replace(0, float("nan")))
    bin_stats = []
    for path in sorted(output.glob("bins-*.parquet")):
        bins = pd.read_parquet(path)
        bins = bins.loc[(bins.timestamp > start) & (bins.timestamp <= end)].copy()
        if bins.empty:
            continue
        bins["day"] = (bins.timestamp - pd.Timedelta(nanoseconds=1)).dt.floor("D")
        bin_stats.append(bins.groupby(UNIT + ["day"], observed=True).agg(
            valid_5m_bins=("valid_slots", lambda x: x.ge(2).sum()),
            usable_5m_bins=("usable", "sum")).reset_index())
    bstats = pd.concat(bin_stats).groupby(UNIT + ["day"], observed=True)[["valid_5m_bins", "usable_5m_bins"]].sum().reset_index()
    profile = profile.merge(bstats, on=UNIT + ["day"], how="left")
    profile[["valid_5m_bins", "usable_5m_bins"]] = profile[["valid_5m_bins", "usable_5m_bins"]].fillna(0).astype(int)
    profile["valid_5m_coverage"] = profile.valid_5m_bins / 288
    profile["usable_5m_coverage"] = profile.usable_5m_bins / 288
    return profile
