"""Run unchanged pilot rules on the explicitly recorded convenience cohort."""
import argparse,json
from pathlib import Path
import pandas as pd
from traffic_recovery.data import pilot
from traffic_recovery.data.bounded_coverage import run_bounded

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--count',type=int,default=40);a=p.parse_args()
    source=a.root/f'processed-{a.count}';scope=json.loads((source/'cohort_scope.json').read_text())
    # Restrict coverage inventory as well as ingestion; thresholds are unchanged.
    ids=scope['detector_ids']
    pilot.run_bounded=lambda src,dst,start,end:run_bounded(src,dst,start,end,detectors=ids)
    args=argparse.Namespace(config=Path('configs/pilot.json'),input=source,output=source/'derived',report=a.root/f'reports/pilot-{a.count}',reuse_coverage=True)
    result=pilot.run(args)
    result['convenience_cohort']=scope
    (args.report/'desktop_scope.json').write_text(json.dumps(scope,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2,default=str),flush=True)

if __name__=='__main__':main()
