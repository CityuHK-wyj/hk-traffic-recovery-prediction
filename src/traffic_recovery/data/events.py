"""Provisional lane-level events with training-only reference and explicit censoring.

All thresholds are research candidates, not established congestion definitions.
Targets use the observed sustained recovery confirmation time, never backdated
first-high times. Bin-end +10m replay is a conservative availability policy, not
a retrospective claim about exact publication or physical recovery instants.
"""
from dataclasses import dataclass
import hashlib
import math

import pandas as pd

HORIZONS = (15, 30, 60)
UNIT = ["detector_id", "direction", "lane_id"]
FEATURES = ["speed_kmh", "speed_ratio", "baseline_kmh", "valid_slots", "onset_observed_minutes"]


@dataclass(frozen=True)
class EventRules:
    """Ratios to historical reference, persistence in consecutive 5-minute bins."""
    congestion: float = 0.5
    recovery: float = 0.8
    onset_bins: int = 2
    recovery_bins: int = 3
    step_minutes: int = 5

    def __post_init__(self) -> None:
        if not (0 < self.congestion < self.recovery <= 1):
            raise ValueError("Require 0 < congestion < recovery <= 1")
        if min(self.onset_bins, self.recovery_bins, self.step_minutes) < 1:
            raise ValueError("Persistence and step must be positive")


def fit_reference(bins: pd.DataFrame, *, fit_start: pd.Timestamp,
                  fit_end: pd.Timestamp, min_bins: int = 300) -> pd.DataFrame:
    """Fit per-lane 85th-percentile positive-flow speeds, only available history.

    [fit_start, fit_end) applies to BOTH observation and conservative availability
    times. Raises for naive boundaries; validation/test rows cannot affect fit.
    Units without min_bins finite positive speeds receive no reference.
    """
    if fit_start.tzinfo is None or fit_end.tzinfo is None or fit_start >= fit_end:
        raise ValueError("Require aware ordered fit boundaries")
    history = bins.loc[(bins.timestamp >= fit_start) & (bins.timestamp < fit_end)
                       & (bins.available_at < fit_end) & bins.usable
                       & bins.speed_kmh.gt(0) & bins.speed_kmh.lt(float("inf"))]
    reference = history.groupby(UNIT, observed=True).speed_kmh.agg(
        baseline_kmh=lambda x: x.quantile(0.85), reference_bins="count").reset_index()
    reference = reference.loc[reference.reference_bins >= min_bins].copy()
    reference["reference_fit_start"] = fit_start
    reference["reference_fit_end"] = fit_end
    return reference


