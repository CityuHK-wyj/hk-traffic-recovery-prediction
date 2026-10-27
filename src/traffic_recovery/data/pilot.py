"""Coverage-filtered real-event pilot CLI. No ML fitting or context enrichment."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import json
import logging
import platform
import os
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from traffic_recovery.data.coverage import profile_period
from traffic_recovery.data.bounded_coverage import run_bounded
from traffic_recovery.data.events import EventRules, HORIZONS, UNIT, assign_splits, build_events, fit_reference
from traffic_recovery.data.http import sha256_file

LOGGER = logging.getLogger(__name__)


def label_summary(events: pd.DataFrame) -> dict:
    """Actual counts per horizon, nulls explicit; empty events are not fabricated."""
    result = {"events": len(events), "horizons": {}}
    for h in HORIZONS:
        values = events.get(f"label_{h}m", pd.Series(dtype="Int8"))
        result["horizons"][str(h)] = {"positive": int(values.eq(1).sum()), "negative": int(values.eq(0).sum()),
            "unknown": int(values.isna().sum()),
            "reasons": events[f"reason_{h}m"].value_counts().to_dict() if len(events) else {}}
    return result


def select_cohort(profile: pd.DataFrame, selection_end: pd.Timestamp,
                  config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Historical-only selection; compare 30s vs 5m coverage without equating them.

    One lane per detector/direction avoids dependent same-road lane samples.
    Sort by reference-period flow coverage, then valid coverage, then lane name.
    Deterministic max_units cap uses detector ID order, NOT downstream event counts.
    """
    history = profile.loc[profile.day < selection_end]
    summary = history.groupby(UNIT, observed=True).agg(
        valid_30s_mean=("valid_coverage", "mean"), valid_30s_min=("valid_coverage", "min"),
        valid_5m_mean=("valid_5m_coverage", "mean"), valid_5m_min=("valid_5m_coverage", "min"),
        flow_5m_mean=("usable_5m_coverage", "mean"), conflicts=("conflict_slots", "sum"),
        max_gap_seconds=("max_invalid_or_absent_gap_seconds", "max")).reset_index()
    comparisons = []
    for resolution in ["30s", "5m"]:
        for cutoff in [0.90, 0.95]:
            for policy in ["mean", "min"]:
                eligible = summary.loc[summary[f"valid_{resolution}_{policy}"] >= cutoff]
                comparisons.append({"resolution": resolution, "cutoff": cutoff, "policy": policy,
                    "lane_units": len(eligible), "detectors": eligible.detector_id.nunique()})
    summary["selected_by_coverage"] = ((summary.valid_5m_mean >= config["valid_5m_mean_min"])
        & (summary.valid_5m_min >= config["valid_5m_daily_min"])
        & (summary.flow_5m_mean >= config["flow_5m_mean_min"]) & summary.conflicts.eq(0))
    eligible = summary.loc[summary.selected_by_coverage].sort_values(
        ["detector_id", "direction", "flow_5m_mean", "valid_5m_mean", "lane_id"],
        ascending=[True, True, False, False, True]).drop_duplicates(["detector_id", "direction"])
    cohort = eligible.sort_values(["detector_id", "direction"]).head(config["max_units"])
    return cohort, pd.DataFrame(comparisons)


