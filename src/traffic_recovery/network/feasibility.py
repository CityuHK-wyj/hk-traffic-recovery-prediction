"""Real subset topology and detector matching audit; candidates are NOT certified.

Streams official EPSG:2326 GML around medium-pilot detectors, and writes a
conservative endpoint/turn graph. No automatic human review is invented.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from traffic_recovery.data.http import sha256_file
from traffic_recovery.data.traffic import parse_traffic
from traffic_recovery.network.pilot import COMPASS, directed_arcs, graph_transitions, match_candidates, read_features
from traffic_recovery.network.spatial_features import neighbor_features


def source_coordinates(element) -> list[tuple[float, float]]:
    """Extract EPSG:2326 LineString or continuous Curve LineStringSegments.

    Unknown geometry and noncontinuous curve segments fail explicitly. Original
    source vertices are retained; no geometric intersection splitting is done.
    """
    lines = element.findall(".//{*}LineString")
    curves = element.findall(".//{*}Curve")
    if len(lines) + len(curves) != 1:
        raise ValueError("Expected one source LineString or Curve")
    geom = (lines or curves)[0]
    if geom.get("srsName") != "EPSG:2326" or geom.get("srsDimension", "2") != "2":
        raise ValueError("Unexpected road CRS or dimension")
    lists = geom.findall("./{*}posList") if lines else geom.findall("./{*}segments/{*}LineStringSegment/{*}posList")
    if not lists or (curves and len(lists) != len(geom.findall("./{*}segments/*"))):
        raise ValueError("Unexpected source curve segments")
    points = []
    for pos in lists:
        values = [float(x) for x in (pos.text or "").split()]
        if len(values) < 4 or len(values) % 2:
            raise ValueError("Malformed source coordinates")
        segment = list(zip(values[::2], values[1::2]))
        if points and points[-1] != segment[0]:
            raise ValueError("Noncontinuous source curve")
        points.extend(segment if not points else segment[1:])
    return points


def subset_roads(path: Path, points: list[Point], radius: float) -> tuple[list[dict], list[LineString]]:
    """Stream centerlines; keep source lines within radius metres of input points."""
    attrs, lines = [], []
    for attr, element in read_features(path):
        coords = source_coordinates(element)
        xs, ys = zip(*coords)
        bounds = (min(xs) - radius, min(ys) - radius, max(xs) + radius, max(ys) + radius)
        if not any(bounds[0] <= p.x <= bounds[2] and bounds[1] <= p.y <= bounds[3] for p in points):
            continue
        line = LineString(coords)
        if any(line.distance(p) <= radius for p in points):
            attrs.append(attr)
            lines.append(line)
    if not lines or len({a["ROUTE_ID"] for a in attrs}) != len(attrs):
        raise ValueError("Empty subset or duplicate route IDs")
    return attrs, lines


def name_evidence(detector_road: str, source_name: str) -> str:
    """Compare official source name as literal normalized substring; never certify."""
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    road = normalize(str(source_name))
    detector = normalize(str(detector_road))
    if not road or road in {"99", "nan", "na"}:
        return "unknown_source_name"
    return "name_in_detector_description" if road in detector else "name_not_in_detector_description"


def components(arcs: list[dict]) -> dict:
    """Weak endpoint components; not legal-route or detector coverage claims."""
    links = defaultdict(set)
    for arc in arcs:
        a, b = arc["from_node"], arc["to_node"]
        links[a].add(b)
        links[b].add(a)
    remaining = set(links)
    sizes = []
    while remaining:
        stack = [remaining.pop()]
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for node in links[current] & remaining:
                remaining.remove(node)
                stack.append(node)
        sizes.append(size)
    return {"nodes": len(links), "weak_components": len(sizes), "largest_weak_component_nodes": max(sizes, default=0)}


def run(output: Path, data_output: Path, input_dir: Path, roads: Path, metadata: Path, network_http: Path) -> dict:
    """Write source-backed candidates, versioned graph, review map and NA features."""
    output.mkdir(parents=True, exist_ok=True)
    data_output.mkdir(parents=True, exist_ok=True)
    bins_paths = sorted(input_dir.glob("bins-*.parquet"))
    if len(bins_paths) != 3:
        raise ValueError("Expected verified medium pilot's three bin partitions")
    for path in bins_paths:
        checkpoint = input_dir / f"checkpoint-{path.stem.removeprefix('bins-')}.json"
        record = json.loads(checkpoint.read_text(encoding="utf-8"))
        if record["outputs"].get(path.name) != sha256_file(path):
            raise ValueError(f"Invalid medium-pilot checkpoint: {path}")
    bins = pd.concat([pd.read_parquet(path) for path in bins_paths], ignore_index=True)
    events_path = input_dir / "medium_events.parquet"
    events = pd.read_parquet(events_path)
    recorded = json.loads(Path("reports/medium_pilot/statistics.json").read_text(encoding="utf-8"))
    if recorded["events_sha256"] != sha256_file(events_path):
        raise ValueError("Medium events hash differs from validation evidence")
    references = pd.read_csv("reports/medium_pilot/reference.csv")
    references["reference_fit_end"] = pd.to_datetime(references.reference_fit_end, utc=True).dt.tz_convert("Asia/Hong_Kong")
    units = bins[["detector_id", "direction", "lane_id"]].drop_duplicates().sort_values(["detector_id", "direction", "lane_id"])
    selected = units.drop_duplicates(["detector_id", "direction"])
    detectors = pd.read_csv(metadata, dtype={"AID_ID_Number": str}, encoding="utf-8-sig")
    selected = selected.merge(detectors, left_on="detector_id", right_on="AID_ID_Number", how="left", validate="many_to_one")
    if selected[["Easting", "Northing"]].isna().any().any():
        raise ValueError("Missing detector coordinates")
    points = [Point(x, y) for x, y in zip(selected.Easting, selected.Northing)]
    attrs, lines = subset_roads(roads, points, 500)
    tree = STRtree(lines)
    version = "centerline-sha256:" + sha256_file(roads)
    mapping_version = "candidate-geometry-name-direction-v1"
    rows, alternatives = [], []
    for (_, detector), point in zip(selected.iterrows(), points):
        candidates = match_candidates(point, detector.direction, attrs, lines, tree)
        for candidate in candidates:
            candidate["name_evidence"] = name_evidence(detector.Road_EN, candidate["road_name"])
        compatible = [c for c in candidates if c["direction_compatible"]]
        named = [c for c in compatible if c["name_evidence"] == "name_in_detector_description"]
        # Prefer a compatible named road over a nearer unnamed/unrelated road,
        # but keep every candidate and record ambiguity; never claim verification.
        chosen = (named or compatible or [None])[0]
        base = {"detector_id": detector.detector_id, "direction": detector.direction, "lane_id": detector.lane_id,
                "metadata_direction": detector.Direction, "metadata_direction_agrees": detector.direction == detector.Direction,
                "detector_road": detector.Road_EN, "easting": point.x, "northing": point.y,
                "network_version": version, "mapping_version": mapping_version, "review_status": "pending",
                "reviewer": None, "valid_from": None, "valid_to": None}
        alternatives.extend(base | c for c in candidates)
        if chosen is None:
            rows.append(base | {"status": "unmatched_direction" if candidates else "unmatched_distance",
                                "candidate_count": len(candidates), "compatible_count": 0, "ambiguous": False,
                                "arc_id": None})
        else:
            # All nearby direction-compatible alternatives, including different names,
            # remain potential parallel-road/flyover ambiguity.
            ambiguous = sum(c["distance_m"] <= chosen["distance_m"] + 10 for c in compatible) > 1
            reasons = []
            if ambiguous:
                reasons.append("multiple_direction_compatible_nearby_routes")
            if not base["metadata_direction_agrees"]:
                reasons.append("metadata_direction_mismatch")
            if chosen["name_evidence"] != "name_in_detector_description":
                reasons.append(chosen["name_evidence"])
            rows.append(base | chosen | {"status": "review_required", "ambiguity_reasons": "|".join(reasons),
                "candidate_count": len(candidates), "compatible_count": len(compatible), "ambiguous": ambiguous,
                "arc_id": chosen["route_id"] + (":F" if chosen["orientation"] == "forward" else ":R")})
    matches = pd.DataFrame(rows)
    matches.to_csv(output / "detector_mapping.csv", index=False)
    pd.DataFrame(alternatives).to_csv(output / "matching_candidates.csv", index=False)
    pd.DataFrame([a | {"geometry_wkb": g.wkb, "length_m": g.length, "network_version": version, "crs": "EPSG:2326"}
                  for a, g in zip(attrs, lines)]).to_parquet(data_output / "source_roads.parquet", index=False, compression="zstd")
    arcs = directed_arcs(attrs, lines)
    pd.DataFrame([{**arc, "from_node": str(arc["from_node"]), "to_node": str(arc["to_node"]), "network_version": version}
                  for arc in arcs]).to_parquet(data_output / "directed_arcs.parquet", index=False, compression="zstd")
    turns = [a for a, _ in read_features(network_http / "TURN.gml")]
    allowed, excluded = graph_transitions(arcs, turns)
    local_ids = {a["ROUTE_ID"] for a in attrs}
    intersection_pairs = defaultdict(list)
    intersection_rows = []
    for attr, element in read_features(network_http / "INTERSECTION.gml"):
        ids = {attr.get(f"RD_ID_{i}") for i in range(1, 11)} - {None, ""}
        if not ids & local_ids:
            continue
        point = element.find(".//{*}Point")
        if point is None or point.get("srsName") != "EPSG:2326":
            raise ValueError("Unexpected source intersection CRS")
        x, y = map(float, point.findtext("{*}pos", "").split())
        intersection_rows.append(attr | {"easting": x, "northing": y})
        for a in ids & local_ids:
            for b in ids & local_ids:
                if a != b:
                    intersection_pairs[(a, b)].append((attr["INT_ID"], x, y))
    pd.DataFrame(intersection_rows).to_csv(output / "source_intersections.csv", index=False)
    local_turns = [t for t in turns if any(t.get(f"EDGE{i}FID") in local_ids for i in range(1, 9))]
    pd.DataFrame(local_turns).to_csv(output / "source_turns.csv", index=False)
    arc_lookup = {a["arc_id"]: a for a in arcs}
    graph_rows = []
    for transition, rejected in [(t, False) for t in allowed] + [(t, True) for t in excluded]:
        x, y, elevation = arc_lookup[transition["from_arc"]]["to_node"]
        supported = [str(i) for i, px, py in intersection_pairs[(transition["from_route"], transition["to_route"])]
                     if math.hypot(px - x, py - y) <= 1]
        graph_rows.append(transition | {"easting": x, "northing": y, "elevation": elevation,
            "intersection_ids": "|".join(supported), "automatic_status": "rejected_restriction_or_uturn" if rejected else
                ("source_supported_review_pending" if supported else "ambiguous_no_source_intersection"),
            "network_version": version, "review_status": "pending", "reviewer": None, "valid_from": None, "valid_to": None})
    transition_frame = pd.DataFrame(graph_rows)
    matched_arcs = set(matches.arc_id.dropna())
    transition_frame["touches_matched_arc"] = transition_frame.from_arc.isin(matched_arcs) | transition_frame.to_arc.isin(matched_arcs)
    transition_frame.to_csv(data_output / "directed_transitions.csv", index=False)
    supported = transition_frame.loc[transition_frame.automatic_status.eq("source_supported_review_pending")]
    detector_arc = matches.loc[matches.arc_id.notna(), ["detector_id", "direction", "arc_id"]]
    pairs = supported.merge(detector_arc.rename(columns={"detector_id": "upstream_detector", "direction": "upstream_direction"}),
                            left_on="from_arc", right_on="arc_id")
    pairs = pairs.merge(detector_arc.rename(columns={"detector_id": "downstream_detector", "direction": "downstream_direction"}),
                        left_on="to_arc", right_on="arc_id", suffixes=("_up", "_down"))
    pairs = pairs.loc[pairs.upstream_detector.ne(pairs.downstream_detector)].copy()
    pairs.to_csv(output / "candidate_detector_connections.csv", index=False)
    levels = defaultdict(set)
    for arc in arcs:
        for x, y, elevation in [arc["from_node"], arc["to_node"]]:
            levels[(x, y)].add(elevation)
    grade_separated_xy = sum(len(elevations) > 1 for elevations in levels.values())
    sample = pd.concat([transition_frame.loc[transition_frame.automatic_status.eq(status)].sort_values(
        "touches_matched_arc", ascending=False).head(15) for status in
        ["source_supported_review_pending", "ambiguous_no_source_intersection", "rejected_restriction_or_uturn"]]).head(45)
    sample.to_csv(output / "connection_review_sample.csv", index=False)
    # Static overview: source roads and detector coordinates; no automated map is
    # presented as independent ground truth.
    fig, ax = plt.subplots(figsize=(13, 10))
    for line in lines:
        x, y = line.xy
        ax.plot(x, y, color="0.76", linewidth=.35)
    ax.scatter(matches.easting, matches.northing, c=matches.ambiguous.map({True: "darkorange", False: "royalblue"}), s=30, zorder=3)
    for _, row in matches.iterrows():
        ax.annotate(row.detector_id, (row.easting, row.northing), fontsize=5)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.set(title="Detector/road subset — candidates only, manual review pending\nOrange: geometrically ambiguous; blue: other (not verified)",
           xlabel="Easting EPSG:2326 (m)", ylabel="Northing EPSG:2326 (m)")
    fig.tight_layout()
    fig.savefig(output / "detector_map.png", dpi=160)
    plt.close(fig)
    # Per-detector maps show chosen route and all roads, so names/direction can be audited.
    for offset in range(0, len(matches), 12):
        subset = matches.iloc[offset:offset + 12]
        fig, axes = plt.subplots(4, 3, figsize=(15, 18))
        route_lookup = {a["ROUTE_ID"]: i for i, a in enumerate(attrs)}
        for ax, (_, row) in zip(axes.flat, subset.iterrows()):
            p = Point(row.easting, row.northing)
            for idx in tree.query(p, predicate="dwithin", distance=150):
                x, y = lines[idx].xy
                ax.plot(x, y, color="0.75", linewidth=.8)
            if pd.notna(row.get("route_id")):
                line = lines[route_lookup[row.route_id]]
                x, y = line.xy
                ax.plot(x, y, color="blue", linewidth=1.8)
                position = line.project(p)
                a = line.interpolate(max(0, position - 15))
                b = line.interpolate(min(line.length, position + 15))
                if row.orientation == "reverse":
                    a, b = b, a
                ax.annotate("", (b.x, b.y), (a.x, a.y), arrowprops={"arrowstyle": "->", "color": "blue"})
            angle = math.radians(COMPASS[row.direction])
            ax.arrow(p.x, p.y, 25*math.sin(angle), 25*math.cos(angle), color="red", width=.8, length_includes_head=True)
            ax.scatter(p.x, p.y, color="red", s=18)
            ax.set(xlim=(p.x-120, p.x+120), ylim=(p.y-120, p.y+120),
                   title=f"{row.detector_id} {row.direction} / {row.get('route_id', 'none')}\n{row.get('ambiguity_reasons', row.status)}", aspect="equal")
            ax.tick_params(labelsize=5)
            ax.ticklabel_format(useOffset=False, style="plain")
        for ax in list(axes.flat)[len(subset):]:
            ax.set_visible(False)
        fig.suptitle("Candidate mapping only — EPSG:2326; blue road travel / red observed direction; no independent approval", fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, .98))
        fig.savefig(output / f"detector_review_{offset//12+1}.png", dpi=130)
        plt.close(fig)
    cutoff = pd.Timestamp(recorded["reference_end"])
    spatial = neighbor_features(events, matches, transition_frame, bins, references, network_version=version,
                                reference_cutoff=cutoff)
    features = events[["event_id", "detector_id", "direction", "lane_id", "speed_kmh", "speed_ratio", "baseline_kmh"]].merge(spatial, on="event_id", validate="one_to_one")
    features.to_parquet(data_output / "spatial_features.parquet", index=False)
    features.to_csv(output / "spatial_features_review.csv", index=False)
    distances = matches.distance_m.dropna()
    segment_path = Path("data/sample/verified/segment_current.xml")
    segments = parse_traffic(segment_path.read_bytes())
    audit_path = Path("reports/data_audit.json")
    prior_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    stats = {"crs": "EPSG:2326", "network_version": version, "mapping_version": mapping_version,
        "network_revision_cutoff_source": (network_http / "DATA_LAST_UPDATED_DATE.csv").read_text(encoding="utf-8-sig").strip(),
        "subset_radius_m": 500, "source_routes_in_subset": len(attrs), "route_length_total_m": sum(g.length for g in lines),
        "directed_arcs": len(arcs), "endpoint_graph": components(arcs),
        "coincident_endpoint_xy_multiple_elevations": grade_separated_xy,
        "source_supported_candidate_detector_pairs": len(pairs),
        "connections": transition_frame.automatic_status.value_counts().to_dict(), "human_verified_connections": 0,
        "connection_review_sample_count": len(sample), "sample_touching_matched_arcs": int(sample.touches_matched_arc.sum()),
        "candidate_transitions_touching_matched_arcs": int(transition_frame.touches_matched_arc.sum()),
        "turn_records_total": len(turns), "local_turn_records": len(local_turns),
        "source_intersection_records_local": len(intersection_rows),
        "detector_direction_units": len(matches), "automated_candidate_matches": int(matches.arc_id.notna().sum()),
        "detector_units_with_ambiguous_matches": int(matches.ambiguous.sum()),
        "unmatched": int(matches.arc_id.isna().sum()), "human_verified_matches": 0,
        "metadata_direction_mismatches": int((~matches.metadata_direction_agrees).sum()),
        "all_candidates": len(alternatives), "direction_incompatible_candidates": sum(not c["direction_compatible"] for c in alternatives),
        "direction_compatible_selected": int(matches.direction_compatible.fillna(False).sum()),
        "candidate_bearing_difference_degrees": {"median": float(matches.direction_difference_deg.median()),
                                                  "max": float(matches.direction_difference_deg.max())},
        "selected_candidates_in_current_processed_ids": int(matches.route_id.isin(set(segments.segment_id)).sum()),
        "current_processed_version": str(segments.irn_version.iloc[0]),
        "prior_audit_processed_ids_missing_from_full_centerline": len(prior_audit["road_network"]["processed_segment_ids_not_in_centerline"]),
        "selected_name_evidence_counts": matches.get("name_evidence", pd.Series(dtype=str)).value_counts().to_dict(),
        "candidate_distance_m": {"min": float(distances.min()), "median": float(distances.median()),
            "p90": float(distances.quantile(.9)), "max": float(distances.max())} if len(distances) else None,
        "feature_rows": len(features), "feature_status": features.feature_status.value_counts().to_dict(),
        "events_with_verified_upstream_observations": int(features.upstream_observed_detectors.gt(0).sum()),
        "events_with_verified_downstream_observations": int(features.downstream_observed_detectors.gt(0).sum()),
        "sources": {str(p): sha256_file(p) for p in [roads, metadata, network_http / "TURN.gml", network_http / "INTERSECTION.gml", network_http / "DATA_LAST_UPDATED_DATE.csv", Path("reports/medium_pilot/reference.csv"), segment_path, audit_path, events_path, *bins_paths]},
        "limits": ["all matching and connections require independent manual review and time-version reconciliation",
            "endpoint graph may overrestrict source turns and miss interior topology", "medium cohort is convenience-selected"]}
    stats["derived_sha256"] = {str(p): sha256_file(p) for p in [data_output / "source_roads.parquet",
        data_output / "directed_arcs.parquet", data_output / "directed_transitions.csv", data_output / "spatial_features.parquet",
        output / "detector_mapping.csv", output / "matching_candidates.csv", output / "connection_review_sample.csv"]}
    (output / "quality.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/spatial_feasibility"))
    parser.add_argument("--input", type=Path, default=Path("data/local/pilot/medium-40"))
    parser.add_argument("--data-output", type=Path, default=Path("data/local/spatial-feasibility"))
    parser.add_argument("--roads", type=Path, default=Path("data/local/audit-20261019-21/network_centerline.gml"))
    parser.add_argument("--metadata", type=Path, default=Path("data/sample/verified/detectors.csv"))
    parser.add_argument("--network-http", type=Path, default=Path("data/local/pilot/network_http"))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.data_output, args.input, args.roads, args.metadata, args.network_http), indent=2))


if __name__ == "__main__":
    main()
