"""Auditable direction-aware matching and conservative source-endpoint graph.

No detector proximity is treated as an upstream/downstream relationship. Graph
transitions are geometric topology candidates, not validated traffic adjacency.
"""
import argparse
from collections import defaultdict
import json
import math
import logging
from pathlib import Path
from typing import Iterator
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from traffic_recovery.data.http import EvidenceClient, sha256_file
from traffic_recovery.data.sources import NETWORK_STATIC

COMPASS = {"North": 0, "North East": 45, "East": 90, "South East": 135,
           "South": 180, "South West": 225, "West": 270, "North West": 315}


def read_features(path: Path) -> Iterator[tuple[dict[str, str], ET.Element]]:
    """Stream actual CityGML objects; yielded XML is cleared after iteration."""
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag.endswith("}GenericCityObject"):
            attrs = {child.get("name"): child.findtext("{*}value", "")
                     for child in element if child.get("name")}
            yield attrs, element
            element.clear()
        elif element.tag.endswith("}cityObjectMember"):
            element.clear()


def read_roads(path: Path) -> tuple[list[dict], list[LineString]]:
    """Read EPSG:2326 source polylines without spatially simplifying endpoints."""
    attributes, geometries = [], []
    for attrs, element in read_features(path):
        lines = element.findall(".//{*}LineString")
        if len(lines) != 1 or lines[0].get("srsName") != "EPSG:2326":
            raise ValueError("Expected one EPSG:2326 LineString per route")
        values = [float(v) for v in lines[0].findtext("{*}posList", "").split()]
        if len(values) < 4 or len(values) % 2:
            raise ValueError("Malformed source geometry")
        geometries.append(LineString(zip(values[::2], values[1::2])))
        attributes.append(attrs)
    if not attributes or len({a["ROUTE_ID"] for a in attributes}) != len(attributes):
        raise ValueError("Empty/duplicate road IDs")
    return attributes, geometries


def angular_difference(a: float, b: float) -> float:
    """Smallest absolute bearing difference in degrees, in [0,180]."""
    return abs((a - b + 180) % 360 - 180)


def local_bearing(line: LineString, point: Point) -> float:
    """Digitised tangent bearing over +/-10 m around nearest projected point."""
    position = line.project(point)
    before = line.interpolate(max(0, position - 10))
    after = line.interpolate(min(line.length, position + 10))
    return math.degrees(math.atan2(after.x - before.x, after.y - before.y)) % 360


def match_candidates(point: Point, direction: str, attrs: list[dict],
                     lines: list[LineString], tree: STRtree,
                     radius_m: float = 50, tolerance_deg: float = 45) -> list[dict]:
    """All source routes within radius, with directional checks (not validation)."""
    if direction not in COMPASS:
        raise ValueError(f"Unknown observed travel direction: {direction}")
    candidates = []
    for index in tree.query(point, predicate="dwithin", distance=radius_m):
        line, attr = lines[index], attrs[index]
        bearing = local_bearing(line, point)
        choices = [(angular_difference(COMPASS[direction], bearing), "forward")]
        if attr["TRAVEL_DIRECTION"] == "1":
            choices.append((angular_difference(COMPASS[direction], (bearing + 180) % 360), "reverse"))
        elif attr["TRAVEL_DIRECTION"] != "3":
            raise ValueError("Unknown permitted-travel code")
        difference, orientation = min(choices)
        candidates.append({"route_id": attr["ROUTE_ID"], "road_name": attr.get("STREET_ENAME", ""),
            "distance_m": point.distance(line), "direction_difference_deg": difference,
            "direction_compatible": difference <= tolerance_deg, "orientation": orientation,
            "digitised_bearing_deg": bearing, "travel_direction": attr["TRAVEL_DIRECTION"],
            "elevation": attr["ELEVATION"]})
    return sorted(candidates, key=lambda r: (r["distance_m"], r["route_id"]))


def endpoint_key(coordinate: tuple, elevation: str) -> tuple:
    """Centimetre endpoint identity plus source elevation, not nearest-road links."""
    return (round(coordinate[0], 2), round(coordinate[1], 2), elevation)


