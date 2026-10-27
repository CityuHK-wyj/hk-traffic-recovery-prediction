"""Controlled real-data scalability/event verification, not the full study cohort."""
import argparse
import json
from pathlib import Path
import sys

try:
    import resource
except ImportError:
    resource = None
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pyarrow.dataset as ds

from traffic_recovery.data.bounded_coverage import COLUMNS, _scan, _time_filter, run_bounded
from traffic_recovery.data.coverage import deduplicate, make_bins, profile_day
from traffic_recovery.data.events import HORIZONS, UNIT, build_events, fit_reference
from traffic_recovery.data.http import sha256_file
from traffic_recovery.data.pilot import label_summary

START = pd.Timestamp("2026-10-18", tz="Asia/Hong_Kong")
FIT_END = pd.Timestamp("2026-10-20", tz="Asia/Hong_Kong")
END = pd.Timestamp("2026-10-21", tz="Asia/Hong_Kong")
SOURCE = Path("data/local/pilot/lane_snapshots")
METADATA = Path("data/sample/verified/detectors.csv")


def io_counts() -> dict[str, int]:
    """Linux process I/O counters, distinguishing logical from physical disk bytes."""
    path = Path("/proc/self/io")
    if not path.exists():
        return {}
    return {key: int(value) for key, value in
            (line.split(":") for line in path.read_text(encoding="utf-8").splitlines())}


def cohort() -> list[str]:
    """First 40 metadata IDs alphabetically; deterministic, not a research cohort."""
    frame = pd.read_csv(METADATA, dtype={"AID_ID_Number": str}, encoding="utf-8-sig")
    return sorted(frame.AID_ID_Number.unique())[:40]


def coverage(output: Path) -> None:
    """Measure actual scanner and checkpoint cost inside the same process."""
    started = time.perf_counter()
    before = io_counts()
    profile = run_bounded(SOURCE, output, START, END, detectors=cohort(), group_size=2)
    io = {key: value - before[key] for key, value in io_counts().items()}
    measured = {"wall_seconds": time.perf_counter() - started, "io": io,
        "max_rss_kib_process": (
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if resource is not None and sys.platform.startswith("linux")
            else None
        ),
        "detectors_requested": cohort(), "observed_detectors": int(profile.detector_id.nunique()),
        "lane_days": len(profile), "present_slots": int(profile.present_slots.sum()),
        "valid_slots": int(profile.valid_slots.sum()), "offline_slots": int(profile.offline_slots.sum()),
        "conflict_slots": int(profile.conflict_slots.sum()), "repeat_rows": int(profile.repeat_rows.sum()),
        "checkpoint_count": len(list(output.glob("checkpoint-*.json"))),
        "output_bytes": sum(p.stat().st_size for p in output.iterdir() if p.is_file())}
    print(json.dumps(measured, indent=2))


def reference_check(output: Path) -> dict:
    """Compare real one-day/two-detector slots and bins with unpartitioned rules."""
    ids = cohort()[:2]
    day = START
    dataset = ds.dataset([str(p) for p in sorted(SOURCE.glob("*.parquet"))], format="parquet")
    exp = _time_filter(day, day + pd.Timedelta(days=1)) & ds.field("detector_id").isin(ids)
    batches = [b for b in _scan(dataset, COLUMNS, exp, 32768).to_batches() if b.num_rows]
    import pyarrow as pa
    frame = pa.Table.from_batches(batches).to_pandas()
    quality = deduplicate(frame)
    expected_profile = profile_day(quality, day)
    available = frame.loc[frame.available_at <= frame.timestamp.dt.ceil("5min") + pd.Timedelta(minutes=10)]
    expected_bins = make_bins(deduplicate(available))
    actual_profile = pd.read_parquet(output / "profile-20261018.parquet")
    actual_profile = actual_profile.loc[actual_profile.detector_id.isin(ids), expected_profile.columns]
    actual_bins = pd.read_parquet(output / "bins-20261018.parquet")
    actual_bins = actual_bins.loc[actual_bins.detector_id.isin(ids), expected_bins.columns]
    def compare(left: pd.DataFrame, right: pd.DataFrame, key: list[str]) -> None:
        pd.testing.assert_frame_equal(left.sort_values(key).reset_index(drop=True).sort_index(axis=1),
            right.sort_values(key).reset_index(drop=True).sort_index(axis=1), check_dtype=False, check_categorical=False)
    compare(expected_profile, actual_profile, UNIT + ["day"])
    compare(expected_bins, actual_bins, UNIT + ["timestamp"])
    return {"status": "passed", "detectors": ids, "archive_rows": len(frame),
            "unique_keys": len(quality), "bins": len(expected_bins), "profile_rows": len(expected_profile),
            "scope": "one day/two detectors, all supplied capture files; existing in-memory rules"}


