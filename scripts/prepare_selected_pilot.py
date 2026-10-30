"""Bounded convenience-cohort ingestion using unchanged repository cleaning rules.

Select detectors before parsing observations, never by recovery outcomes. Original
ZIPs remain authoritative; this is an exploratory subset, not a full-inventory run.
"""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse,json,logging,hashlib,xml.etree.ElementTree as ET
import pandas as pd
from traffic_recovery.data import pilot_ingest as ingest
from traffic_recovery.data.http import sha256_file
ORIGINAL_COMPACT = ingest.compact_snapshot

def selected_payload(payload: bytes, ids: set[str]) -> bytes:
    root=ET.fromstring(payload)
    for detectors in root.findall('./periods/period/detectors'):
        detectors[:]=[d for d in detectors if d.findtext('detector_id') in ids]
    return ET.tostring(root,encoding='utf-8')

def work(job):
    directory,output,ids=job
    directory=Path(directory);output=Path(output);token=directory.name
    ingest.compact_snapshot=lambda payload,member:ORIGINAL_COMPACT(selected_payload(payload,set(ids)),member)
    ingest.VERSION='selected-detectors-v1-'+hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:12]
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    record=ingest.ingest_day(directory/f'raw_{token}.zip',output/'lane_snapshots'/f'{token}.parquet',json.loads((directory/'versions.json').read_text()))
    record['selected_detector_ids']=ids
    return record

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--count',type=int,default=40);p.add_argument('--workers',type=int,default=3);a=p.parse_args()
    metadata=a.root/'metadata/detectors.csv';frame=pd.read_csv(metadata,dtype=str)
    column='Device_ID' if 'Device_ID' in frame else frame.columns[0]
    ids=sorted(frame[column].dropna().unique())[:a.count]
    out=a.root/f'processed-{a.count}';out.mkdir(exist_ok=True)
    (out/'cohort_scope.json').write_text(json.dumps({'scope':'Exploratory first IDs in current metadata, not representative or outcome-selected','detector_ids':ids,'metadata_sha256':sha256_file(metadata),'script_sha256':sha256_file(Path(__file__))},indent=2),encoding='utf-8')
    jobs=[(str(d),str(out),ids) for d in sorted((a.root/'raw').iterdir()) if d.is_dir()]
    records=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(work,j) for j in jobs]
        for f in as_completed(futures):
            r=f.result();records.append(r)
            (out/'ingest.json').write_text(json.dumps(sorted(records,key=lambda x:x['source']),indent=2),encoding='utf-8')
            print('COMPLETED',Path(r['source']).name,r['rows'],'rows',flush=True)
    print('FINISHED',len(records),sum(r['rows'] for r in records),'rows',flush=True)

if __name__=='__main__':main()
