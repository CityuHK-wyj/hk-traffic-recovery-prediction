"""Wait for data completion, verify, execute review notebook and package local changes."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,contextlib,hashlib,io,json,os,re,subprocess,sys,time,zipfile
import pandas as pd


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    root=args.root.resolve();project=Path(__file__).parents[1]
    while not (root/'completion.json').exists():time.sleep(15)
    with (root/'verification.log').open('w',encoding='utf-8') as log:
        subprocess.run([sys.executable,str(project/'scripts/verify_long_window.py'),'--root',str(root)],cwd=project,stdout=log,stderr=subprocess.STDOUT,check=True)
    summary=json.loads((root/'reports/summary.json').read_text(encoding='utf-8'))
    validation=json.loads((root/'reports/validation.json').read_text(encoding='utf-8'))
    downloads=json.loads((root/'download_manifest.json').read_text(encoding='utf-8'))
    ingestion=json.loads((root/'processed/ingest.json').read_text(encoding='utf-8'))
    bad=[]
    for item in ingestion:
        for excluded in item.get('quarantined_snapshots',[]):
            bad.append({'capture_day':item['identity']['day'],'source_zip':item['source'],**excluded})
    pd.DataFrame(bad).to_csv(root/'reports/source_snapshot_exclusions.csv',index=False)
    anomalies=[]
    for item in downloads['records']:
        check=json.loads((root/item['path']).parent.joinpath('archive_check.json').read_text(encoding='utf-8'))
        anomalies.append({'month':item['month'],'snapshots':item['snapshots'],
            'duplicate_name_extra_entries':check.get('duplicate_name_extra_entries',0),
            'out_of_month_entries':len(check.get('out_of_month_capture_entries',[]))})
    pd.DataFrame(anomalies).to_csv(root/'reports/archive_anomalies.csv',index=False)
    test_log=(root/'tests.log').read_text(encoding='utf-8',errors='replace');passed=re.findall(r'(\d+) passed',test_log)
    label_lines=['| 预测范围 | 已恢复 | 未恢复 | 未知/被截断 |','|---|---:|---:|---:|']
    for h in ['15','30','60']:
        row=summary['labels']['horizons'][h]
        label_lines.append(f'| {h}分钟 | {row["positive"]:,} | {row["negative"]:,} | {row["unknown"]:,} |')
    split_lines=['| 时间分组（暂定） | 事件数 |','|---|---:|']
    split_lines += [f'| {k} | {v["events"]:,} |' for k,v in summary['splits'].items()]
    text=f'''# 香港交通恢复预测：长窗口数据交接

本目录仅完成成员1的数据获取、清洗、质量检查及暂定恢复标签；本次未上传GitHub、未申请合并、未训练模型。

观测范围为2023年1月1日至2026年9月30日，共{summary['days']:,}天。45个月官方原始ZIP全部保留，共{sum(r['bytes'] for r in downloads['records']):,}字节，包含{sum(r['snapshots'] for r in downloads['records']):,}个XML条目。另保留2026年10月1日的边界档案。ZIP不全量解压，避免将约902GB的XML展开到磁盘。

分析队列由2023年1月1日至7日的全站历史覆盖选出，最终保留{summary['selected_detectors']}个检测器、{summary['selected_units']}个车道单位。后续摄取这些检测器的所有车道。摄取前的所选队列原始行数为{summary['ingestion']['source_rows']:,}，逐日去重及冲突隔离后保留{int(validation['cleaned_lane_observations']['rows']):,}条车道观测。它们不是独立事件，也不代表全香港道路。完整路网原始数据仍在raw中，可供其他成员扩展空间范围。

共生成{summary['labels']['events']:,}个可见拥堵起点事件。标签表示预测时刻之后是否观察到持续恢复确认，阈值仍待小组确认；不是精确物理恢复时间，也不证明事件由事故引起。

{chr(10).join(label_lines)}

{chr(10).join(split_lines)}

站点选择只使用2023年初数据；历史速度参考只使用2023年1月。训练事件从2023年2月开始，训练至2024年底，2025年验证，2026年1至9月测试。跨边界及事件重叠按已有规则隔离；unknown不当作负例。阈值敏感性只在2023年2至4月训练历史中统计。

官方档案共发现{sum(r['duplicate_name_extra_entries'] for r in anomalies)}个重名额外条目、{sum(r['out_of_month_entries'] for r in anomalies)}个跨月条目，均保留并据实处理。所选队列处理排除了{len(bad)}个结构/时间不合格的源快照，原因及原ZIP内位置见reports/source_snapshot_exclusions.csv。全日缺失保留为空，不补成零；数值冲突、停用观测均屏蔽测量值。设备与车道身份跨年是否稳定、长期参考速度漂移和稀疏分箱限制仍需在实验报告中讨论。

检查结果：{passed[-1] if passed else '见tests.log'}项离线测试通过；真实数据最终校验{validation['status']}。检验包括档案与快照计数对账、输出校验值、事件唯一性、标签取值、缺失日分区和冲突/停用数值屏蔽。测试中的合成数据仅验证程序，不作为研究样本。

## 直接使用

- processed/derived/events.parquet：事件、15/30/60分钟标签及暂定时间分组。
- processed/derived/cohort_bins.parquet：所选车道的五分钟速度序列。
- processed/derived/cleaned-YYYYMMDD.parquet：每日清洗观测，含速度、流量、占有率和可获取时间。
- reports/cohort.csv、coverage_detector_month.csv：队列参考及长期覆盖。
- reports/validation.json、handoff_manifest.json：最终校验和文件来源。
- project/notebooks/long_window_review.ipynb：已执行的中文复核笔记。
- project/docs/long_window_data.md：具体口径与复现方法。
- GitHub_Long_Window_Data_Handoff.zip：后续可上传的代码和小型报告，不含大型原始/处理数据。

其他成员仍需完成道路匹配和空间特征、外部因素、基础模型和机器学习、按时间评估及最终解释。本次数据标签与划分不等于小组已经批准的最终研究口径。
'''
    (root/'README.md').write_text(text,encoding='utf-8')
    small=project/'reports/long_window';small.mkdir(parents=True,exist_ok=True)
    import shutil
    for name in ['summary.json','validation.json','cohort.csv','coverage_detector_month.csv',
                 'selection_filter_comparison.csv','training_only_threshold_sensitivity.json','archive_anomalies.csv']:
        shutil.copy2(root/'reports'/name,small/name)
    (small/'README.md').write_text(text,encoding='utf-8')
    notebook=project/'notebooks/long_window_review.ipynb';nb=json.loads(notebook.read_text(encoding='utf-8'))
    namespace={};prior=Path.cwd();os.chdir(notebook.parent)
    try:
        number=0
        for cell in nb['cells']:
            if cell['cell_type']!='code':continue
            number+=1;capture=io.StringIO()
            with contextlib.redirect_stdout(capture):exec(''.join(cell['source']),namespace)
            cell['execution_count']=number
            cell['outputs']=[{'output_type':'stream','name':'stdout','text':capture.getvalue().splitlines(True)}]
    finally:os.chdir(prior)
    nb['metadata']['executed_at_utc']=datetime.now(timezone.utc).isoformat()
    notebook.write_text(json.dumps(nb,indent=2,ensure_ascii=False),encoding='utf-8')
    files=[project/'configs/long_window.json',project/'src/traffic_recovery/data/long_window.py',
           project/'tests/test_long_window.py',project/'docs/long_window_data.md',notebook]
    files += [project/'scripts'/name for name in ['download_long_window.py','prepare_long_window.py',
                    'label_long_window.py','verify_long_window.py','finish_long_window.py']]
    files += list(small.glob('*'))
    package=root/'GitHub_Long_Window_Data_Handoff.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for file in files:z.write(file,file.relative_to(project).as_posix())
    with zipfile.ZipFile(package) as z:assert z.testzip() is None
    completion=json.loads((root/'completion.json').read_text(encoding='utf-8'))
    completion.update(validation='passed',notebook='executed',tests_passed=int(passed[-1]) if passed else None,
        package=package.name,package_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
        handoff_finished_at_utc=datetime.now(timezone.utc).isoformat())
    (root/'completion.json').write_text(json.dumps(completion,indent=2),encoding='utf-8')
    print('VERIFIED_AND_PACKAGED',json.dumps(completion),flush=True)


if __name__=='__main__':main()
