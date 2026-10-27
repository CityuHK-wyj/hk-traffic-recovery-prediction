"""Explicitly SYNTHETIC topology; not evidence of real HK matching accuracy."""
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from traffic_recovery.network.pilot import directed_arcs, graph_transitions, match_candidates


def attrs(route: str, direction: str = "3", elevation: str = "0") -> dict:
    return {"ROUTE_ID": route, "TRAVEL_DIRECTION": direction, "ELEVATION": elevation, "STREET_ENAME": "SYNTHETIC"}


def test_direction_rejects_nearby_wrong_way_and_bidirectional_allows_reverse() -> None:
    lines = [LineString([(0, 0), (100, 0)])]
    tree = STRtree(lines)
    result = match_candidates(Point(50, 2), "West", [attrs("TEST")], lines, tree)
    assert result[0]["distance_m"] == 2
    assert not result[0]["direction_compatible"]
    result = match_candidates(Point(50, 2), "West", [attrs("TEST", "1")], lines, tree)
    assert result[0]["direction_compatible"] and result[0]["orientation"] == "reverse"
    assert match_candidates(Point(50, 1000), "East", [attrs("TEST")], lines, tree) == []


def test_crossings_do_not_connect_and_grade_separation_respected() -> None:
    attributes = [attrs("A"), attrs("B"), attrs("C", elevation="1")]
    lines = [LineString([(0, 0), (10, 0)]), LineString([(5, -5), (5, 5)]), LineString([(10, 0), (20, 0)])]
    arcs = directed_arcs(attributes, lines)
    allowed, _ = graph_transitions(arcs, [])
    assert allowed == []  # B crosses interior, C has a different elevation


def test_real_endpoint_identity_direction_and_turn_constraints() -> None:
    attributes = [attrs("A", "1"), attrs("B"), attrs("C")]
    lines = [LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)]), LineString([(20, 0), (30, 0)])]
    arcs = directed_arcs(attributes, lines)
    assert len(arcs) == 4
    allowed, excluded = graph_transitions(arcs, [{"TURN_ID": "SYNTH_TURN", "NO_TURN": "-1", "EDGE1FID": "A", "EDGE2FID": "B"}])
    assert [(a["from_arc"], a["to_arc"]) for a in allowed] == [("B:F", "C:F")]
    assert any(e.get("turn_ids") == "SYNTH_TURN" for e in excluded)
    assert not any(a["from_arc"] == "A:R" for a in allowed)


def test_multi_edge_restriction_is_conservatively_blocked_not_ignored() -> None:
    attributes = [attrs("A"), attrs("B"), attrs("C")]
    lines = [LineString([(i * 10, 0), ((i + 1) * 10, 0)]) for i in range(3)]
    turns = [{"TURN_ID": "SYNTH_MULTIEDGE", "NO_TURN": "-1", "EDGE1FID": "A", "EDGE2FID": "B", "EDGE3FID": "C"}]
    allowed, excluded = graph_transitions(directed_arcs(attributes, lines), turns)
    assert allowed == []
    assert len(excluded) == 2
