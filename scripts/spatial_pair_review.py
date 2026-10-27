"""Create focused human-review packets for the six existing candidate pairs.

Source-backed evidence only: no approval or historical validity is inferred.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely import wkb
from shapely.geometry import Point

REPORT = Path("reports/spatial_feasibility")
DATA = Path("data/local/spatial-feasibility")
OUT = Path("reports/spatial_pair_review")


def main() -> None:
    """Produce six auditable plots and checklists without changing review status."""
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = pd.read_csv(REPORT / "candidate_detector_connections.csv", dtype=str).fillna("")
    mapping = pd.read_csv(REPORT / "detector_mapping.csv", dtype=str).fillna("")
    candidates = pd.read_csv(REPORT / "matching_candidates.csv", dtype=str).fillna("")
    roads = pd.read_parquet(DATA / "source_roads.parquet")
    roads_by_id = {r.ROUTE_ID: r for r in roads.itertuples(index=False)}
    turns = pd.read_csv(REPORT / "source_turns.csv", dtype=str).fillna("")
    intersections = pd.read_csv(REPORT / "source_intersections.csv", dtype=str).fillna("")
    if len(pairs) != 6:
        raise ValueError("Expected the six existing source-supported candidates; inspect input changes")
    summary = []
    for index, pair in pairs.iterrows():
        route_ids = [pair.from_route, pair.to_route]
        selected = [mapping.loc[mapping.detector_id.eq(pair.upstream_detector)].iloc[0],
                    mapping.loc[mapping.detector_id.eq(pair.downstream_detector)].iloc[0]]
        related_turns = turns.loc[turns[[f"EDGE{i}FID" for i in range(1, 9)]].isin(route_ids).any(axis=1)]
        exact_intersection = intersections.loc[intersections.INT_ID.eq(pair.intersection_ids)]
        if len(exact_intersection) != 1:
            raise ValueError("Intersection evidence missing or not unique")
        a, b = [wkb.loads(roads_by_id[r].geometry_wkb) for r in route_ids]
        positions = [Point(float(m.easting), float(m.northing)) for m in selected]
        junction = Point(float(pair.easting), float(pair.northing))
        minx = min([a.bounds[0], b.bounds[0], junction.x] + [p.x for p in positions]) - 100
        maxx = max([a.bounds[2], b.bounds[2], junction.x] + [p.x for p in positions]) + 100
        miny = min([a.bounds[1], b.bounds[1], junction.y] + [p.y for p in positions]) - 100
        maxy = max([a.bounds[3], b.bounds[3], junction.y] + [p.y for p in positions]) + 100
        fig, ax = plt.subplots(figsize=(10, 7))
        for road in roads.itertuples(index=False):
            geom = wkb.loads(road.geometry_wkb)
            x0, y0, x1, y1 = geom.bounds
            if x1 < minx or x0 > maxx or y1 < miny or y0 > maxy:
                continue
            ax.plot(*geom.xy, color="0.8", linewidth=.6)
        for geom, route, color in [(a, route_ids[0], "royalblue"), (b, route_ids[1], "darkorange")]:
            ax.plot(*geom.xy, color=color, linewidth=2.5, label=f"candidate route {route} (digitised forward)")
            p1, p2 = geom.interpolate(.45, normalized=True), geom.interpolate(.55, normalized=True)
            ax.annotate('', (p2.x, p2.y), (p1.x, p1.y), arrowprops={"arrowstyle": "->", "color": color, "lw": 1.5})
        for point, item in zip(positions, selected):
            ax.scatter(point.x, point.y, color="red", zorder=5)
            ax.annotate(item.detector_id, (point.x, point.y), fontsize=9)
        ax.scatter(junction.x, junction.y, marker="x", s=90, color="black", label=f"source intersection {pair.intersection_ids}", zorder=6)
        ax.set(xlim=(minx,maxx), ylim=(miny,maxy), xlabel="Easting EPSG:2326 (m)", ylabel="Northing EPSG:2326 (m)",
               title=f"Candidate {index+1}: {pair.upstream_detector} → {pair.downstream_detector}\nNot verified: inspect direction, level, restrictions, historical validity")
        ax.set_aspect("equal")
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.legend(fontsize=8)
        fig.tight_layout()
        figure = OUT / f"pair-{index+1}.png"
        fig.savefig(figure, dpi=140)
        plt.close(fig)
        related_turns.to_csv(OUT / f"pair-{index+1}-turns.csv", index=False)
        candidates.loc[candidates.detector_id.isin([pair.upstream_detector, pair.downstream_detector])].to_csv(OUT / f"pair-{index+1}-alternatives.csv", index=False)
        exact_intersection.to_csv(OUT / f"pair-{index+1}-intersection.csv", index=False)
        record = {"pair": index+1, "upstream_candidate": pair.upstream_detector, "downstream_candidate": pair.downstream_detector,
                  "from_arc": pair.from_arc, "to_arc": pair.to_arc, "intersection_id": pair.intersection_ids,
                  "source_elevation": pair.elevation, "related_turn_records": len(related_turns), "review_status": "pending",
                  "figure": figure.name, "network_version": pair.network_version}
        summary.append(record)
        lines = [f"# Candidate {index+1}: {pair.upstream_detector} → {pair.downstream_detector}", "",
            "**PENDING — no human verification, no approved feature use.** Arrows are candidate travel directions, not certified upstream/downstream relationships.", "",
            f"- Candidate arcs: `{pair.from_arc}` → `{pair.to_arc}`; shared endpoint `{pair.node}`; source intersection `{pair.intersection_ids}`.",
            f"- Source endpoint elevation: `{pair.elevation}`; intersection evidence: [CSV](pair-{index+1}-intersection.csv).",
            f"- {len(related_turns)} TURN records reference either route (not necessarily this movement): [complete rows](pair-{index+1}-turns.csv).",
            f"- [Detailed map](pair-{index+1}.png) and [all 50 m detector alternatives](pair-{index+1}-alternatives.csv).",
            f"- Network identifier: `{pair.network_version}`; source revision cut-off is not historical validity.", ""]
        for m in selected:
            r = roads_by_id[m.route_id]
            lines.extend([f"### {m.detector_id}: selected route {m.route_id}",
                f"- Feed direction: {m.direction}; current metadata direction: {m.metadata_direction}; literal agreement: {m.metadata_direction_agrees}.",
                f"- Source road: {m.road_name}; detector description: {m.detector_road}; name evidence: {m.name_evidence}.",
                f"- Candidate distance: {float(m.distance_m):.2f} m; bearing difference: {float(m.direction_difference_deg):.2f}°; ambiguity: {m.ambiguous}.",
                f"- Source travel-direction code: {r.TRAVEL_DIRECTION}; elevation: {r.ELEVATION}; creation/update: {r.CRE_DATE} / {r.LAST_UPD_DATE_V}.", ""])
        lines += ["## Independent reviewer checklist", "",
            "- [ ] Verify both detector coordinates, physical carriageway and historical effective dates against authoritative evidence.",
            "- [ ] Resolve feed-versus-metadata direction, local line bearing, lane orientation and all plausible alternatives.",
            "- [ ] Confirm source route geometries meet at the actual junction and are on the same navigable level.",
            "- [ ] Inspect every applicable TURN row, including EDGE1END, positions, vehicle/time restrictions and multi-edge paths.",
            "- [ ] Confirm this directed movement is permitted and source/network versions were valid at prediction time.",
            "- [ ] Record decision (verified / rejected / ambiguous), reviewer, evidence URLs/checksums, method and validity interval.",
            "- [ ] If anything is unresolved, retain `pending`; do not feed this pair into directed spatial features.", ""]
        (OUT / f"pair-{index+1}.md").write_text("\n".join(lines), encoding="utf-8")
    pd.DataFrame(summary).to_csv(OUT / "pair_review_index.csv", index=False)
    (OUT / "README.md").write_text("# Six source-supported pair review packets\n\nAll are pending; no independent review is implied. See individual maps, TURN rows, intersection evidence and checklists.\n\n" + "\n".join(f"- [Pair {r['pair']}: {r['upstream_candidate']} → {r['downstream_candidate']}](pair-{r['pair']}.md)" for r in summary) + "\n", encoding="utf-8")
    print(json.dumps({"pairs": len(summary), "verified": 0, "status": "pending", "directory": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
