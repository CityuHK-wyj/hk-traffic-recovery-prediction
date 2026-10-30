"""Complete the data-only handoff after long-window ingestion and daily quality."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import argparse,json,platform,time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traffic_recovery.data.events import UNIT,EventRules,fit_reference,build_events,assign_splits
from traffic_recovery.data.pilot import label_summary,plot_events
from traffic_recovery.data.coverage import profile_period
from traffic_recovery.data.http import sha256_file


def write_json(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding='utf-8');tmp.replace(path)


def availability_safe_splits(events,validation_start,test_start,test_end):
    """Also purge outcomes whose +10m archive closure crosses a fit boundary."""
    splits=assign_splits(events,validation_start,test_start,test_end)
    maturity=pd.concat([events.prediction_time+pd.Timedelta(minutes=70),
                        events.episode_separated_at+pd.Timedelta(minutes=10)],axis=1).max(axis=1)
    splits.loc[(splits.eq('train') & maturity.ge(validation_start)) |
               (splits.eq('validation') & maturity.ge(test_start))]='purged'
    return splits,maturity


def label_unit(job):
    root,identity,config=job;root=Path(root)
    dates={k:pd.Timestamp(v).tz_convert('Asia/Hong_Kong') for k,v in config.items() if k.endswith('_start') or k.endswith('_end')}
    paths=[str(p) for p in sorted((root/'processed/derived').glob('bins-*.parquet'))]
    filters=[(key,'==',identity[key]) for key in UNIT]
    bins=pd.read_parquet(paths,filters=filters).sort_values('timestamp')
    if bins.timestamp.duplicated().any():raise ValueError('Duplicate lane bins')
    reference=fit_reference(bins,fit_start=dates['observation_start'],fit_end=dates['reference_end'],min_bins=config['min_reference_bins'])
    if reference.empty:return {'unit':identity,'excluded':'insufficient training reference'}
    reference=reference.iloc[0];baseline=float(reference.baseline_kmh)
    rules=EventRules(config['congestion_ratio'],config['recovery_ratio'],config['onset_bins'],config['recovery_bins'])
    events=build_events(bins,baseline,start=dates['reference_end'],end=dates['observation_end'],rules=rules)
    if len(events):
        events['reference_fit_end']=dates['reference_end']
        events['split_proposal'],events['outcome_maturity_at']=availability_safe_splits(
            events,dates['validation_start'],dates['test_start'],dates['observation_end'])
        assert not (events.label_15m.eq(1)&events.label_30m.eq(0)).any()
        assert not (events.label_30m.eq(1)&events.label_60m.eq(0)).any()
        if len(events)>1:assert events.prediction_time.sort_values().diff().dropna().ge(pd.Timedelta(minutes=60)).all()
    unit_id=__import__('hashlib').sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    target=root/'processed/units'/unit_id;target.mkdir(parents=True,exist_ok=True)
    bins.to_parquet(target/'bins.parquet',index=False,compression='zstd')
    events.to_parquet(target/'events.parquet',index=False,compression='zstd')
    sensitivity=[]
    history=bins.loc[bins.timestamp<dates['sensitivity_end']]
    for low in config['sensitivity_congestion']:
        for high in config['sensitivity_recovery']:
            candidate=EventRules(low,high,rules.onset_bins,rules.recovery_bins)
            measured=build_events(history,baseline,start=dates['reference_end'],end=dates['sensitivity_end'],rules=candidate)
            sensitivity.append({'congestion':low,'recovery':high,**label_summary(measured)})
    result={'unit':identity,'reference':reference.to_dict(),'events':len(events),'directory':str(target),'sensitivity':sensitivity}
    write_json(target/'manifest.json',result)
    print('LABEL_UNIT',identity['detector_id'],identity['lane_id'],len(events),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--wait',action='store_true');args=parser.parse_args();root=args.root
    status=root/'preparation_status.json'
    while not status.exists():
        if not args.wait:raise RuntimeError('Ingestion and quality must finish first')
        time.sleep(15)
    if json.loads(status.read_text(encoding='utf-8'))['status']!='ingestion_and_quality_complete':raise ValueError('Preparation not complete')
    config_path=Path(__file__).parents[1]/'configs/long_window.json';config=json.loads(config_path.read_text(encoding='utf-8'))
    cohort=pd.read_csv(root/'reports/cohort_selection.csv',dtype={s:str for s in UNIT})
    identities=cohort[UNIT].to_dict('records')
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(label_unit,[(str(root),r,config) for r in identities]))
    included=[r for r in results if 'excluded' not in r]
    if not included:raise ValueError('No unit has a sufficient historical reference')
    pd.DataFrame([r for r in results if 'excluded' in r]).to_csv(root/'reports/excluded_reference_units.csv',index=False)
    reference=pd.DataFrame([r['reference'] for r in included]);reference.to_csv(root/'reports/cohort.csv',index=False)
    frames=[pd.read_parquet(Path(r['directory'])/'events.parquet') for r in included if r['events']]
    if not frames:raise ValueError('No witnessed episodes; never substitute synthetic events')
    events=pd.concat(frames,ignore_index=True).sort_values('prediction_time').reset_index(drop=True)
    output=root/'processed/derived';events.to_parquet(output/'events.parquet',index=False,compression='zstd')
    events.to_csv(root/'reports/events_review.csv',index=False)
    writer=None
    try:
        for r in included:
            table=pq.read_table(Path(r['directory'])/'bins.parquet')
            if writer is None:writer=pq.ParquetWriter(output/'cohort_bins.parquet',table.schema,compression='zstd')
            writer.write_table(table.cast(writer.schema))
    finally:
        if writer:writer.close()
    sensitivity=[]
    for i in range(9):
        records=[r['sensitivity'][i] for r in included]
        combined={'congestion':records[0]['congestion'],'recovery':records[0]['recovery'],
                  'events':sum(r['events'] for r in records),'horizons':{}}
        for h in ['15','30','60']:
            combined['horizons'][h]={k:sum(r['horizons'][h][k] for r in records) for k in ['positive','negative','unknown']}
        sensitivity.append(combined)
    write_json(root/'reports/training_only_threshold_sensitivity.json',{'window':[config['reference_end'],config['sensitivity_end']],
        'purpose':'Descriptive rule sensitivity on training-period history only; no test threshold tuning','results':sensitivity})
    profile=pd.read_parquet(output/'coverage_lane_day.parquet')
    start,end=pd.Timestamp(config['observation_start']).tz_convert('Asia/Hong_Kong'),pd.Timestamp(config['observation_end']).tz_convert('Asia/Hong_Kong')
    period=profile_period(profile,start,end);period.to_csv(root/'reports/coverage_lane_period.csv',index=False)
    profile.to_csv(root/'reports/coverage_lane_day.csv',index=False)
    monthly=profile.assign(month=profile.day.dt.strftime('%Y-%m')).groupby(['detector_id','direction','month'],observed=True).agg(
        lane_days=('day','size'),valid_slots=('valid_slots','sum'),expected_slots=('expected_slots','sum'),
        usable_5m_bins=('usable_5m_bins','sum'),conflict_slots=('conflict_slots','sum'),offline_slots=('offline_slots','sum')).reset_index()
    monthly['valid_30s_coverage']=monthly.valid_slots/monthly.expected_slots
    monthly['usable_5m_coverage']=monthly.usable_5m_bins/(monthly.lane_days*288)
    monthly.to_csv(root/'reports/coverage_detector_month.csv',index=False)
    stats={'status':'complete_data_only_handoff','provisional':True,'window':[config['observation_start'],config['observation_end']],
           'evaluation_start_after_reference':config['reference_end'],'days':int(profile.day.nunique()),
           'ingestion':json.loads(status.read_text(encoding='utf-8')),'selected_units':len(included),'selected_detectors':int(reference.detector_id.nunique()),
           'labels':label_summary(events),'splits':{k:label_summary(v) for k,v in events.groupby('split_proposal')},
           'total_conflict_slots_all_observed_cohort_lanes':int(profile.conflict_slots.sum()),
           'rules':asdict(EventRules(config['congestion_ratio'],config['recovery_ratio'],config['onset_bins'],config['recovery_bins'])),
           'label_time':'Observed sustained recovery confirmation relative to archive prediction time; not exact physical recovery',
           'availability':'Bin end +10min closure; late captures excluded before feature deduplication',
           'split_outcome_maturity':'Additional conservative training/validation purge: max(prediction+70m, episode separation+10m) must precede next fit boundary',
           'fit_policy':'Cohort Jan 1–7 2023 only; reference Jan 2023 only; no future screening',
           'sensitivity_window':[config['reference_end'],config['sensitivity_end']],
           'limitations':['Provisional thresholds; team review required','At most 24 lane units; not all Hong Kong roads',
              'Same identifier across years does not prove hardware/lane geometry stability','Fixed 2023 reference can drift; review monthly coverage and future-period censoring',
              'Sparse five-minute usable bins are not full 30-second coverage','Network/spatial features, external context and all ML remain with other members'],
           'completed_at_utc':datetime.now(timezone.utc).isoformat()}
    # Plot only six review episodes; avoid loading 45 months of all-lane bins into memory.
    chosen=[]
    for val in [1,0,None]:
        mask=events.label_60m.isna() if val is None else events.label_60m.eq(val)
        chosen.extend(events.loc[mask].head(2).index)
    snippets=[]
    for i in chosen:
        event=events.loc[i];filters=[(k,'==',event[k]) for k in UNIT]+[
            ('timestamp','>=',event.onset_time-pd.Timedelta(minutes=45)),
            ('timestamp','<=',event.prediction_time+pd.Timedelta(minutes=90))]
        snippets.append(pd.read_parquet(output/'cohort_bins.parquet',filters=filters))
    stats['figures']=plot_events(events,pd.concat(snippets,ignore_index=True).drop_duplicates(UNIT+['timestamp']),root/'reports/event_figures')
    write_json(root/'reports/summary.json',stats)
    provenance={'config':config,'config_sha256':sha256_file(config_path),'python':platform.python_version(),
        'uv_lock_sha256':sha256_file(Path(__file__).parents[1]/'uv.lock'),
        'source_code_sha256':{str(p.relative_to(Path(__file__).parents[1])):sha256_file(p) for p in sorted((Path(__file__).parents[1]/'src').rglob('*.py'))},
        'source_inventory':'../download_manifest.json','ingestion':'../processed/ingest.json',
        'outputs':{p.name:{'bytes':p.stat().st_size,'sha256':sha256_file(p)} for p in [output/'events.parquet',output/'cohort_bins.parquet',output/'coverage_lane_day.parquet']}}
    write_json(root/'reports/handoff_manifest.json',provenance)
    write_json(root/'completion.json',{'status':'complete','completed_at_utc':stats['completed_at_utc'],
        'data_only':True,'no_model_training':True,'no_github_push_or_merge_request':True,'summary':'reports/summary.json'})
    print('COMPLETE_DATA_ONLY_HANDOFF',len(events),flush=True)


if __name__=='__main__':main()