def directed_arcs(attrs: list[dict], lines: list[LineString]) -> list[dict]:
    """One/two directed arcs per route respecting actual digitised direction."""
    arcs = []
    for attr, line in zip(attrs, lines):
        route = attr["ROUTE_ID"]
        start, end = endpoint_key(line.coords[0], attr["ELEVATION"]), endpoint_key(line.coords[-1], attr["ELEVATION"])
        arcs.append({"arc_id": route + ":F", "route_id": route, "orientation": "forward",
                     "from_node": start, "to_node": end, "length_m": line.length})
        if attr["TRAVEL_DIRECTION"] == "1":
            arcs.append({"arc_id": route + ":R", "route_id": route, "orientation": "reverse",
                         "from_node": end, "to_node": start, "length_m": line.length})
        elif attr["TRAVEL_DIRECTION"] != "3":
            raise ValueError("Unknown travel direction")
    return arcs


def graph_transitions(arcs: list[dict], turns: list[dict]) -> tuple[list[dict], list[dict]]:
    """Candidate endpoint transitions; conservatively block restricted route pairs.

    Multi-edge, conditional and fractional-position restrictions cannot be fully
    represented by this simple edge graph. Block each consecutive restricted pair
    (regardless of time, vehicle and orientation) rather than pretending they are
    resolved. This deliberately over-restricts and is NOT a routing engine.
    """
    blocked = defaultdict(list)
    for turn in turns:
        if float(turn.get("NO_TURN") or "0") >= 0:
            continue
        sequence = [turn[f"EDGE{i}FID"] for i in range(1, 9) if turn.get(f"EDGE{i}FID")]
        for a, b in zip(sequence, sequence[1:]):
            blocked[(a, b)].append(turn["TURN_ID"])
    outgoing = defaultdict(list)
    for arc in arcs:
        outgoing[arc["from_node"]].append(arc)
    allowed, excluded = [], []
    for arc in arcs:
        for following in outgoing[arc["to_node"]]:
            row = {"from_arc": arc["arc_id"], "to_arc": following["arc_id"],
                   "from_route": arc["route_id"], "to_route": following["route_id"],
                   "node": str(arc["to_node"]), "evidence": "source_endpoint_1cm_same_elevation"}
            restrictions = blocked[(arc["route_id"], following["route_id"])]
            if restrictions or arc["route_id"] == following["route_id"]:
                excluded.append(row | {"reason": "turn_constraint_conservative" if restrictions else "uturn_not_validated",
                                       "turn_ids": "|".join(restrictions)})
            else:
                allowed.append(row)
    return allowed, excluded


