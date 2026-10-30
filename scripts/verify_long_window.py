"""Validate data-only completion, traceability, schema, and observed label support."""
from pathlib import Path
import argparse,json
import duckdb
import pandas as pd
from traffic_recovery.data.http import sha256_file


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);args=parser.parse_args();root=args.root
    downloads=json.loads((root/'download_manifest.json').read_text(encoding='utf-8'))
    assert downloads['complete'] and len(downloads['records'])==45 and not downloads['errors']
    assert sum(r['bytes'] for r in downloads['records'])==downloads['expected_bytes']
    expected=[f'{y}{m:02d}' for y in range(2023,2027) for m in range(1,13) if (y,m)<=(2026,9)]
    assert [r['month'] for r in downloads['records']]==expected
    ingestion=json.loads((root/'processed/ingest.json').read_text(encoding='utf-8'))
    boundary=json.loads((root/'raw/20261001-boundary/archive_check.json').read_text(encoding='utf-8'))
    assert sum(r['snapshots'] for r in ingestion)==sum(r['snapshots'] for r in downloads['records'])+boundary['snapshots']
    for r in ingestion:
        day=r['identity']['day'];month=Path(r['source']).parent.name
        name=f'{day}.parquet' if day[:6]==month else f'{day}-from-{month}.parquet'
        output=root/'processed/lane_snapshots'/name
        assert output.exists() and sha256_file(output)==r['sha256']
    manifest=json.loads((root/'reports/handoff_manifest.json').read_text(encoding='utf-8'))
    for name,r in manifest['outputs'].items():assert sha256_file(root/'processed/derived'/name)==r['sha256']
    events=pd.read_parquet(root/'processed/derived/events.parquet')
    assert not events.event_id.duplicated().any()
    assert not events[['detector_id','direction','lane_id','prediction_time']].duplicated().any()
    assert events.prediction_time.dt.tz is not None
    assert events.prediction_time.min()>=pd.Timestamp('2023-02-01T00:00+08:00')
    assert events.prediction_time.max()<pd.Timestamp('2026-10-01T00:00+08:00')
    for h in [15,30,60]:assert events[f'label_{h}m'].dropna().isin([0,1]).all()
    assert events.loc[events.split_proposal.eq('train'),'outcome_maturity_at'].lt(pd.Timestamp('2025-01-01T00:00+08:00')).all()
    assert events.loc[events.split_proposal.eq('validation'),'outcome_maturity_at'].lt(pd.Timestamp('2026-01-01T00:00+08:00')).all()
    con=duckdb.connect();con.execute("SET memory_limit='512MB'");con.execute("SET TimeZone='Asia/Hong_Kong'")
    paths=[str(p) for p in sorted((root/'processed/derived').glob('cleaned-*.parquet'))]
    assert len(paths)==(pd.Timestamp('2026-10-01')-pd.Timestamp('2023-01-01')).days
    totals=con.execute('''SELECT count(*) AS rows, count(speed_kmh) AS valid_speed_rows,
       count(occupancy_pct) AS valid_occupancy_rows, count(volume_count) AS valid_volume_rows,
       count(*) FILTER(WHERE conflict) AS conflicts,
       count(*) FILTER(WHERE conflict AND (speed_kmh IS NOT NULL OR volume_count IS NOT NULL OR occupancy_pct IS NOT NULL OR speed_sd_kmh IS NOT NULL)) AS unmasked_conflicts,
       count(*) FILTER(WHERE valid<>'Y' AND (speed_kmh IS NOT NULL OR occupancy_pct IS NOT NULL OR volume_count IS NOT NULL)) AS unmasked_offline,
       count(*) FILTER(WHERE occupancy_pct<0 OR occupancy_pct>100 OR speed_kmh<0 OR volume_count<0) AS invalid_domain_values,
       min(timestamp)::VARCHAR AS first_observation,max(timestamp)::VARCHAR AS last_observation
       FROM read_parquet(?)''',[paths]).fetchdf().iloc[0].to_dict()
    assert totals['unmasked_conflicts']==totals['unmasked_offline']==totals['invalid_domain_values']==0
    report={'status':'passed','checks':['45 official monthly archives plus next-day boundary',
        'ZIP snapshot counts reconcile with processed capture entries including duplicate names',
        'All compact capture files and final handoff outputs match recorded SHA-256',
        'One unique event ID/key, binary-or-unknown labels, time-aware prediction dates',
        'One cleaned partition per observation day, valid domains, all conflicting/offline measurements masked'],
        'cleaned_lane_observations':totals,'event_rows':len(events),
        'limitations':'No claim of physical lane stability, incident causality, exact recovery time, model accuracy, or scientific approval.'}
    (root/'reports/validation.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    print(json.dumps(report,indent=2,default=str))


if __name__=='__main__':main()
