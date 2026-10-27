"""Offline structural checks of generated real subset, NOT manual validation."""
import ast
import json
from pathlib import Path

import pandas as pd
from shapely import wkb
from shapely.geometry import Point

from traffic_recovery.data.http import sha256_file
from traffic_recovery.network.pilot import local_bearing, angular_difference, COMPASS


def verify(report: Path, data: Path) -> dict:
    """Recheck source-derived arc geometry, endpoints, direction, restrictions.

    Raises AssertionError on failed invariants. Passing is not proof that a source
    intersection is navigable or that a detector-road candidate is correct.
    """
    quality = json.loads((report / "quality.json").read_text(encoding="utf-8"))
    for path, digest in quality["derived_sha256"].items():
        assert sha256_file(Path(path)) == digest
    roads = pd.read_parquet(data / "source_roads.parquet")
    arcs = pd.read_parquet(data / "directed_arcs.parquet")
    transitions = pd.read_csv(data / "directed_transitions.csv", dtype=str).fillna("")
    turns = pd.read_csv(report / "source_turns.csv", dtype=str).fillna("")
    intersections = pd.read_csv(report / "source_intersections.csv", dtype=str).fillna("")
    mapping = pd.read_csv(report / "detector_mapping.csv", dtype=str).fillna("")
    sources = {row.ROUTE_ID: row for row in roads.itertuples(index=False)}
    arc_lookup = {}
    for arc in arcs.itertuples(index=False):
        road = sources[arc.route_id]
        geom = wkb.loads(road.geometry_wkb)
        start, end = geom.coords[0], geom.coords[-1]
        if arc.orientation == "reverse":
            assert road.TRAVEL_DIRECTION == "1"
            start, end = end, start
        else:
            assert road.TRAVEL_DIRECTION in {"1", "3"} and arc.orientation == "forward"
        assert ast.literal_eval(arc.from_node) == (round(start[0], 2), round(start[1], 2), road.ELEVATION)
        assert ast.literal_eval(arc.to_node) == (round(end[0], 2), round(end[1], 2), road.ELEVATION)
        assert abs(geom.length - arc.length_m) < 1e-7
        arc_lookup[arc.arc_id] = arc
    restrictions = set()
    for row in turns.to_dict("records"):
        if float(row["NO_TURN"] or "0") < 0:
            sequence = [row[f"EDGE{i}FID"] for i in range(1, 9) if row.get(f"EDGE{i}FID")]
            restrictions.update(zip(sequence, sequence[1:]))
    intersection_lookup = {row["INT_ID"]: row for row in intersections.to_dict("records")}
    for transition in transitions.itertuples(index=False):
        a, b = arc_lookup[transition.from_arc], arc_lookup[transition.to_arc]
        assert a.to_node == b.from_node  # includes source elevation; excludes interior crossings
        if transition.automatic_status != "rejected_restriction_or_uturn":
            assert (a.route_id, b.route_id) not in restrictions and a.route_id != b.route_id
        if transition.automatic_status == "source_supported_review_pending":
            assert transition.intersection_ids
            x, y, _ = ast.literal_eval(a.to_node)
            for identifier in transition.intersection_ids.split("|"):
                intersection = intersection_lookup[identifier]
                members = {intersection.get(f"RD_ID_{i}", "") for i in range(1, 11)}
                assert {a.route_id, b.route_id} <= members
                assert Point(x, y).distance(Point(float(intersection["easting"]), float(intersection["northing"]))) <= 1
    for row in mapping.itertuples(index=False):
        if not row.arc_id:
            continue
        road = sources[row.route_id]
        line = wkb.loads(road.geometry_wkb)
        point = Point(float(row.easting), float(row.northing))
        assert abs(point.distance(line) - float(row.distance_m)) < 1e-7
        bearing = local_bearing(line, point)
        if row.orientation == "reverse":
            assert road.TRAVEL_DIRECTION == "1"
            bearing = (bearing + 180) % 360
        assert abs(angular_difference(COMPASS[row.direction], bearing) - float(row.direction_difference_deg)) < 1e-7
        assert float(row.distance_m) <= 50 and float(row.direction_difference_deg) <= 45
    features = pd.read_parquet(data / "spatial_features.parquet")
    assert features.feature_status.eq("mapping_unverified").all()
    assert features[["upstream_mean_speed_kmh", "downstream_mean_speed_kmh"]].isna().all().all()
    return {"status": "passed", "source_roads": len(roads), "directed_arcs": len(arcs),
            "candidate_transitions": len(transitions), "detector_candidates": len(mapping),
            "event_rows": len(features), "verified_human_matches": 0, "verified_human_connections": 0,
            "warning": "Automated geometry/source-field invariants only; not independent validation of real-world navigability or mapping accuracy."}


def main() -> None:
    report, data = Path("reports/spatial_feasibility"), Path("data/local/spatial-feasibility")
    result = verify(report, data)
    (report / "automated_checks.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
