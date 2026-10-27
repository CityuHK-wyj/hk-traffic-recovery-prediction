"""SYNTHETIC GML and geometry contract checks."""
import xml.etree.ElementTree as ET

import pytest

from traffic_recovery.network.feasibility import name_evidence, source_coordinates


def test_linestring_and_curve_preserve_source_coordinates() -> None:
    line = ET.fromstring('<g><LineString srsName="EPSG:2326" srsDimension="2"><posList>1 2 3 4</posList></LineString></g>')
    curve = ET.fromstring('<g><Curve srsName="EPSG:2326"><segments><LineStringSegment><posList>1 2 3 4</posList></LineStringSegment><LineStringSegment><posList>3 4 5 6</posList></LineStringSegment></segments></Curve></g>')
    assert source_coordinates(line) == [(1., 2.), (3., 4.)]
    assert source_coordinates(curve) == [(1., 2.), (3., 4.), (5., 6.)]


def test_unknown_crs_or_noncontinuous_curve_fails() -> None:
    wrong = ET.fromstring('<g><LineString srsName="EPSG:4326"><posList>1 2 3 4</posList></LineString></g>')
    with pytest.raises(ValueError, match="CRS"):
        source_coordinates(wrong)
    broken = ET.fromstring('<g><Curve srsName="EPSG:2326"><segments><LineStringSegment><posList>1 2 3 4</posList></LineStringSegment><LineStringSegment><posList>3 5 5 6</posList></LineStringSegment></segments></Curve></g>')
    with pytest.raises(ValueError, match="Noncontinuous"):
        source_coordinates(broken)


def test_name_is_evidence_only() -> None:
    assert name_evidence('Waterloo Road near X - Northbound', 'WATERLOO ROAD') == 'name_in_detector_description'
    assert name_evidence('Waterloo Road near X', '-99') == 'unknown_source_name'
    assert name_evidence('Waterloo Road near X', 'PRINCESS MARGARET ROAD') == 'name_not_in_detector_description'
