"""Synthetic boundary checks; no research measurements are manufactured."""
from pathlib import Path
import pandas as pd
import pytest
from traffic_recovery.data.long_window import parse_rows,compact_rows
from traffic_recovery.data.pilot_ingest import compact_snapshot
from traffic_recovery.data.traffic import SchemaError

PAYLOAD=(Path(__file__).parent/'fixtures/raw_synthetic.xml').read_bytes()
MEMBER='20260102-0010-rawSpeedVol-all.xml'


def test_batch_matches_existing_adapter_and_handles_midnight():
    frame,_=compact_rows(parse_rows(PAYLOAD,MEMBER))
    original=compact_snapshot(PAYLOAD,MEMBER)
    pd.testing.assert_frame_equal(original,frame[list(original.columns)],check_dtype=False)


def test_later_revision_is_retained_separately_until_availability_filter():
    first=parse_rows(PAYLOAD,MEMBER)
    second=parse_rows(PAYLOAD.replace(b'<speed>40</speed>',b'<speed>55</speed>'),'20260102-0030-rawSpeedVol-all.xml')
    frame,_=compact_rows(first+second)
    assert len(frame)==2
    assert not frame.conflict.any()
    assert frame.speed_kmh.tolist()==[40,55]
    assert frame.available_at.nunique()==2


def test_within_snapshot_conflict_masks_every_measurement():
    first=parse_rows(PAYLOAD,MEMBER)
    second=parse_rows(PAYLOAD.replace(b'<speed>40</speed>',b'<speed>55</speed>'),MEMBER)
    frame,_=compact_rows(first+second)
    assert len(frame)==1 and frame.conflict.all()
    assert frame[['speed_kmh','volume_count','occupancy_pct','speed_sd_kmh']].isna().all().all()


@pytest.mark.parametrize('value',['-1','inf','1.5','bad',''])
def test_invalid_speed_does_not_become_zero(value):
    payload=PAYLOAD.replace(b'<speed>40</speed>',f'<speed>{value}</speed>'.encode())
    frame,_=compact_rows(parse_rows(payload,MEMBER))
    assert frame.speed_kmh.isna().all()


def test_explicit_cohort_never_substitutes_another_detector():
    assert parse_rows(PAYLOAD,MEMBER,{'OTHER_SYNTHETIC'})==[]
    assert len(parse_rows(PAYLOAD,MEMBER,{'TEST001'}))==1


def test_missing_tag_fails_instead_of_inventing_missing_observation():
    with pytest.raises(SchemaError):
        parse_rows(PAYLOAD.replace(b'<speed>40</speed>',b''),MEMBER)


def test_duplicate_zip_entry_names_preserve_both_versions_and_quarantine(tmp_path):
    import importlib.util
    import zipfile
    from traffic_recovery.data.http import sha256_file
    from traffic_recovery.data.coverage import deduplicate
    spec=importlib.util.spec_from_file_location('long_preparation',Path(__file__).parents[1]/'scripts/prepare_long_window.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    archive=tmp_path/'source.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr(MEMBER,PAYLOAD)
        with pytest.warns(UserWarning,match='Duplicate name'):
            z.writestr(MEMBER,PAYLOAD.replace(b'<speed>40</speed>',b'<speed>55</speed>'))
    destination=tmp_path/'capture.parquet'
    module.ingest_job((str(archive),'20260102',str(destination),None,sha256_file(archive),{}))
    frame=pd.read_parquet(destination)
    assert len(frame)==2 and frame.source_file.nunique()==2
    assert set(frame.speed_kmh)=={40,55}
    quality=deduplicate(frame)
    assert len(quality)==1 and quality.conflict.all() and quality.speed_kmh.isna().all()


def test_truncated_snapshot_is_explicitly_quarantined(tmp_path):
    import importlib.util,zipfile
    from traffic_recovery.data.http import sha256_file
    spec=importlib.util.spec_from_file_location('long_preparation_badxml',Path(__file__).parents[1]/'scripts/prepare_long_window.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    archive=tmp_path/'source.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr(MEMBER,PAYLOAD)
        z.writestr(MEMBER.replace('0010','0011'),PAYLOAD[:-40])
    record=module.ingest_job((str(archive),'20260102',str(tmp_path/'capture.parquet'),None,sha256_file(archive),{}))
    assert record['snapshots']==2 and record['parsed_snapshots']==1
    assert len(record['quarantined_snapshots'])==1
    assert record['quarantined_snapshots'][0]['original_xml_parse_error']
    assert len(pd.read_parquet(tmp_path/'capture.parquet'))==1


def test_complete_day_outage_produces_empty_typed_tables(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('long_preparation_outage',Path(__file__).parents[1]/'scripts/prepare_long_window.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.profile_job((pd.Timestamp('2026-01-02',tz='Asia/Hong_Kong'),[],str(tmp_path),['TEST001']))
    bins=pd.read_parquet(tmp_path/'bins-20260102.parquet')
    cleaned=pd.read_parquet(tmp_path/'cleaned-20260102.parquet')
    assert bins.empty and cleaned.empty
    assert str(cleaned.timestamp.dt.tz)=='Asia/Hong_Kong'


def test_training_labels_must_mature_before_next_fit_boundary():
    import importlib.util
    spec=importlib.util.spec_from_file_location('long_labels',Path(__file__).parents[1]/'scripts/label_long_window.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    events=pd.DataFrame({'prediction_time':pd.to_datetime(['2024-12-31T22:55+08:00','2024-12-31T22:40+08:00']),
        'onset_time':pd.to_datetime(['2024-12-31T22:45+08:00','2024-12-31T22:30+08:00']),
        'episode_separated_at':pd.to_datetime(['2024-12-31T23:30+08:00','2024-12-31T23:10+08:00'])})
    splits,maturity=module.availability_safe_splits(events,pd.Timestamp('2025-01-01T00:00+08:00'),
        pd.Timestamp('2026-01-01T00:00+08:00'),pd.Timestamp('2026-10-01T00:00+08:00'))
    assert splits.tolist()==['purged','train']
    assert maturity.iloc[0]==pd.Timestamp('2025-01-01T00:05+08:00')