def build_events(series: pd.DataFrame, baseline: float, *, start: pd.Timestamp,
                 end: pd.Timestamp, rules: EventRules = EventRules()) -> pd.DataFrame:
    """Build one onset-confirmation row/event on one lane and an explicit grid.

    Require prior sustained recovery to arm onset (left-boundary congestion is
    not a new event). Two low bins confirm onset; three high bins confirm end.
    Missing/invalid bins terminate follow-up as unknown, never as recovery or 0.
    After any event require recovered rearming AND a 60-minute prediction embargo.
    A positive requires a fully witnessed sustained run before censoring; negatives
    require uninterrupted valid follow-up through the deadline. Outcome time is
    the observed confirmation bin end; its archive availability is a separate
    outcome field. At onset, lag must be shorter than earliest recovery persistence
    so a qualifying recovery cannot already predate the prediction.
    Returns an empty frame if no events; raises on duplicate/naive/unordered times.
    """
    if not math.isfinite(baseline) or baseline <= 0 or start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Invalid reference or boundaries")
    if series.empty:
        return pd.DataFrame()
    if not isinstance(series.timestamp.dtype, pd.DatetimeTZDtype) or not isinstance(series.available_at.dtype, pd.DatetimeTZDtype):
        raise ValueError("Observation and availability times must be aware")
    if series[UNIT].drop_duplicates().shape[0] != 1 or series.timestamp.duplicated().any():
        raise ValueError("Require one unique lane series")
    source = series.sort_values("timestamp").set_index("timestamp")
    if (source.available_at < source.index).any():
        raise ValueError("Availability precedes observation")
    identity = tuple(str(series.iloc[0][c]) for c in UNIT)
    grid = pd.date_range(start, end, freq=f"{rules.step_minutes}min", inclusive="left")
    source = source.reindex(grid)
    # Replay ordered complete bins at their cumulative arrival watermark. A late
    # earlier bin cannot retrospectively be used at an earlier prediction time.
    source["available_at"] = source.available_at.cummax()
    active = None
    armed = False
    lows = highs = 0
    cooldown = start
    rows = []
    last_valid = None

    def finish(reason: str, recovery_at=None, available_at=None) -> None:
        nonlocal active, cooldown
        assert active is not None
        followup = last_valid if last_valid is not None else active["prediction_time"]
        active.update(recovery_time=recovery_at, recovery_available_at=available_at,
                      followup_end=followup, termination_reason=reason,
                      episode_separated_at=recovery_at)
        for horizon in HORIZONS:
            deadline = active["prediction_time"] + pd.Timedelta(minutes=horizon)
            if recovery_at is not None and recovery_at <= deadline:
                label, why = 1, "confirmed_recovery"
            elif followup >= deadline:
                label, why = 0, "observed_without_recovery"
            else:
                label, why = pd.NA, reason
            active[f"label_{horizon}m"] = label
            active[f"reason_{horizon}m"] = why
        rows.append(active)
        cooldown = max(active["prediction_time"] + pd.Timedelta(minutes=60), followup)
        active = None

    for stamp, row in source.iterrows():
        usable = (pd.notna(row.get("usable")) and bool(row.usable)
                  and pd.notna(row.speed_kmh) and pd.notna(row.available_at))
        if not usable:
            if active is not None:
                finish("missing_or_invalid_bin")
            armed = False
            lows = highs = 0
            continue
        arrival = row.available_at
        ratio = float(row.speed_kmh) / baseline
        last_valid = stamp
        highs = highs + 1 if ratio >= rules.recovery else 0
        lows = lows + 1 if ratio <= rules.congestion else 0
        if active is not None:
            if highs >= rules.recovery_bins:
                finish("recovered", stamp, arrival)
                armed = True
                lows = 0
            continue
        if highs >= rules.recovery_bins:
            armed = True
            if rows and rows[-1]["episode_separated_at"] is None:
                # A censored episode stays unknown, but later witnessed recovery
                # establishes a safe episode boundary for temporal splitting.
                rows[-1]["episode_separated_at"] = stamp
        if armed and lows >= rules.onset_bins and arrival <= cooldown:
            # An onset during embargo is suppressed as an entire episode, not
            # relabelled as a fresh onset when the clock expires mid-congestion.
            armed = False
        if armed and lows == rules.onset_bins and cooldown < arrival < end:
            if arrival - stamp >= pd.Timedelta(minutes=rules.step_minutes * rules.recovery_bins):
                raise ValueError("Onset availability lag must be shorter than recovery persistence")
            token = f"{identity}|{stamp.isoformat()}|{rules}"
            active = dict(zip(UNIT, identity)) | {
                "event_id": hashlib.sha256(token.encode()).hexdigest()[:20],
                "onset_time": stamp - pd.Timedelta(minutes=rules.step_minutes * (rules.onset_bins - 1)),
                "onset_confirmed_at": stamp, "prediction_time": arrival,
                "feature_max_available_at": arrival,
                "speed_kmh": float(row.speed_kmh), "speed_ratio": ratio,
                "baseline_kmh": baseline, "valid_slots": int(row.valid_slots),
                "onset_observed_minutes": rules.step_minutes * rules.onset_bins,
                "congestion_ratio": rules.congestion, "recovery_ratio": rules.recovery,
                "onset_bins": rules.onset_bins, "recovery_bins": rules.recovery_bins,
                "definition_version": "lane-observed-confirmation-v1"}
            armed = False
    if active is not None:
        finish("period_end")
    result = pd.DataFrame(rows)
    if len(result):
        for horizon in HORIZONS:
            result[f"label_{horizon}m"] = result[f"label_{horizon}m"].astype("Int8")
        for col in ["recovery_time", "recovery_available_at", "followup_end", "episode_separated_at"]:
            result[col] = pd.to_datetime(result[col], utc=True).dt.tz_convert(start.tz)
    return result


def assign_splits(events: pd.DataFrame, validation_start: pd.Timestamp,
                  test_start: pd.Timestamp, test_end: pd.Timestamp) -> pd.Series:
    """Chronological event assignment; purge 60m windows AND entire event ends.

    Censored events require a later witnessed recovery/rearming before a fold
    boundary. This preserves censored examples without selecting only recoveries.
    """
    splits = pd.Series("purged", index=events.index, dtype="string")
    label_end = events.prediction_time + pd.Timedelta(minutes=60)
    separation_end = pd.concat([label_end, events.episode_separated_at], axis=1).max(axis=1)
    # A censored label is not silently turned positive by later rearming.
    complete = events.episode_separated_at.notna()
    splits.loc[complete & (separation_end < validation_start)] = "train"
    splits.loc[complete & (events.onset_time >= validation_start + pd.Timedelta(minutes=60)) & (separation_end < test_start)] = "validation"
    splits.loc[(events.onset_time >= test_start + pd.Timedelta(minutes=60)) & (label_end < test_end)] = "test"
    return splits
