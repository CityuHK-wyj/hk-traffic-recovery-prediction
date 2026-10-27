"""Fail-closed event-time neighbor features from human-reviewed directed topology.

Candidate matches/topology are deliberately NOT accepted as scientific evidence.
All identifiers are strings, timestamps timezone-aware and speeds in km/h.
"""
import pandas as pd


def _approved(frame: pd.DataFrame, when: pd.Timestamp, *, version: str) -> pd.DataFrame:
    """Return only independently reviewed, version-compatible, time-valid rows."""
    required = {"review_status", "reviewer", "valid_from", "valid_to", "network_version"}
    if not required <= set(frame.columns):
        raise ValueError(f"Missing review fields: {sorted(required - set(frame.columns))}")
    start = pd.to_datetime(frame.valid_from, utc=True, errors="raise")
    end = pd.to_datetime(frame.valid_to, utc=True, errors="raise")
    reviewed = frame.review_status.eq("human_verified")
    if ((start.isna() | end.isna() | (start >= end)) & reviewed).any():
        raise ValueError("Reviewed rows need an explicit nonempty validity interval")
    mask = (frame.review_status.eq("human_verified") & frame.reviewer.notna()
            & frame.reviewer.astype(str).str.strip().ne("") & frame.network_version.eq(version)
            & start.le(when) & end.gt(when))
    return frame.loc[mask]


def neighbor_features(events: pd.DataFrame, mappings: pd.DataFrame, transitions: pd.DataFrame,
                      bins: pd.DataFrame, references: pd.DataFrame, *, network_version: str,
                      reference_cutoff: pd.Timestamp,
                      max_age: pd.Timedelta = pd.Timedelta(minutes=10)) -> pd.DataFrame:
    """One local/spatial row per event; never infer adjacency from point proximity.

    Mapping requires human_verified, reviewer, version, [valid_from,valid_to),
    detector_id/direction/lane_id and directed arc_id. Transitions require the
    same review fields plus from_arc/to_arc and represent verified legal turns.
    Neighbor bins must be usable, same mapped detector/direction/lane, latest
    timestamp and available_at <= prediction, and no older than max_age.
    Neighbor congestion ratios require a fit reference available by the explicitly
    supplied training-only cutoff and prediction.
    Unknown neighbors yield NA speeds and NA coverage when denominator is zero.
    Returns explicit counts, coverage and provenance watermarks. Raises on
    missing columns, ambiguous reviewed mappings or invalid/naive timestamps.
    """
    if max_age <= pd.Timedelta(0) or reference_cutoff.tzinfo is None:
        raise ValueError("max_age must be positive and reference_cutoff aware")
    for frame, cols in [(events, ["event_id", "detector_id", "direction", "lane_id", "prediction_time"]),
                        (mappings, ["detector_id", "direction", "lane_id", "arc_id"]),
                        (transitions, ["from_arc", "to_arc"]),
                        (bins, ["detector_id", "direction", "lane_id", "timestamp", "available_at", "usable", "speed_kmh"]),
                        (references, ["detector_id", "direction", "lane_id", "baseline_kmh", "reference_fit_end"])]:
        if not set(cols) <= set(frame.columns):
            raise ValueError(f"Missing columns: {sorted(set(cols) - set(frame.columns))}")
    for frame, cols in [(events, ["prediction_time"]), (bins, ["timestamp", "available_at"]),
                        (references, ["reference_fit_end"])]:
        for column in cols:
            if not isinstance(frame[column].dtype, pd.DatetimeTZDtype) or frame[column].isna().any():
                raise ValueError(f"{column} must contain aware timestamps")
    if (bins.available_at < bins.timestamp).any():
        raise ValueError("Observation availability precedes its timestamp")
    if references.duplicated(["detector_id", "direction", "lane_id"]).any():
        raise ValueError("Ambiguous neighbor reference")
    rows = []
    for event in events.itertuples(index=False):
        when = event.prediction_time
        if when < reference_cutoff:
            raise ValueError("Prediction precedes frozen training reference cutoff")
        mapping = _approved(mappings, when, version=network_version)
        graph = _approved(transitions, when, version=network_version)
        keys = ["detector_id", "direction", "lane_id"]
        if mapping.duplicated(keys).any():
            raise ValueError("Ambiguous verified detector/lane mapping")
        local = mapping.loc[(mapping.detector_id == event.detector_id) &
                            (mapping.direction == event.direction) & (mapping.lane_id == event.lane_id)]
        row = {"event_id": event.event_id, "prediction_time": when,
               "network_version": network_version, "feature_status": "mapping_unverified"}
        for relation in ["upstream", "downstream"]:
            row.update({f"{relation}_mean_speed_kmh": pd.NA, f"{relation}_congestion_fraction": pd.NA,
                        f"{relation}_observed_detectors": 0, f"{relation}_eligible_detectors": 0,
                        f"{relation}_reference_detectors": 0, f"{relation}_coverage": pd.NA,
                        f"{relation}_road_degree": pd.NA, f"{relation}_max_available_at": pd.NaT})
        if local.empty:
            rows.append(row)
            continue
        arc = local.iloc[0].arc_id
        row["feature_status"] = "verified_mapping_no_verified_neighbors"
        for relation, local_col, remote_col in [("upstream", "to_arc", "from_arc"),
                                               ("downstream", "from_arc", "to_arc")]:
            links = graph.loc[graph[local_col].eq(arc)]
            neighbor_arcs = set(links[remote_col])
            row[f"{relation}_road_degree"] = len(neighbor_arcs)
            candidates = mapping.loc[mapping.arc_id.isin(neighbor_arcs) & mapping.detector_id.ne(event.detector_id)]
            # A detector with multiple approved lanes contributes once, never as multiple independent detectors.
            if candidates.detector_id.duplicated().any():
                raise ValueError("Multiple reviewed lanes for a neighboring detector")
            row[f"{relation}_eligible_detectors"] = len(candidates)
            if len(candidates):
                row["feature_status"] = "verified_neighbors"
                eligible_bins = bins.loc[(bins.timestamp <= when) & (bins.available_at <= when)
                    & (bins.timestamp >= when - max_age) & bins.usable & bins.speed_kmh.notna()].copy()
                eligible_bins = eligible_bins.merge(candidates[keys], on=keys, how="inner", validate="many_to_one")
                eligible_bins = eligible_bins.sort_values(["timestamp", "available_at"]).drop_duplicates("detector_id", keep="last")
                count = len(eligible_bins)
                row[f"{relation}_observed_detectors"] = count
                row[f"{relation}_coverage"] = count / len(candidates)
                if count:
                    row[f"{relation}_mean_speed_kmh"] = float(eligible_bins.speed_kmh.mean())
                    row[f"{relation}_max_available_at"] = eligible_bins.available_at.max()
                    ref = eligible_bins.merge(references, on=keys, how="left", validate="one_to_one")
                    ref = ref.loc[(ref.reference_fit_end <= reference_cutoff) & (ref.reference_fit_end <= when)
                                  & ref.baseline_kmh.notna() & ref.baseline_kmh.gt(0)]
                    row[f"{relation}_reference_detectors"] = len(ref)
                    if len(ref):
                        row[f"{relation}_congestion_fraction"] = float((ref.speed_kmh / ref.baseline_kmh <= 0.5).mean())
        rows.append(row)
    return pd.DataFrame(rows)
