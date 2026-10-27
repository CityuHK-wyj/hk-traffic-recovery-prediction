"""Member 2's minimal schema/key audit, not a spatial matching implementation."""
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


def inspect_centerline(path: Path, segment_ids: set[str]) -> dict:
    """Stream official CityGML, count route IDs/directions and check ID overlap.

    Does not infer graph connectivity, validate geometry or claim detector-match
    accuracy. A shared route ID is only key compatibility, not spatial validation.
    """
    routes: set[str] = set()
    directions: Counter = Counter()
    features = 0
    duplicates = 0
    coordinate_systems: set[str] = set()
    fields: set[str] = set()
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag.endswith("}Envelope"):
            coordinate_systems.add(element.get("srsName", ""))
        if element.tag.endswith("}GenericCityObject"):
            attributes = {child.get("name"): child.findtext("{*}value", "")
                          for child in element if child.get("name")}
            fields.update(attributes)
            route = attributes.get("ROUTE_ID", "")
            if not route:
                raise ValueError("CENTERLINE feature has no ROUTE_ID")
            duplicates += route in routes
            routes.add(route)
            directions[attributes.get("TRAVEL_DIRECTION", "")] += 1
            features += 1
            element.clear()
        elif element.tag.endswith("}cityObjectMember"):
            element.clear()
    if not features:
        raise ValueError("Empty or unexpected CENTERLINE GML")
    return {"features": features, "unique_route_ids": len(routes),
            "duplicate_route_ids": duplicates, "fields": sorted(fields),
            "crs": sorted(coordinate_systems), "travel_direction_counts": dict(directions),
            "processed_segment_ids_in_centerline": len(segment_ids & routes),
            "processed_segment_ids_not_in_centerline": sorted(segment_ids - routes),
            "caveat": "Identifier overlap only; no detector matching or directed graph validated."}
