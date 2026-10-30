"""Historical-only cohort selection, full-window ingestion and bounded day quality.

No models, external adapters, or network work. All scientific choices provisional.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import logging
import time
import zipfile
from collections import Counter
import xml.etree.ElementTree as ET
import ast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traffic_recovery.data.long_window import parse_rows, compact_rows, COMPACT_COLUMNS
from traffic_recovery.data.coverage import deduplicate, make_bins, profile_day
from traffic_recovery.data.events import UNIT
from traffic_recovery.data.http import sha256_file
from traffic_recovery.data.pilot import select_cohort
from traffic_recovery.data.traffic import SchemaError

VERSION = 'long-window-batch-v1'


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    tmp.replace(path)


def ingest_job(job):
    archive, day, destination, ids, source_sha, implementation_sha = job
    archive,destination=Path(archive),Path(destination)
    stamp = destination.with_suffix('.json')
    identity={'version':VERSION,'day':day,'source_sha256':source_sha,'detector_ids':ids,
              'implementation_sha256':implementation_sha}
    if stamp.exists():
        prior=json.loads(stamp.read_text(encoding='utf-8'))
        if sha256_file(destination)!=prior['sha256']:
            raise ValueError('Corrupt ingestion checkpoint: '+str(destination))
        if prior['identity'] != identity:
            # An earlier verified run predated ZIP duplicate-name support. Its
            # unique-name archives are equivalent; preserve its generation identity.
            previous=list((destination.parents[2]/'provenance').glob('prepare_long_window_before_*.py'))
            old=prior['identity'];old_impl=old.get('implementation_sha256',{})
            same=all(old.get(k)==identity[k] for k in ['version','day','source_sha256','detector_ids'])
            same &= old_impl.get('long_window.py')==implementation_sha['long_window.py']
            generation=[p for p in previous if sha256_file(p)==old_impl.get('prepare_long_window.py')]
            same &= bool(generation)
            def transform_ast(path):
                module=ast.parse(path.read_text(encoding='utf-8'))
                function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='ingest_job')
                index=next(i for i,n in enumerate(function.body) if isinstance(n,ast.Expr) and ast.unparse(n).startswith('destination.parent.mkdir('))
                return ast.dump(ast.Module(body=function.body[index:],type_ignores=[]),include_attributes=False)
            unchanged_transform=bool(generation) and transform_ast(generation[0])==transform_ast(Path(__file__))
            if not unchanged_transform:
                with zipfile.ZipFile(archive) as z:
                    same &= len(z.namelist())==len(set(z.namelist()))
            if not same:raise ValueError('Stale ingestion checkpoint: '+str(destination))
            save(destination.with_suffix('.compatibility.json'),{'generation_identity_preserved':old,
                'current_identity':identity,'verified':'Same immutable source/adapter; unchanged ingestion transform AST, or verified unique-name legacy archive. Original generation identity is preserved.',
                'output_sha256':prior['sha256']})
        return prior
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.partial')
    writer=None
    count=source_rows=0
    quarantined=[]
    start=end=None
    fields={'source_offline_rows':0,'unknown_validity_rows':0,'conflicting_keys_quarantined':0}
    with zipfile.ZipFile(archive) as bundle:
        entries=list(enumerate(bundle.infolist()))
        names=sorted([(i,n) for i,n in entries if Path(n.filename).name.startswith(day+'-') and n.filename.endswith('.xml')],key=lambda x:(x[1].filename,x[0]))
        if not names: raise ValueError('No capture snapshots for '+day)
        counts=Counter(n.filename for _,n in names)
        batch=[]
        try:
            for index, (entry_index, info) in enumerate(names):
                # read() validates the original ZIP member CRC, before filtering.
                name=info.filename
                provenance=name if counts[name]==1 else name+f'#zip_entry={entry_index}'
                payload=bundle.read(info)
                try:
                    batch.extend(parse_rows(payload,provenance,set(ids) if ids else None))
                except (ET.ParseError,SchemaError,ValueError) as exc:
                    # Retain bytes in the unchanged ZIP; do not repair truncated
                    # XML or fabricate rows. Exclusion affects coverage/labels.
                    original_error=None
                    try: ET.fromstring(payload)
                    except ET.ParseError as raw_error: original_error=str(raw_error)
                    if isinstance(exc,ET.ParseError) and original_error is None:
                        raise RuntimeError('Filtered XML failed but original parses; adapter bug') from exc
                    quarantined.append({'source_file':provenance,'zip_entry_index':entry_index,
                        'sha256':__import__('hashlib').sha256(payload).hexdigest(),
                        'bytes':len(payload),'reason':f'{type(exc).__name__}: {exc}',
                        'original_xml_parse_error':original_error})
                if (index+1)%64==0 or index+1==len(names):
                    frame, quality=compact_rows(batch)
                    source_rows+=len(batch)
                    batch=[]
                    for key in fields: fields[key]+=quality.get(key,0)
                    if not len(frame): continue
                    for key in UNIT+['valid','signature','source_file']: frame[key]=frame[key].astype(str)
                    for key in ['speed_kmh','volume_count','occupancy_pct','speed_sd_kmh']:
                        frame[key]=pd.to_numeric(frame[key],errors='coerce').astype('float64')
                    arrow=pa.Table.from_pandas(frame,preserve_index=False)
                    if writer is None: writer=pq.ParquetWriter(temporary,arrow.schema,compression='zstd')
                    writer.write_table(arrow.cast(writer.schema))
                    count+=len(frame)
                    start=frame.timestamp.min() if start is None else min(start,frame.timestamp.min())
                    end=frame.timestamp.max() if end is None else max(end,frame.timestamp.max())
        finally:
            if writer is not None: writer.close()
    if writer is None:
        # A historical cohort can later disappear. Empty is preserved, never fabricated.
        schema=pa.schema([(s,pa.string()) for s in UNIT]+[('timestamp',pa.timestamp('ns',tz='Asia/Hong_Kong'))]+
                        [(s,pa.float64()) for s in ['speed_kmh','volume_count','occupancy_pct','speed_sd_kmh']]+
                        [('valid',pa.string()),('conflict',pa.bool_()),('signature',pa.string()),
                         ('available_at',pa.timestamp('ns',tz='Asia/Hong_Kong')),('source_file',pa.string())])
        pq.write_table(pa.Table.from_batches([],schema=schema),temporary)
    temporary.replace(destination)
    record={'identity':identity,'source':str(archive),'source_rows':source_rows,'rows':count,'snapshots':len(names),
            'min_timestamp':str(start) if start is not None else None,'max_timestamp':str(end) if end is not None else None,
            'quarantined_snapshots':quarantined,'parsed_snapshots':len(names)-len(quarantined),
            'batch_quality_counts_not_global_unique':fields,'sha256':sha256_file(destination),'bytes':destination.stat().st_size}
    save(stamp,record)
    print('INGEST',day,source_rows,count,flush=True)
    return record


def profile_job(job):
    day, paths, output, ids = job
    output=Path(output); token=day.strftime('%Y%m%d')
    bins_path=output/f'bins-{token}.parquet'; profile_path=output/f'profile-{token}.parquet'
    clean_path=output/f'cleaned-{token}.parquet'
    checkpoint=output/f'quality-{token}.json'
    identity={'version':VERSION,'day':str(day),'ids':ids,
              'sources':{str(p):sha256_file(Path(p)) for p in paths},
              'quality_code':{name:sha256_file(Path(__file__).parents[1]/'src/traffic_recovery/data'/name)
                              for name in ['coverage.py','long_window.py']}}
    if checkpoint.exists():
        old=json.loads(checkpoint.read_text(encoding='utf-8'))
        if old['identity']!=identity or any(sha256_file(p)!=old['outputs'][p.name] for p in [bins_path,profile_path,clean_path]):
            raise ValueError('Corrupt quality checkpoint')
        return str(profile_path)
    output.mkdir(parents=True,exist_ok=True)
    summaries=[]; writer=None; clean_writer=None; tmp=bins_path.with_suffix('.partial'); clean_tmp=clean_path.with_suffix('.partial')
    if ids is None:
        all_ids=set()
        for path in paths:
            all_ids.update(pq.read_table(path,columns=['detector_id']).column(0).unique().to_pylist())
        ids=sorted(all_ids)
    if not paths:
        ids=[]  # Complete-day outage: publish typed empty tables and zero coverage.
    try:
        for offset in range(0,len(ids),12):
            filters=[('timestamp','>',day),('timestamp','<=',day+pd.Timedelta(days=1)),('detector_id','in',ids[offset:offset+12])]
            frame=pq.read_table(paths,filters=filters).to_pandas()
            if frame.empty: continue
            feature=frame.loc[frame.available_at <= frame.timestamp.dt.ceil('5min')+pd.Timedelta(minutes=10)]
            binned=make_bins(deduplicate(feature))
            unique=deduplicate(frame)
            unique.loc[unique.conflict,['occupancy_pct','speed_sd_kmh']]=float('nan')
            for key in UNIT+['valid','signature','source_file']: unique[key]=unique[key].astype(str)
            clean_arrow=pa.Table.from_pandas(unique,preserve_index=False)
            if clean_writer is None: clean_writer=pq.ParquetWriter(clean_tmp,clean_arrow.schema,compression='zstd')
            clean_writer.write_table(clean_arrow.cast(clean_writer.schema))
            summary=profile_day(unique,day)
            stats=binned.groupby(UNIT,observed=True).agg(valid_5m_bins=('valid_slots',lambda s:s.ge(2).sum()),
                                                       usable_5m_bins=('usable','sum')).reset_index()
            summaries.append(summary.merge(stats,on=UNIT,how='left'))
            for key in UNIT: binned[key]=binned[key].astype(str)
            arrow=pa.Table.from_pandas(binned,preserve_index=False)
            if writer is None: writer=pq.ParquetWriter(tmp,arrow.schema,compression='zstd')
            writer.write_table(arrow.cast(writer.schema))
    finally:
        if writer is not None: writer.close()
        if clean_writer is not None: clean_writer.close()
    if writer is None:
        # A complete-day outage contributes zero coverage, not invented rows.
        tz='Asia/Hong_Kong'
        schema=pa.schema([(s,pa.string()) for s in UNIT]+[('timestamp',pa.timestamp('ns',tz=tz)),
            ('present_slots',pa.int64()),('valid_slots',pa.int64()),('flow_slots',pa.int64()),('speed_kmh',pa.float64()),
            ('last_source_available_at',pa.timestamp('ns',tz=tz)),('offline_slots',pa.int64()),('conflict_slots',pa.int64()),
            ('repeat_rows',pa.int64()),('available_at',pa.timestamp('ns',tz=tz)),('usable',pa.bool_())])
        pq.write_table(pa.Table.from_batches([],schema=schema),tmp)
        clean_schema=pa.schema([(s,pa.string()) for s in UNIT]+[('timestamp',pa.timestamp('ns',tz=tz))]+
            [(s,pa.float64()) for s in ['speed_kmh','volume_count','occupancy_pct','speed_sd_kmh']]+
            [('valid',pa.string()),('conflict',pa.bool_()),('signature',pa.string()),('available_at',pa.timestamp('ns',tz=tz)),
             ('source_file',pa.string()),('repeat_rows',pa.int64())])
        pq.write_table(pa.Table.from_batches([],schema=clean_schema),clean_tmp)
    tmp.replace(bins_path)
    clean_tmp.replace(clean_path)
    profile=pd.concat(summaries,ignore_index=True) if summaries else pd.DataFrame(columns=UNIT+[
        'day','present_slots','valid_slots','offline_slots','conflict_slots','repeat_rows','first_present','last_present',
        'first_valid','last_valid','max_absent_gap_seconds','max_invalid_or_absent_gap_seconds','valid_5m_bins','usable_5m_bins'])
    profile.to_parquet(profile_path,index=False,compression='zstd')
    save(checkpoint,{'identity':identity,'outputs':{p.name:sha256_file(p) for p in [bins_path,profile_path,clean_path]}})
    print('QUALITY',token,len(profile),flush=True)
    return str(profile_path)


def profiles(root, source, output, start, end, ids, workers):
    """Choose capture partitions by verified observed timestamp bounds, not filename guesses."""
    start=start.tz_convert('Asia/Hong_Kong').as_unit('ns');end=end.tz_convert('Asia/Hong_Kong').as_unit('ns')
    paths=sorted(source.glob('*.parquet'))
    bounds=[]
    for p in paths:
        r=json.loads(p.with_suffix('.json').read_text(encoding='utf-8'))
        if r['min_timestamp'] is not None:
            bounds.append((p,pd.Timestamp(r['min_timestamp']),pd.Timestamp(r['max_timestamp'])))
    jobs=[]
    for day in pd.date_range(start,end,freq='D',inclusive='left'):
        selected=[str(p) for p,a,b in bounds if b>day and a<=day+pd.Timedelta(days=1)]
        jobs.append((day,selected,str(output),ids))
    measured=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(profile_job,jobs): measured.append(pd.read_parquet(result))
    profile=pd.concat(measured,ignore_index=True)
    inventory=profile[UNIT].drop_duplicates()
    days=pd.DataFrame({'day':pd.date_range(start,end,freq='D',inclusive='left')})
    profile=inventory.merge(days,how='cross').merge(profile,on=UNIT+['day'],how='left')
    for col in ['present_slots','valid_slots','offline_slots','conflict_slots','repeat_rows','valid_5m_bins','usable_5m_bins']:
        profile[col]=profile[col].fillna(0).astype(int)
    for col in ['max_absent_gap_seconds','max_invalid_or_absent_gap_seconds']: profile[col]=profile[col].fillna(86400).astype(int)
    for col in ['first_present','last_present','first_valid','last_valid']:
        profile[col]=pd.to_datetime(profile[col],utc=True).dt.tz_convert('Asia/Hong_Kong')
    profile['expected_slots']=2880
    profile['valid_coverage']=profile.valid_slots/2880
    profile['valid_5m_coverage']=profile.valid_5m_bins/288
    profile['usable_5m_coverage']=profile.usable_5m_bins/288
    profile.to_parquet(output/'coverage_lane_day.parquet',index=False,compression='zstd')
    return profile


def wait_archive(root,month):
    check=root/'raw'/month/'archive_check.json'
    while not check.exists():
        manifest=root/'download_manifest.json'
        if manifest.exists():
            failures=json.loads(manifest.read_text(encoding='utf-8')).get('errors',[])
            if any(r['month']==month for r in failures): raise RuntimeError('Download failed for '+month)
        print('WAIT_ARCHIVE',month,flush=True); time.sleep(15)
    record=json.loads(check.read_text(encoding='utf-8'))
    archive=root/record['path']
    if sha256_file(archive)!=record['sha256']: raise ValueError('Archive changed since acquisition: '+month)
    return archive,record['sha256']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path);p.add_argument('--workers',type=int,default=8)
    a=p.parse_args();root=a.root
    config=json.loads((Path(__file__).parents[1]/'configs/long_window.json').read_text(encoding='utf-8'))
    implementation={str(p.name):sha256_file(p) for p in [Path(__file__),Path(__file__).parents[1]/'src/traffic_recovery/data/long_window.py']}
    first,first_hash=wait_archive(root,'202301')
    selection=root/'selection/lane_snapshots'
    with ProcessPoolExecutor(max_workers=min(a.workers,2)) as pool:
        jobs=[(str(first),f'202301{d:02d}',str(selection/f'202301{d:02d}.parquet'),None,first_hash,implementation) for d in range(1,9)]
        list(pool.map(ingest_job,jobs))
    profile=profiles(root,selection,root/'selection/derived',pd.Timestamp(config['observation_start']),pd.Timestamp(config['selection_end']),None,min(a.workers,4))
    cohort,comparison=select_cohort(profile,pd.Timestamp(config['selection_end']),config)
    (root/'reports').mkdir(exist_ok=True)
    comparison.to_csv(root/'reports/selection_filter_comparison.csv',index=False)
    if cohort.empty: raise RuntimeError('No historical cohort meets existing filters; no silent relaxation')
    cohort.to_csv(root/'reports/cohort_selection.csv',index=False)
    ids=sorted(cohort.detector_id.unique())
    save(root/'cohort_scope.json',{'selection_window':[config['observation_start'],config['selection_end']],
        'selection':'All detector/lane identities observed in Jan 1–7 2023; coverage filters only; one lane per detector/direction; existing cap 24; no future/test selection',
        'detector_ids':ids,'selected_units':cohort[UNIT].to_dict('records'),'provisional':True})
    print('COHORT',len(ids),len(cohort),flush=True)
    records=[]
    # Dispatch completed months immediately; the next month can still be downloading.
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for month in [f'{y}{m:02d}' for y in range(2023,2027) for m in range(1,13) if (y,m)<=(2026,9)]:
            archive,source_sha=wait_archive(root,month)
            with zipfile.ZipFile(archive) as z:
                days=sorted({Path(n).name[:8] for n in z.namelist() if n.endswith('.xml')})
            jobs=[(str(archive),day,str(root/'processed/lane_snapshots'/
                (f'{day}.parquet' if day[:6]==month else f'{day}-from-{month}.parquet')),ids,source_sha,implementation) for day in days]
            for record in pool.map(ingest_job,jobs): records.append(record)
            save(root/'processed/ingest.json',records)
    # Boundary archive is acquired separately, so Sep 30 closure is observable.
    archive,source_sha=wait_archive(root,'20261001-boundary')
    boundary=ingest_job((str(archive),'20261001',str(root/'processed/lane_snapshots/20261001.parquet'),ids,source_sha,implementation))
    records.append(boundary);save(root/'processed/ingest.json',records)
    profile=profiles(root,root/'processed/lane_snapshots',root/'processed/derived',pd.Timestamp(config['observation_start']),pd.Timestamp(config['observation_end']),ids,a.workers)
    save(root/'preparation_status.json',{'status':'ingestion_and_quality_complete','source_rows':sum(r['source_rows'] for r in records),
        'compact_rows':sum(r['rows'] for r in records),'days':int(profile.day.nunique()),'lane_units':len(profile[UNIT].drop_duplicates()),
        'updated_at_utc':datetime.now(timezone.utc).isoformat(),'next':'Build provisional recovery events and handoff; no ML'})
    print('INGESTION_AND_QUALITY_COMPLETE',flush=True)


if __name__=='__main__': main()
