"""Download authentic official pilot inputs; do not fabricate or label observations."""
from pathlib import Path
from datetime import date, timedelta, datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse,json, zipfile, xml.etree.ElementTree as ET
from traffic_recovery.data.http import EvidenceClient, sha256_file
from traffic_recovery.data.sources import RAW, RESOURCES, archive_url, list_versions

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,required=True)
ROOT=parser.parse_args().root
ROOT.mkdir(exist_ok=True)

def acquire(day):
    token=day.strftime('%Y%m%d')
    client=EvidenceClient(ROOT/'raw' /token, timeout=120, reuse=True)
    listing=list_versions(client, RAW, day, day, 'versions.json')
    archive=client.fetch(archive_url('get-file',url=RAW,time=token),'raw_'+token+'.zip')
    with zipfile.ZipFile(archive) as z:
        xml=sorted(n for n in z.namelist() if n.endswith('.xml'))
        if sorted(Path(n).name[:13] for n in xml)!=sorted(listing['timestamps']):
            raise ValueError('Archive members differ from daily listing: '+token)
        # Parse boundary files to check the response really contains traffic XML.
        for n in {xml[0],xml[-1]}: ET.fromstring(z.read(n))
    print('Downloaded and checked', token,len(xml),'snapshots',archive.stat().st_size,'bytes',flush=True)
    return {'capture_day':day.isoformat(),'archive':str(archive.relative_to(ROOT)),'sha256':sha256_file(archive),'bytes':archive.stat().st_size,'snapshots':len(xml),'check':'ZIP directory matches daily listing; first/last XML parsed; full row/coverage audit pending'}

days=[date(2026,10,7)+timedelta(days=i) for i in range(15)]
results=[];errors=[]
with ThreadPoolExecutor(max_workers=3) as pool:
    jobs={pool.submit(acquire,day):day for day in days}
    for future in as_completed(jobs):
        try:results.append(future.result())
        except Exception as e:
            errors.append({'day':jobs[future].isoformat(),'error':str(e)})
            print('FAILED',jobs[future],str(e),flush=True)
        (ROOT/'download_manifest.json').write_text(json.dumps({'checked_at_utc':datetime.now(timezone.utc).isoformat(),'source':RAW,'scope':'2026-10-07 to 2026-10-21 inclusive archive capture days; not the full 2023-2026 study','records':sorted(results,key=lambda x:x['capture_day']),'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
client=EvidenceClient(ROOT/'metadata',timeout=120,reuse=True)
for name in ['detectors.csv','traffic_spec.pdf','raw_schema.xsd']:
    p=client.fetch(RESOURCES[name],name);print('Metadata',name,p.stat().st_size,flush=True)
readme='''# 香港交通恢复项目：官方原始试验数据

数据来源：香港运输署 Traffic Data of Strategic / Major Roads。
https://data.gov.hk/en-data/dataset/hk-td-sm_4-traffic-data-strategic-major-roads

范围：2026年10月7日至21日（15个档案捕获日期），用于仓库现有14日观测窗口及边界记录。不是2023–2026全部数据。
raw/ 含逐日原始ZIP、当天版本列表、HTTP状态/响应元数据及校验值；metadata/ 含检测器位置、官方字段说明和XML架构。
ZIP保持原样。文件名日期是档案捕获日期，分析时必须用XML内部观测时间，并考虑可获取时间。
download_manifest.json记录实际下载、快照数量、大小、SHA-256和失败信息。下载/边界XML检查不等于完成全量解析、数据质量或连续覆盖验证。
后续：流式解析与去重、覆盖检查、建立仅依赖历史数据的参考、构建事件及标签、按时间分组并隔离窗口，再运行本地特征基础模型。
本目录不包含模型结果，也不应将缺失观测当作0。
'''
(ROOT/'README.md').write_text(readme,encoding='utf-8')
print('FINISHED',len(results),'days',sum(x['bytes'] for x in results),'bytes','errors',len(errors),flush=True)
if errors:raise SystemExit(1)