def run_pilot(cohort: Path, roads: Path, metadata: Path, network_http: Path,
              output: Path, limit: int = 12) -> dict:
    """Match first N sorted cohort units, export all candidates and review maps."""
    output.mkdir(parents=True, exist_ok=True)
    selected = pd.read_csv(cohort, dtype=str).sort_values(["detector_id", "direction"]).head(limit)
    detectors = pd.read_csv(metadata, dtype={"AID_ID_Number": str}, encoding="utf-8-sig")
    selected = selected.merge(detectors, left_on="detector_id", right_on="AID_ID_Number", how="left", validate="many_to_one")
    if selected[["Easting", "Northing"]].isna().any().any():
        raise ValueError("Cohort has missing detector coordinates")
    attrs, lines = read_roads(roads)
    tree = STRtree(lines)
    rows, candidate_rows, local = [], [], set()
    for _, detector in selected.iterrows():
        point = Point(detector.Easting, detector.Northing)
        candidates = match_candidates(point, detector.direction, attrs, lines, tree)
        base = {"detector_id": detector.detector_id, "direction": detector.direction,
                "lane_id": detector.lane_id, "metadata_direction": detector.Direction,
                "metadata_direction_agrees": detector.direction == detector.Direction,
                "detector_road_name": detector.Road_EN, "easting": point.x, "northing": point.y}
        candidate_rows.extend(base | c for c in candidates)
        compatible = [c for c in candidates if c["direction_compatible"]]
        if compatible:
            chosen = compatible[0]
            ambiguous = sum(c["distance_m"] <= chosen["distance_m"] + 10 for c in compatible) > 1
            status = "ambiguous_parallel_or_junction" if ambiguous else "provisional_manual_review_pending"
            if not base["metadata_direction_agrees"]:
                status = "direction_metadata_mismatch"
            rows.append(base | chosen | {"status": status, "ambiguous": ambiguous,
                        "candidate_count": len(candidates), "compatible_count": len(compatible)})
        else:
            rows.append(base | {"status": "unmatched_no_direction_compatible_route" if candidates else "unmatched_distance",
                                "ambiguous": False, "candidate_count": len(candidates), "compatible_count": 0})
        local.update(int(i) for i in tree.query(point, predicate="dwithin", distance=500))
    matches = pd.DataFrame(rows)
    matches.to_csv(output / "matched_detectors.csv", index=False)
    pd.DataFrame(candidate_rows).to_csv(output / "match_candidates.csv", index=False)
    local_indices = sorted(local)
    local_attrs = [attrs[i] for i in local_indices]
    local_lines = [lines[i] for i in local_indices]
    pd.DataFrame([a | {"geometry_wkb": g.wkb} for a, g in zip(local_attrs, local_lines)]).to_parquet(output / "roads.parquet", index=False)
    arcs = directed_arcs(local_attrs, local_lines)
    turns = [a for a, _ in read_features(network_http / "TURN.gml")]
    transitions, excluded = graph_transitions(arcs, turns)
    pd.DataFrame([{**a, "from_node": str(a["from_node"]), "to_node": str(a["to_node"])} for a in arcs]).to_parquet(output / "directed_arcs.parquet", index=False)
    local_ids = {a["ROUTE_ID"] for a in local_attrs}
    local_turns = [t for t in turns if any(t.get(f"EDGE{i}FID") in local_ids for i in range(1, 9))]
    pd.DataFrame(local_turns).to_csv(output / "local_turn_constraints.csv", index=False)
    # Inspect explicit intersection road membership as additional audit evidence.
    intersections = []
    intersection_pairs = defaultdict(list)
    for attr, element in read_features(network_http / "INTERSECTION.gml"):
        ids = {attr.get(f"RD_ID_{i}") for i in range(1, 11)} - {None, ""}
        if not ids & local_ids:
            continue
        point = element.find(".//{*}Point")
        if point is None or point.get("srsName") != "EPSG:2326":
            raise ValueError("Unexpected intersection geometry")
        east, north = map(float, point.findtext("{*}pos", "").split())
        intersections.append(attr | {"easting": east, "northing": north})
        for a in ids & local_ids:
            for b in ids & local_ids:
                if a != b:
                    intersection_pairs[(a, b)].append((attr["INT_ID"], east, north))
    arcs_by_id = {arc["arc_id"]: arc for arc in arcs}
    for transition in transitions + excluded:
        x, y, _ = arcs_by_id[transition["from_arc"]]["to_node"]
        transition["intersection_ids"] = "|".join(identifier for identifier, east, north in
            intersection_pairs[(transition["from_route"], transition["to_route"])]
            if math.hypot(x - east, y - north) <= 1)
    pd.DataFrame(transitions).to_csv(output / "candidate_transitions.csv", index=False)
    pd.DataFrame(excluded).to_csv(output / "excluded_transitions.csv", index=False)
    pd.DataFrame(intersections).to_csv(output / "local_intersections.csv", index=False)
    fig, axes = plt.subplots(math.ceil(len(rows) / 3), 3, figsize=(15, 4.5 * math.ceil(len(rows) / 3)), squeeze=False)
    route_index = {a["ROUTE_ID"]: i for i, a in enumerate(attrs)}
    for ax, row in zip(axes.flat, rows):
        point = Point(row["easting"], row["northing"])
        for index in tree.query(point, predicate="dwithin", distance=150):
            x, y = lines[index].xy
            ax.plot(x, y, color="0.75", linewidth=1)
        if row.get("route_id"):
            line = lines[route_index[row["route_id"]]]
            x, y = line.xy
            ax.plot(x, y, color="tab:blue", linewidth=2)
            position = line.project(point)
            a, b = line.interpolate(max(0, position - 15)), line.interpolate(min(line.length, position + 15))
            if row["orientation"] == "reverse":
                a, b = b, a
            ax.annotate("", (b.x, b.y), (a.x, a.y), arrowprops={"arrowstyle": "->", "color": "blue"})
        angle = math.radians(COMPASS[row["direction"]])
        ax.arrow(point.x, point.y, 30 * math.sin(angle), 30 * math.cos(angle), width=1, color="red", length_includes_head=True)
        ax.scatter(point.x, point.y, c="red", s=20)
        ax.set(xlim=(point.x - 120, point.x + 120), ylim=(point.y - 120, point.y + 120),
               title=f"{row['detector_id']} {row['direction']}\n{row.get('route_id', 'unmatched')}: {row['status']}")
        ax.set_aspect("equal")
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.tick_params(labelsize=7)
    for ax in list(axes.flat)[len(rows):]:
        ax.set_visible(False)
    fig.suptitle("Manual review — EPSG:2326 metres; red: observed direction; blue: candidate road travel\nNo match is certified; no proximity-based upstream/downstream inference", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output / "detector_matching_map.png", dpi=130)
    plt.close(fig)
    distances = matches.get("distance_m", pd.Series(dtype=float)).dropna()
    stats = {"cohort_units": len(matches), "candidate_matches": len(distances),
        "unmatched": int(matches.status.str.startswith("unmatched").sum()),
        "ambiguous": int(matches.ambiguous.sum()),
        "metadata_direction_mismatches": int((~matches.metadata_direction_agrees).sum()),
        "status_counts": matches.status.value_counts().to_dict(),
        "distance_m": {"min": float(distances.min()), "median": float(distances.median()), "max": float(distances.max())} if len(distances) else None,
        "source_routes": len(attrs), "local_routes": len(local_attrs), "directed_arcs": len(arcs),
        "candidate_endpoint_transitions": len(transitions), "excluded_transitions": len(excluded),
        "intersection_supported_transitions": sum(bool(t["intersection_ids"]) for t in transitions),
        "turn_records": len(turns), "local_turn_records": len(local_turns), "local_intersections": len(intersections),
        "certified_matches": 0, "validated_upstream_downstream_pairs": 0,
        "crs": "EPSG:2326", "radius_m": 50, "bearing_tolerance_degrees": 45,
        "ambiguity_distance_margin_m": 10, "manual_review": "pending", "version_reconciliation": "pending",
        "sources": {str(p): sha256_file(p) for p in [cohort, roads, metadata, network_http / "TURN.gml", network_http / "INTERSECTION.gml"]},
        "source_metadata": [json.loads(p.read_text(encoding="utf-8")) for p in sorted(network_http.glob("*.meta.json"))]}
    (output / "spatial_quality.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=Path("reports/milestone2/cohort.csv"))
    parser.add_argument("--roads", type=Path, default=Path("data/local/audit-20261019-21/network_centerline.gml"))
    parser.add_argument("--metadata", type=Path, default=Path("data/sample/verified/detectors.csv"))
    parser.add_argument("--network-http", type=Path, default=Path("data/local/pilot/network_http"))
    parser.add_argument("--output", type=Path, default=Path("reports/milestone2/spatial"))
    parser.add_argument("--acquire", action="store_true", help="Download/reuse official turn/intersection resources and CENTERLINE if absent")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.acquire:
        client = EvidenceClient(args.network_http, reuse=True)
        for name in ["TURN.gfs", "TURN.gml", "INTERSECTION.gfs", "INTERSECTION.gml", "DATA_LAST_UPDATED_DATE.csv"]:
            client.fetch(NETWORK_STATIC + name, name)
        if not args.roads.exists():
            args.roads = client.fetch(NETWORK_STATIC + "CENTERLINE.gml", "CENTERLINE.gml")
    print(json.dumps(run_pilot(args.cohort, args.roads, args.metadata, args.network_http, args.output), indent=2))


if __name__ == "__main__":
    main()
