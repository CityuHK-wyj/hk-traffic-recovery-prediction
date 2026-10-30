"""Synthetic subset equivalence tests; never traffic-recovery evidence."""
import importlib.util
from pathlib import Path
import copy
import xml.etree.ElementTree as ET
import pandas as pd
from traffic_recovery.data.traffic import parse_traffic

spec=importlib.util.spec_from_file_location('prepare_selected',Path(__file__).parents[1]/'scripts/prepare_selected_pilot.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_selection_preserves_full_parser_values():
    root=ET.fromstring((Path(__file__).parent/'fixtures/raw_synthetic.xml').read_bytes())
    detectors=root.find('./periods/period/detectors')
    extra=copy.deepcopy(detectors[0]);extra.find('detector_id').text='TEST002';detectors.append(extra)
    payload=ET.tostring(root)
    full=parse_traffic(payload)
    selected=parse_traffic(module.selected_payload(payload,{'TEST001'}))
    pd.testing.assert_frame_equal(selected.reset_index(drop=True),full.loc[full.detector_id.eq('TEST001')].reset_index(drop=True))

def test_selection_removes_other_detectors_without_changing_periods():
    payload=(Path(__file__).parent/'fixtures/raw_synthetic.xml').read_bytes()
    original=ET.fromstring(payload)
    selected=ET.fromstring(module.selected_payload(payload,set()))
    assert not selected.findall('./periods/period/detectors/detector')
    assert selected.findtext('date')==original.findtext('date')
    assert selected.findtext('./periods/period/period_to')==original.findtext('./periods/period/period_to')
