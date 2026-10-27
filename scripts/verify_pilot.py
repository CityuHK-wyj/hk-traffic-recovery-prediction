"""Offline integrity/invariant checks on the ACTUAL pilot artifacts (not pytest fixtures)."""
import argparse
import json
from pathlib import Path

import pandas as pd

from traffic_recovery.data.events import HORIZONS, UNIT, fit_reference
from traffic_recovery.data.http import sha256_file


def verify(root: Path, reports: Path) -> dict:
    """Raise AssertionError on corrupted provenance, unavailable features or bad labels."""
    manifest = json.loads((reports / "manifest.json").read_text(encoding="utf-8"))
    for name, evidence in manifest["outputs"].items():
        assert sha256_file(root / name) == evidence["sha256"], name
    for evidence in manifest["sources"]:
        assert sha256_file(Path(evidence["source"])) == evidence["source_sha256"]
    events = pd.read_parquet(root / "events.parquet")
    bins = pd.read_parquet(root / "cohort_bins.parquet")
    assert len(events) and not events.event_id.duplicated().any()
    assert (events.feature_max_available_at <= events.prediction_time).all()
    assert (events.reference_fit_end <= events.prediction_time).all()
    assert (events.onset_confirmed_at <= events.prediction_time).all()
    assert (bins.last_source_available_at <= bins.available_at).all()
    assert bins.available_at.sub(bins.timestamp).eq(pd.Timedelta(minutes=10)).all()
    config = manifest["config"]
    reference = fit_reference(bins, fit_start=pd.Timestamp(config["observation_start"]),
        fit_end=pd.Timestamp(config["reference_end"]), min_bins=config["min_reference_bins"])
    compared = events.merge(reference[UNIT + ["baseline_kmh"]], on=UNIT, suffixes=("", "_ref"))
    assert len(compared) == len(events)
    assert compared.baseline_kmh.sub(compared.baseline_kmh_ref).abs().lt(1e-9).all()
    for _, group in events.groupby(UNIT):
        assert group.sort_values("prediction_time").prediction_time.diff().dropna().gt(pd.Timedelta(minutes=60)).all()
    for _, event in events.iterrows():
        unit = bins
        for key in UNIT:
            unit = unit.loc[unit[key] == event[key]]
        onset = unit.loc[(unit.timestamp >= event.onset_time) & (unit.timestamp <= event.onset_confirmed_at)]
        assert len(onset) == event.onset_bins
        assert onset.usable.all() and onset.speed_kmh.le(event.baseline_kmh * event.congestion_ratio).all()
        assert (onset.available_at <= event.prediction_time).all()
        observed = unit.loc[(unit.timestamp >= event.onset_confirmed_at) & (unit.timestamp <= event.followup_end)]
        assert observed.usable.all()
        assert len(observed) == int((event.followup_end - event.onset_confirmed_at).total_seconds() / 300) + 1
        if pd.notna(event.recovery_time):
            assert event.prediction_time < event.recovery_time <= event.recovery_available_at
            sustained = unit.loc[(unit.timestamp <= event.recovery_time)
                & (unit.timestamp > event.recovery_time - pd.Timedelta(minutes=5 * event.recovery_bins))]
            assert len(sustained) == event.recovery_bins
            assert sustained.usable.all() and sustained.speed_kmh.ge(event.baseline_kmh * event.recovery_ratio).all()
        labels = []
        for h in HORIZONS:
            label = event[f"label_{h}m"]
            deadline = event.prediction_time + pd.Timedelta(minutes=h)
            if pd.notna(label):
                labels.append(int(label))
                if label == 1:
                    assert pd.notna(event.recovery_time) and event.recovery_time <= deadline
                else:
                    assert event.followup_end >= deadline
                    assert pd.isna(event.recovery_time) or event.recovery_time > deadline
        assert labels == sorted(labels)
    spatial = json.loads((reports / "spatial" / "spatial_quality.json").read_text(encoding="utf-8"))
    matches = pd.read_csv(reports / "spatial" / "matched_detectors.csv")
    chosen = matches.loc[matches.route_id.notna()]
    assert len(chosen) == spatial["candidate_matches"]
    assert chosen.distance_m.le(spatial["radius_m"]).all()
    assert chosen.direction_difference_deg.le(spatial["bearing_tolerance_degrees"]).all()
    assert spatial["certified_matches"] == 0
    result = {"status": "passed", "real_event_rows": len(events), "cohort_bin_rows": len(bins),
        "source_zip_hashes_verified": len(manifest["sources"]),
        "checks": ["output/source hashes", "unique events", "feature availability", "historical-only reference recomputation",
                   "nonoverlapping within-unit 60m windows", "witnessed onset", "uninterrupted follow-up",
                   "sustained recovery", "horizon labels/censoring/monotonicity", "candidate match distances/directions"]}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/local/pilot/derived"))
    parser.add_argument("--reports", type=Path, default=Path("reports/milestone2"))
    args = parser.parse_args()
    result = verify(args.data, args.reports)
    (args.reports / "integrity_checks.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
