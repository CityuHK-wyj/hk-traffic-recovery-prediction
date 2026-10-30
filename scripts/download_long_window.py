"""Acquire all 45 official monthly archives, retaining HTTP and integrity evidence."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import zipfile
import xml.etree.ElementTree as ET
import time
from collections import Counter
from urllib.request import Request, urlopen

from traffic_recovery.data.http import EvidenceClient, sha256_file
from traffic_recovery.data.sources import RAW, RESOURCES, archive_url


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def acquire(root, entry):
    token = entry['timestamp']
    target = root / 'raw' / token[:6]
    target.mkdir(parents=True, exist_ok=True)
    archive = fetch_ranges(target, entry)
    if archive.stat().st_size != entry['size']:
        raise ValueError('Archive byte count differs from official inventory: ' + token)
    with zipfile.ZipFile(archive) as bundle:
        members = sorted((x for x in bundle.infolist() if x.filename.lower().endswith('.xml')),key=lambda x:x.filename)
        if len(members) != entry['resource_file_count']:
            raise ValueError('Snapshot count differs from official inventory: ' + token)
        stamps = [Path(x.filename).name[:13] for x in members]
        for stamp in stamps: datetime.strptime(stamp,'%Y%m%d-%H%M')
        outside=[x.filename for x in members if not Path(x.filename).name.startswith(token[:6])]
        duplicate_names={n:count for n,count in Counter(x.filename for x in members).items() if count>1}
        for info in [members[0],members[-1]]:
            if ET.fromstring(bundle.read(info)).tag != 'raw_speed_volume_list':
                raise ValueError('Unexpected XML root: ' + info.filename)
        record = {'month': token[:6], 'path': archive.relative_to(root).as_posix(),
                  'bytes': archive.stat().st_size, 'sha256': sha256_file(archive),
                  'snapshots': len(members), 'xml_bytes': sum(n.file_size for n in members),
                  'duplicate_name_extra_entries':sum(c-1 for c in duplicate_names.values()),
                  'duplicate_names':duplicate_names,
                  'out_of_month_capture_entries':outside,
                  'first_capture': stamps[0], 'last_capture': stamps[-1],
                  'validation': 'Official monthly byte/member counts; valid capture filenames; duplicate names and cross-month entries recorded and retained; first/last XML parsed. Full CRC and row checks occur during ingestion.'}
    write_json(target / 'archive_check.json', record)
    print('COMPLETE', record['month'], record['bytes'], record['snapshots'], flush=True)
    return record


def fetch_ranges(target, entry):
    """Resume at verified range boundaries; pin ETag and validate each Content-Range."""
    requested = archive_url('get-file', url=RAW, time=entry['timestamp'])
    archive = target / ('raw_' + entry['timestamp'][:6] + '.zip')
    metadata = archive.with_name(archive.name + '.meta.json')
    if archive.exists():
        old = json.loads(metadata.read_text(encoding='utf-8'))
        if old['requested_url'] != requested or old['sha256'] != sha256_file(archive):
            raise ValueError('Existing archive provenance/hash mismatch')
        return archive
    # The official API rejects HEAD; a one-byte GET follows its real redirect.
    with urlopen(Request(requested, headers={'Range':'bytes=0-0'}), timeout=60) as response:
        final = response.url
        headers = dict(response.headers.items())
        etag = response.headers.get('ETag')
        if response.status != 206 or response.headers.get('Content-Range') != f'bytes 0-0/{entry["size"]}' or not etag:
            raise ValueError('Probe length or ETag differs from inventory')
        response.read()
    partial = archive.with_suffix('.range-partial')
    checkpoint = target / 'range_checkpoint.json'
    offset = 0
    if checkpoint.exists():
        old = json.loads(checkpoint.read_text(encoding='utf-8'))
        if old['url'] != final or old['etag'] != etag or old['expected_bytes'] != entry['size']:
            raise ValueError('Remote object changed since checkpoint')
        offset = old['verified_bytes']
        if not partial.exists() or partial.stat().st_size < offset:
            raise ValueError('Missing/corrupt partial download')
        with partial.open('r+b') as stream:
            stream.truncate(offset)
        if sha256_file(partial) != old['prefix_sha256']:
            raise ValueError('Downloaded prefix checksum mismatch')
    elif partial.exists():
        raise ValueError('Partial without checkpoint')
    digest = __import__('hashlib').sha256()
    if offset:
        with partial.open('rb') as stream:
            while block := stream.read(1024*1024): digest.update(block)
    with partial.open('ab') as stream:
        while offset < entry['size']:
            stop = min(offset + 8*1024*1024, entry['size']) - 1
            for attempt in range(1,4):
                record = {'requested_url': final, 'range': [offset,stop], 'attempt': attempt,
                          'retrieved_at': datetime.now(timezone.utc).isoformat()}
                try:
                    request = Request(final, headers={'Range': f'bytes={offset}-{stop}', 'If-Match': etag, 'Accept-Encoding': 'identity'})
                    with urlopen(request, timeout=60) as response:
                        record.update(status=response.status, headers=dict(response.headers.items()))
                        payload = response.read()
                        if (response.status != 206 or response.headers.get('ETag') != etag
                            or response.headers.get('Content-Range') != f'bytes {offset}-{stop}/{entry["size"]}'
                            or len(payload) != stop-offset+1):
                            raise ValueError('Invalid byte range response')
                    record.update(bytes=len(payload), sha256=__import__('hashlib').sha256(payload).hexdigest())
                except Exception as exc:
                    record['error'] = repr(exc)
                with (target/'range_requests.jsonl').open('a',encoding='utf-8') as log:
                    log.write(json.dumps(record)+'\n')
                if 'error' not in record:
                    break
                if attempt == 3: raise RuntimeError(record['error'])
                time.sleep(attempt)
            stream.write(payload)
            stream.flush()
            digest.update(payload)
            offset = stop+1
            write_json(checkpoint, {'url': final,'etag': etag,'expected_bytes':entry['size'],
                                   'verified_bytes':offset,'prefix_sha256':digest.hexdigest()})
    partial.replace(archive)
    write_json(metadata, {'requested_url': requested,'final_url':final,'status':206,
                         'acquisition':'Validated 206 ranges pinned to a single ETag; reconstructed original object',
                         'headers':headers,'bytes':offset,'sha256':digest.hexdigest(),
                         'completed_at':datetime.now(timezone.utc).isoformat()})
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--boundary-only', action='store_true')
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    client = EvidenceClient(args.root / 'metadata', timeout=180, reuse=True)
    if args.boundary_only:
        listing=client.json(archive_url('list-file-versions',url=RAW,start='20261001',end='20261001'),'boundary_inventory.json')
        entries=[e for e in listing['data-files'] if e['timestamp']=='20261001' and e['period']=='D']
        if len(entries)!=1: raise ValueError('Expected a daily Oct 1 boundary archive')
        record=acquire(args.root,entries[0])
        record['scope']='2026-10-01 capture-day boundary; not an extra evaluation month'
        output=args.root/'raw/20261001-boundary';output.mkdir(exist_ok=True)
        write_json(output/'archive_check.json',record)
        return
    listing = client.json(archive_url('list-file-versions', url=RAW, start='20230101', end='20260930'), 'archive_inventory.json')
    entries = [e for e in listing['data-files'] if '202301' <= e['timestamp'][:6] <= '202609']
    expected = [f'{y}{m:02d}' for y in range(2023,2027) for m in range(1,13) if (y,m) <= (2026,9)]
    if sorted(e['timestamp'][:6] for e in entries) != expected or any(e['period'] != 'M' for e in entries):
        raise ValueError('Expected exactly 45 monthly archive entries')
    for name in ['detectors.csv', 'traffic_spec.pdf', 'raw_schema.xsd']:
        client.fetch(RESOURCES[name], name)
    print('INVENTORY', len(entries), sum(e['size'] for e in entries), 'bytes', flush=True)
    records, errors = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(acquire, args.root, e): e['timestamp'][:6] for e in entries}
        for future in as_completed(jobs):
            try:
                records.append(future.result())
            except Exception as exc:
                errors.append({'month': jobs[future], 'error': repr(exc)})
                print('FAILED', jobs[future], repr(exc), flush=True)
            write_json(args.root / 'download_manifest.json', {
                'updated_at_utc': datetime.now(timezone.utc).isoformat(), 'source': RAW,
                'window': ['2023-01-01', '2026-09-30'], 'expected_months': 45,
                'expected_bytes': sum(e['size'] for e in entries),
                'complete': len(records) == 45 and not errors,
                'records': sorted(records, key=lambda r:r['month']), 'errors': errors})
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
