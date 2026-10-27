"""Tiny explicitly SYNTHETIC GML test; not a measured spatial-matching example."""
from pathlib import Path

from traffic_recovery.network.audit import inspect_centerline


def test_citygml_route_ids_directions_and_crs(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.gml"
    path.write_text('''<core:CityModel xmlns:core="urn:core" xmlns:gml="urn:gml" xmlns:gen="urn:gen">
    <gml:Envelope srsName="EPSG:2326"/>
    <core:cityObjectMember><gen:GenericCityObject>
      <gen:intAttribute name="ROUTE_ID"><gen:value>TEST_A</gen:value></gen:intAttribute>
      <gen:intAttribute name="TRAVEL_DIRECTION"><gen:value>3</gen:value></gen:intAttribute>
    </gen:GenericCityObject></core:cityObjectMember></core:CityModel>''', encoding="utf-8")
    report = inspect_centerline(path, {"TEST_A", "TEST_B"})
    assert report["features"] == 1
    assert report["crs"] == ["EPSG:2326"]
    assert report["travel_direction_counts"] == {"3": 1}
    assert report["processed_segment_ids_in_centerline"] == 1
    assert report["processed_segment_ids_not_in_centerline"] == ["TEST_B"]
