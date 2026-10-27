"""SYNTHETIC topology and traffic; never research observations or validation."""
import pandas as pd
import pytest

from traffic_recovery.network.spatial_features import neighbor_features

NOW = pd.Timestamp("2026-01-01 10:00", tz="Asia/Hong_Kong")
VERSION = "SYNTHETIC_NETWORK"


def fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    events = pd.DataFrame([{"event_id": "E", "detector_id": "LOCAL", "direction": "East", "lane_id": "L", "prediction_time": NOW}])
    review = {"review_status": "human_verified", "reviewer": "synthetic-reviewer", "valid_from": NOW - pd.Timedelta(days=1),
              "valid_to": NOW + pd.Timedelta(days=1), "network_version": VERSION}
    mappings = pd.DataFrame([review | {"detector_id": d, "direction": "East", "lane_id": "L", "arc_id": a}
                             for d, a in [("LOCAL", "A:F"), ("UP", "B:F"), ("DOWN", "C:F")]])
    transitions = pd.DataFrame([review | {"from_arc": a, "to_arc": b} for a, b in [("B:F", "A:F"), ("A:F", "C:F")]])
    bins = pd.DataFrame([{"detector_id": d, "direction": direction, "lane_id": "L", "timestamp": t,
                         "available_at": availability, "usable": True, "speed_kmh": speed}
        for d, direction, t, availability, speed in [
            ("UP", "East", NOW - pd.Timedelta(minutes=10), NOW, 20.),
            ("UP", "East", NOW - pd.Timedelta(minutes=5), NOW + pd.Timedelta(minutes=5), 100.),
            ("UP", "West", NOW - pd.Timedelta(minutes=10), NOW, 999.),
            ("DOWN", "East", NOW - pd.Timedelta(minutes=15), NOW - pd.Timedelta(minutes=5), 50.)]])
    refs = pd.DataFrame([{"detector_id": d, "direction": "East", "lane_id": "L", "baseline_kmh": 60.,
                         "reference_fit_end": NOW - pd.Timedelta(days=1)} for d in ["UP", "DOWN"]])
    return events, mappings, transitions, bins, refs


def test_verified_neighbor_features_asof_and_missing() -> None:
    events, mappings, links, bins, refs = fixture()
    row = neighbor_features(events, mappings, links, bins, refs, network_version=VERSION, reference_cutoff=NOW).iloc[0]
    assert row.upstream_mean_speed_kmh == 20
    assert row.upstream_congestion_fraction == 1
    assert row.upstream_coverage == 1 and row.upstream_observed_detectors == 1
    assert row.upstream_max_available_at == NOW
    assert row.downstream_coverage == 0 and row.downstream_observed_detectors == 0
    assert pd.isna(row.downstream_mean_speed_kmh) and pd.isna(row.downstream_congestion_fraction)
    assert row.upstream_road_degree == 1 and row.downstream_road_degree == 1


def test_unreviewed_or_invalid_version_never_used() -> None:
    events, mapping, links, bins, refs = fixture()
    mapping.loc[:, "review_status"] = "pending"
    mapping["valid_from"] = pd.NaT
    mapping["valid_to"] = pd.NaT
    row = neighbor_features(events, mapping, links, bins, refs, network_version=VERSION, reference_cutoff=NOW).iloc[0]
    assert row.feature_status == "mapping_unverified" and pd.isna(row.upstream_mean_speed_kmh)
    events, mapping, links, bins, refs = fixture()
    links.network_version = "OTHER"
    row = neighbor_features(events, mapping, links, bins, refs, network_version=VERSION, reference_cutoff=NOW).iloc[0]
    assert row.feature_status == "verified_mapping_no_verified_neighbors"
    assert pd.isna(row.upstream_coverage)


def test_future_reference_and_naive_or_unavailable_data_fail_safely() -> None:
    events, mapping, links, bins, refs = fixture()
    refs.loc[refs.detector_id.eq("UP"), "reference_fit_end"] = NOW + pd.Timedelta(hours=1)
    row = neighbor_features(events, mapping, links, bins, refs, network_version=VERSION, reference_cutoff=NOW).iloc[0]
    assert row.upstream_mean_speed_kmh == 20 and pd.isna(row.upstream_congestion_fraction)
    refs.loc[refs.detector_id.eq("UP"), "reference_fit_end"] = NOW - pd.Timedelta(hours=1)
    row = neighbor_features(events, mapping, links, bins, refs, network_version=VERSION,
                            reference_cutoff=NOW - pd.Timedelta(days=1)).iloc[0]
    assert pd.isna(row.upstream_congestion_fraction)  # post-training fit, even if before prediction
    bins["available_at"] = bins.available_at.dt.tz_localize(None)
    with pytest.raises(ValueError, match="aware"):
        neighbor_features(events, mapping, links, bins, refs, network_version=VERSION, reference_cutoff=NOW)


def test_reviewed_ambiguity_and_unknown_validity_are_rejected() -> None:
    events, mapping, links, bins, refs = fixture()
    with pytest.raises(ValueError, match="Ambiguous"):
        neighbor_features(events, pd.concat([mapping, mapping.iloc[:1]]), links, bins, refs, network_version=VERSION, reference_cutoff=NOW)
    mapping.loc[0, "valid_to"] = pd.NaT
    with pytest.raises(ValueError, match="validity interval"):
        neighbor_features(events, mapping, links, bins, refs, network_version=VERSION, reference_cutoff=NOW)