def event_plot(event: pd.Series, bins: pd.DataFrame, target: Path) -> None:
    """Show real 5m speeds, explicit missing bins, thresholds and event boundaries."""
    lane = bins
    for key in UNIT:
        lane = lane.loc[lane[key] == event[key]]
    left = max(FIT_END, event.onset_time - pd.Timedelta(minutes=45))
    right = min(END - pd.Timedelta(minutes=5), event.prediction_time + pd.Timedelta(minutes=90))
    lane = lane.set_index("timestamp").reindex(pd.date_range(left, right, freq="5min"))
    valid = lane.usable.eq(True) & lane.speed_kmh.notna()
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(lane.index, lane.speed_kmh.where(valid), marker=".", label="observed usable 5m speed")
    missing = lane.index[~valid]
    for stamp in missing:
        ax.axvspan(stamp - pd.Timedelta(minutes=2.5), stamp + pd.Timedelta(minutes=2.5), color="0.8", alpha=.6)
    if len(missing):
        ax.scatter(missing, [0] * len(missing), marker="x", color="black", s=18, label="missing/unusable bin (marker at axis baseline)")
    ax.axhline(event.baseline_kmh, color="0.4", linestyle=":", label="historical 85th percentile")
    ax.axhline(event.baseline_kmh * event.congestion_ratio, color="red", linestyle="--", label="congestion ratio 0.5")
    ax.axhline(event.baseline_kmh * event.recovery_ratio, color="green", linestyle="--", label="recovery ratio 0.8")
    ax.axvline(event.onset_time, color="orange", linestyle="--", label="first witnessed low bin")
    ax.axvline(event.onset_confirmed_at, color="orange", linestyle=":", label="onset confirmed")
    ax.axvline(event.prediction_time, color="black", label="prediction (archive closure)")
    if pd.notna(event.recovery_time):
        ax.axvline(event.recovery_time, color="green", label="recovery confirmed")
    else:
        ax.axvline(event.followup_end, color="purple", label="last observed follow-up")
    labels = ", ".join(f"{h}m={event[f'label_{h}m']}" for h in HORIZONS)
    ax.set(title=f"Real event {event.event_id}: {event.detector_id} / {event.direction} / {event.lane_id}\n{labels}; {event.termination_reason}; provisional thresholds",
           xlabel="HKT: observation bin end; black line denotes prediction availability", ylabel="Speed km/h")
    ax.legend(fontsize=7, ncol=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(target, dpi=130)
    plt.close(fig)


def validate_event_rows(events: pd.DataFrame, bins: pd.DataFrame) -> dict:
    """Independently check real label windows, recovery persistence and leakage."""
    assert not events.event_id.duplicated().any()
    for _, group in events.groupby(UNIT, observed=True):
        assert group.sort_values("prediction_time").prediction_time.diff().dropna().gt(pd.Timedelta(minutes=60)).all()
    for _, event in events.iterrows():
        unit = bins
        for key in UNIT:
            unit = unit.loc[unit[key] == event[key]]
        assert event.feature_max_available_at <= event.prediction_time
        assert event.reference_fit_end <= event.onset_time
        onset = unit.loc[unit.timestamp.between(event.onset_time, event.onset_confirmed_at)]
        assert len(onset) == event.onset_bins and onset.usable.all()
        assert onset.speed_kmh.le(event.baseline_kmh * event.congestion_ratio).all()
        assert onset.available_at.le(event.prediction_time).all()
        follow = unit.loc[unit.timestamp.between(event.onset_confirmed_at, event.followup_end)]
        assert follow.usable.all()
        assert len(follow) == int((event.followup_end - event.onset_confirmed_at).total_seconds() / 300) + 1
        if pd.notna(event.recovery_time):
            recovered = unit.loc[(unit.timestamp <= event.recovery_time) &
                (unit.timestamp > event.recovery_time - pd.Timedelta(minutes=5 * event.recovery_bins))]
            assert len(recovered) == event.recovery_bins and recovered.usable.all()
            assert recovered.speed_kmh.ge(event.baseline_kmh * event.recovery_ratio).all()
            assert event.recovery_time > event.prediction_time
        known = []
        for h in HORIZONS:
            label = event[f"label_{h}m"]
            deadline = event.prediction_time + pd.Timedelta(minutes=h)
            if pd.isna(label):
                assert event.followup_end < deadline and (pd.isna(event.recovery_time) or event.recovery_time > deadline)
            else:
                known.append(int(label))
                if label == 1:
                    assert pd.notna(event.recovery_time) and event.recovery_time <= deadline
                else:
                    assert event.followup_end >= deadline and (pd.isna(event.recovery_time) or event.recovery_time > deadline)
        assert known == sorted(known)
    return {"status": "passed", "events_checked": len(events), "checks": ["historical reference boundary",
        "onset persistence and availability", "complete follow-up", "sustained recovery", "horizon labels and censoring",
        "monotonicity", "same-lane 60-minute separation"]}


def events(output: Path, report: Path) -> None:
    """Derive events only after frozen reference end; no synthetic research rows."""
    report.mkdir(parents=True, exist_ok=True)
    # Revalidate source fingerprints and every daily output before consuming bins.
    run_bounded(SOURCE, output, START, END, detectors=cohort(), group_size=2)
    checks = reference_check(output)
    bins = pd.concat([pd.read_parquet(p) for p in sorted(output.glob("bins-*.parquet"))], ignore_index=True)
    reference = fit_reference(bins, fit_start=START, fit_end=FIT_END, min_bins=300)
    frames = []
    for _, ref in reference.iterrows():
        lane = bins
        for key in UNIT:
            lane = lane.loc[lane[key] == ref[key]]
        found = build_events(lane, ref.baseline_kmh, start=FIT_END, end=END)
        if len(found):
            found["reference_fit_end"] = FIT_END
            frames.append(found)
    if not frames:
        raise ValueError("No real events observed; no substitute allowed")
    result = pd.concat(frames, ignore_index=True)
    validation = validate_event_rows(result, bins)
    result.to_parquet(output / "medium_events.parquet", index=False)
    result.to_csv(report / "events.csv", index=False)
    reference.to_csv(report / "reference.csv", index=False)
    chosen = []
    for state in [1, 0, None]:
        mask = result.label_60m.isna() if state is None else result.label_60m.eq(state)
        chosen += result.loc[mask].sort_values("prediction_time").head(2).index.tolist()
    figure_dir = report / "figures"
    figure_dir.mkdir(exist_ok=True)
    figures = []
    for idx in chosen:
        event = result.loc[idx]
        target = figure_dir / f"event-{event.event_id}.png"
        event_plot(event, bins, target)
        figures.append(target.as_posix())
    stats = {"reference_start": START.isoformat(), "reference_end": FIT_END.isoformat(), "event_end": END.isoformat(),
        "reference_lanes": len(reference), "reference_detectors": int(reference.detector_id.nunique()),
        "baseline_rule": "85th percentile usable positive-flow bins, >=300 bins, available before fit end",
        "cohort": "first 40 detector metadata IDs, convenience sample; not coverage-selected or independent roads",
        "rules": "0.5 congestion two bins; 0.8 recovery three bins; 10m archive closure; fully observed within labels",
        "labels": label_summary(result), "termination_counts": result.termination_reason.value_counts().to_dict(),
        "event_detector_count": int(result.detector_id.nunique()),
        "event_lane_count": len(result[UNIT].drop_duplicates()),
        "detector_direction_onset_groups": len(result[["detector_id", "direction", "onset_time"]].drop_duplicates()),
        "event_row_checks": validation,
        "figures": figures, "reference_check": checks,
        "events_sha256": sha256_file(output / "medium_events.parquet"),
        "bin_sha256": {p.name: sha256_file(p) for p in sorted(output.glob("bins-*.parquet"))}}
    (report / "statistics.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["coverage", "events"])
    parser.add_argument("--output", type=Path, default=Path("data/local/pilot/medium-40"))
    parser.add_argument("--report", type=Path, default=Path("reports/medium_pilot"))
    args = parser.parse_args()
    if args.mode == "coverage":
        coverage(args.output)
    else:
        events(args.output, args.report)


if __name__ == "__main__":
    main()