def plot_events(events: pd.DataFrame, bins: pd.DataFrame, output: Path) -> list[str]:
    """Six deterministic outcome-stratified examples from actual events, no smoothing."""
    output.mkdir(parents=True, exist_ok=True)
    selected = []
    for label in [1, 0, None]:
        mask = events.label_60m.isna() if label is None else events.label_60m.eq(label)
        selected.extend(events.loc[mask].sort_values("prediction_time").head(2).index)
    files = []
    for index in selected:
        event = events.loc[index]
        lane = bins
        for key in UNIT:
            lane = lane.loc[lane[key] == event[key]]
        lane = lane.loc[(lane.timestamp >= event.onset_time - pd.Timedelta(minutes=45))
                        & (lane.timestamp <= event.prediction_time + pd.Timedelta(minutes=90))].copy()
        lane = lane.set_index("timestamp").reindex(pd.date_range(lane.timestamp.min(), lane.timestamp.max(), freq="5min"))
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(lane.index, lane.speed_kmh.where(lane.usable.eq(True)), marker=".", label="5m median, positive-flow valid slots")
        ax.axhline(event.baseline_kmh, color="0.5", linestyle=":", label="historical reference (85th percentile)")
        ax.axhline(event.baseline_kmh * event.congestion_ratio, color="red", linestyle="--", label=f"congestion ratio {event.congestion_ratio}")
        ax.axhline(event.baseline_kmh * event.recovery_ratio, color="green", linestyle="--", label=f"recovery ratio {event.recovery_ratio}")
        ax.axvline(event.onset_confirmed_at, color="orange", linestyle=":", label="observed onset confirmation")
        ax.axvline(event.prediction_time, color="black", label="archive prediction time")
        if pd.notna(event.recovery_time):
            ax.axvline(event.recovery_time, color="green", label="observed sustained recovery confirmation")
        else:
            ax.axvline(event.followup_end, color="purple", label="last valid observed follow-up")
        labels = ", ".join(f"{h}m={event[f'label_{h}m']}" for h in HORIZONS)
        ax.set(title=f"Real event {event.event_id}: {event.detector_id}, {event.direction}, {event.lane_id}\n{labels}; provisional rules; timestamps HKT",
               ylabel="Speed (km/h)", xlabel="HKT: observation bin end (curve/outcome); archive decision time (black line)")
        ax.legend(fontsize=7, ncol=2)
        fig.autofmt_xdate()
        fig.tight_layout()
        target = output / f"event-{event.event_id}.png"
        fig.savefig(target, dpi=140)
        plt.close(fig)
        files.append(target.as_posix())
    return files


def write_reports(statistics: dict, comparison: pd.DataFrame, cohort: pd.DataFrame, output: Path) -> None:
    """Write numerical Markdown directly from measured outputs, never hand-enter counts."""
    s = statistics
    lines = ["# Cohort selection — provisional pilot", "", "Generated from real Parquet observations; no synthetic research rows.", "",
        f"Full observation days: **{s['observed_days']}**; observed detectors: **{s['detectors']}**; lane units: **{s['lane_units']}**.",
        f"Slots: {s['present_lane_slots']:,} present / {s['expected_lane_slots']:,} expected; {s['valid_lane_slots']:,} valid-speed slots.",
        f"Offline: {s['offline_slots']:,}; conflicting keys: {s['conflict_keys']:,}; extra repeated archive-key rows: {s['repeat_rows']:,}.", "",
        "## Candidate filters on historical selection days only", "",
        "| Resolution | Threshold | Policy across selection days | Lane units | Detectors |", "|---|---:|---|---:|---:|"]
    for _, row in comparison.iterrows():
        lines.append(f"| {row.resolution} | {row.cutoff:.0%} | {row.policy} | {row.lane_units} | {row.detectors} |")
    lines.extend(["", "30s coverage and sparse-5m-bin coverage measure different things and are NOT interchangeable.",
        "A 5m bin needs >=2 valid slots, not all ten. The event series also requires positive volume in >=2 slots and no conflict.",
        f"Neither 90% nor 95% is a scientific optimum. Selection policy: {s['selection_policy']}.",
        "Require no reference-selection conflicts.",
        "Choose one lane per detector/direction by historical flow then valid coverage; ties by lane name; cap by detector-ID order.",
        "Selection does not inspect validation/test coverage or event counts. Low future coverage causes censoring, not retrospective exclusion.", "",
        f"Selected: **{s['selected_lane_units']} lane units / {s['selected_detectors']} detectors**, before reference cutoff {s['reference_window_end']}.",
        f"Historical selection ends {s['selection_window_end']}. Evaluation usable-bin fraction: **{s['cohort_evaluation_usable_bin_fraction']:.2%}**.",
        "See [cohort.csv](cohort.csv), [coverage_lane_period.csv](coverage_lane_period.csv) and the detailed lane/day and detector/day tables.", "",
        "## Historical reference", "", "85th percentile of usable positive-speed, positive-flow lane-bin medians; >=300 reference bins;",
        "observation AND archive closure before fit end. This is a candidate normal-speed reference, not verified free-flow or posted speed.",
        f"Reference km/h min/median/max: {s['reference_baseline_kmh']}. All-hours pooling may understate uncongested speed on chronically congested roads.",
        "Unit identities, fit counts and fitted values are auditable in cohort.csv. No imputation or ML fitting.", ""])
    (output / "cohort_selection.md").write_text("\n".join(lines), encoding="utf-8")
    lines = ["# Label quality — provisional 15/30/60-minute pilot", "",
        f"**{s['labels']['events']}** witnessed onset samples, one prediction/event, no overlapping 60m prediction windows on the same lane.",
        "These are not proven statistically independent across detectors/roads/days. Left-censored onsets are excluded.", "",
        "| Horizon | Positive | Negative | Unknown/censored |", "|---|---:|---:|---:|"]
    for horizon, values in s["labels"]["horizons"].items():
        lines.append(f"| {horizon} min | {values['positive']} | {values['negative']} | {values['unknown']} |")
    lines.extend(["", "Target: " + s["target"] + ".", "",
        f"Candidate rules: {s['default_rules']}. Persistence counts are consecutive usable bins.",
        "Initial onset must follow witnessed recovered state. Missing/invalid timestamps break persistence and censor follow-up.",
        "Recovery is the third high bin end, never the first high bin or the horizon endpoint state.",
        "Prediction uses fixed +10m archive-bin closure; source captures after closure cannot enter features.",
        "A negative needs uninterrupted usable bins through prediction+horizon; otherwise null. Shorter horizons can be known when longer ones are not.",
        "Sparse observations cannot rule out unobserved within-bin physical transitions; label validity is limited to this sampled confirmation definition.", "",
        "## Threshold sensitivity (same historical cohort/reference, no tuning on test outcomes)", "",
        "| Congestion | Recovery | Events | 15m + / - / NA | 30m + / - / NA | 60m + / - / NA |", "|---:|---:|---:|---|---|---|"])
    for item in s["sensitivity"]:
        counts = [" / ".join(str(item["horizons"][str(h)][k]) for k in ["positive", "negative", "unknown"]) for h in HORIZONS]
        lines.append(f"| {item['rules']['congestion']} | {item['rules']['recovery']} | {item['events']} | " + " | ".join(counts) + " |")
    lines.extend(["", "These are descriptive sensitivity results, not test-set threshold selection or scientifically established cutoffs.",
        "## Split proposal", "", f"Time boundaries (end-exclusive): {s['windows']}. Reference ends at candidate training start.",
        "Purge 60m label windows crossing boundaries; embargo first 60m of validation/test; require full episode separation before earlier folds end.",
        "Censored episodes can remain in earlier folds only if later witnessed rearming proves separation; their labels remain null.",
        f"Proposal counts: {s['split_proposal_counts']}. Per-split labels: [pilot_statistics.json](pilot_statistics.json).",
        "No random split, no final model-ready split approval, no training. Shared-road dependence and class support must be reviewed.", "",
        "## Event visualizations", "", "Deterministic first two available examples per 60m outcome stratum (positive, negative, unknown); not representative prevalence sampling."])
    for path in s["figures"]:
        lines.append(f"- [{Path(path).name}](event_figures/{Path(path).name})")
    lines.append("")
    (output / "label_quality.md").write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    """Generate measured reports, a real events.parquet and checksummed manifest."""
    config = json.loads(args.config.read_text(encoding="utf-8"))
    dates = {name: pd.Timestamp(config[name]).tz_convert("Asia/Hong_Kong") for name in
             ["observation_start", "observation_end", "selection_end", "reference_end", "validation_start", "test_start"]}
    args.output.mkdir(parents=True, exist_ok=True)
    args.report.mkdir(parents=True, exist_ok=True)
    coverage_file = args.output / "coverage_lane_day.parquet"
    coverage_manifest = args.output / "coverage_manifest.json"
    fingerprint = {"version": "bounded-coverage-v1", "start": str(dates["observation_start"]),
                   "end": str(dates["observation_end"]),
                   "sources": {p.name: sha256_file(p) for p in sorted((args.input / "lane_snapshots").glob("*.parquet"))}}
    if args.reuse_coverage and coverage_file.exists():
        recorded = json.loads(coverage_manifest.read_text(encoding="utf-8"))
        if recorded["inputs"] != fingerprint or recorded["sha256"] != sha256_file(coverage_file):
            raise ValueError("Coverage cache differs from input/configuration; recompute without --reuse-coverage")
    # Always validate all per-day checksums before using their bin files.
    profile = run_bounded(args.input / "lane_snapshots", args.output / "compact-bounded-v1", dates["observation_start"], dates["observation_end"])
    if not args.reuse_coverage or not coverage_file.exists():
        tmp = coverage_file.with_suffix(".partial")
        profile.to_parquet(tmp, index=False)
        os.replace(tmp, coverage_file)
        manifest_tmp = coverage_manifest.with_suffix(".partial")
        manifest_tmp.write_text(json.dumps({"inputs": fingerprint, "sha256": sha256_file(coverage_file)}, indent=2) + "\n", encoding="utf-8")
        os.replace(manifest_tmp, coverage_manifest)
    profile.to_csv(args.report / "coverage_lane_day.csv", index=False)
    period_profile = profile_period(profile, dates["observation_start"], dates["observation_end"])
    period_profile.to_csv(args.report / "coverage_lane_period.csv", index=False)
    detector_profile = profile.groupby(["detector_id", "direction", "day"], observed=True).agg(
        lane_count=("lane_id", "size"), expected_lane_slots=("expected_slots", "sum"),
        present_slots=("present_slots", "sum"), valid_slots=("valid_slots", "sum"),
        offline_slots=("offline_slots", "sum"), conflict_slots=("conflict_slots", "sum"),
        max_lane_invalid_gap_seconds=("max_invalid_or_absent_gap_seconds", "max")).reset_index()
    detector_profile["valid_lane_slot_coverage"] = detector_profile.valid_slots / detector_profile.expected_lane_slots
    detector_profile.to_csv(args.report / "coverage_detector_day.csv", index=False)
    cohort, comparison = select_cohort(profile, dates["selection_end"], config)
    comparison.to_csv(args.report / "coverage_filter_comparison.csv", index=False)
    if cohort.empty:
        raise ValueError("No cohort passes configured filters; report candidates, do not silently relax")
    filters = [[(key, "==", row[key]) for key in UNIT] for _, row in cohort.iterrows()]
    bins = pd.read_parquet([str(p) for p in sorted((args.output / "compact-bounded-v1").glob("bins-*.parquet"))], filters=filters)
    reference = fit_reference(bins, fit_start=dates["observation_start"], fit_end=dates["reference_end"], min_bins=config["min_reference_bins"])
    cohort = cohort.merge(reference, on=UNIT, how="inner", validate="one_to_one")
    if cohort.empty:
        raise ValueError("No lane has sufficient pre-evaluation reference")
    cohort.to_csv(args.report / "cohort.csv", index=False)
    bins = bins.merge(cohort[UNIT], on=UNIT, how="inner", validate="many_to_one").sort_values(UNIT + ["timestamp"])
    bins.to_parquet(args.output / "cohort_bins.parquet", index=False, compression="zstd")
    rules = EventRules(config["congestion_ratio"], config["recovery_ratio"], config["onset_bins"], config["recovery_bins"])

    def construct(current: EventRules) -> pd.DataFrame:
        frames = []
        for _, unit in cohort.iterrows():
            lane = bins
            for key in UNIT:
                lane = lane.loc[lane[key] == unit[key]]
            result = build_events(lane, unit.baseline_kmh, start=dates["reference_end"], end=dates["observation_end"], rules=current)
            if len(result):
                result["reference_fit_end"] = dates["reference_end"]
                frames.append(result)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    events = construct(rules)
    if events.empty:
        raise ValueError("No witnessed events under configured rule; never substitute synthetic events")
    events["split_proposal"] = assign_splits(events, dates["validation_start"], dates["test_start"], dates["observation_end"])
    events.to_parquet(args.output / "events.parquet", index=False, compression="zstd")
    events.to_csv(args.report / "events_review.csv", index=False)
    sensitivity = []
    for congestion in config["sensitivity_congestion"]:
        for recovery in config["sensitivity_recovery"]:
            current = EventRules(congestion, recovery, rules.onset_bins, rules.recovery_bins)
            measured = events if current == rules else construct(current)
            sensitivity.append({"rules": asdict(current), **label_summary(measured)})
    cohort_quality = period_profile.merge(cohort[UNIT], on=UNIT, how="inner", validate="one_to_one")
    statistics = {"version": config["version"], "provisional": True,
        "windows": {key: value.isoformat() for key, value in dates.items()}, "default_rules": asdict(rules),
        "selection_policy": {key: config[key] for key in ["valid_5m_mean_min", "valid_5m_daily_min", "flow_5m_mean_min", "max_units"]},
        "observed_days": int(profile.day.nunique()), "detectors": int(profile.detector_id.nunique()),
        "lane_units": len(profile[UNIT].drop_duplicates()), "expected_lane_slots": int(profile.expected_slots.sum()),
        "present_lane_slots": int(profile.present_slots.sum()), "valid_lane_slots": int(profile.valid_slots.sum()),
        "offline_slots": int(profile.offline_slots.sum()), "conflict_keys": int(profile.conflict_slots.sum()),
        "repeat_rows": int(profile.repeat_rows.sum()), "max_invalid_gap_seconds": int(period_profile.max_unusable_speed_gap_seconds.max()),
        "max_absent_gap_seconds": int(period_profile.max_absent_gap_seconds.max()),
        "selected_lane_units": len(cohort), "selected_detectors": int(cohort.detector_id.nunique()),
        "selection_window_end": dates["selection_end"].isoformat(), "reference_window_end": dates["reference_end"].isoformat(),
        "cohort_evaluation_usable_bin_fraction": float(bins.loc[(bins.timestamp >= dates["reference_end"]) & (bins.timestamp < dates["observation_end"])].usable.sum()
            / (len(cohort) * (dates["observation_end"] - dates["reference_end"]).total_seconds() / 300)),
        "reference_baseline_kmh": {"min": float(cohort.baseline_kmh.min()), "median": float(cohort.baseline_kmh.median()), "max": float(cohort.baseline_kmh.max())},
        "cohort_quality": {"expected_30s_slots": int(cohort_quality.expected_slots.sum()),
            "present_30s_slots": int(cohort_quality.present_slots.sum()), "valid_30s_slots": int(cohort_quality.valid_slots.sum()),
            "offline_slots": int(cohort_quality.offline_slots.sum()), "conflict_keys": int(cohort_quality.conflict_slots.sum()),
            "max_absent_gap_seconds": int(cohort_quality.max_absent_gap_seconds.max()),
            "max_unusable_speed_gap_seconds": int(cohort_quality.max_unusable_speed_gap_seconds.max())},
        "labels": label_summary(events), "sensitivity": sensitivity,
        "split_proposal_counts": events.split_proposal.value_counts().to_dict(),
        "split_label_counts": {s: label_summary(g) for s, g in events.groupby("split_proposal")},
        "figures": plot_events(events, bins, args.report / "event_figures"),
        "target": "within horizon after archive prediction time of observed sustained recovery confirmation; not exact physical transition",
        "features": {"allowlist": ["speed_kmh", "speed_ratio", "baseline_kmh", "valid_slots", "onset_observed_minutes"],
                     "availability_rule": "fixed bin-end +10m closure; only source captures by closure; no future bins; historical-only reference"}}
    (args.report / "pilot_statistics.json").write_text(json.dumps(statistics, indent=2) + "\n", encoding="utf-8")
    write_reports(statistics, comparison, cohort, args.report)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "config": config,
        "config_sha256": sha256_file(args.config), "uv_lock_sha256": sha256_file(Path("uv.lock")),
        "software": {"python": platform.python_version(), "platform": platform.platform(),
                     **{name: version(name) for name in ["pandas", "pyarrow", "numpy", "matplotlib", "shapely"]}},
        "source_code_sha256": {p.as_posix(): sha256_file(p) for p in sorted(Path("src/traffic_recovery").rglob("*.py"))},
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip(),
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain"], check=True, capture_output=True, text=True).stdout.strip()),
        "sources": json.loads((args.input / "ingest.json").read_text(encoding="utf-8")),
        "outputs": {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in
                    [coverage_file, args.output / "events.parquet", args.output / "cohort_bins.parquet"]},
        "excluded": ["no-flow speed slots", "conflicting keys", "insufficiently covered reference units", "left-censored onsets", "within-unit 60m overlap"],
        "reuse_coverage": args.reuse_coverage, "availability": statistics["features"]["availability_rule"]}
    (args.report / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return statistics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/pilot.json"))
    parser.add_argument("--input", type=Path, default=Path("data/local/pilot"))
    parser.add_argument("--output", type=Path, default=Path("data/local/pilot/derived"))
    parser.add_argument("--report", type=Path, default=Path("reports/milestone2"))
    parser.add_argument("--reuse-coverage", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run(args)
    print(json.dumps({k: v for k, v in result.items() if k != "sensitivity"}, indent=2))


if __name__ == "__main__":
    main()
