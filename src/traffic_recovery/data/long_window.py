"""Batch source adapter for monthly archives; preserves repository cleaning rules."""
from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pandas as pd

from traffic_recovery.data.traffic import HK, RAW_KEY, SchemaError

RAW_COLUMNS = RAW_KEY + ['period_start','valid','speed_raw','volume_raw','occupancy_raw','sd_raw']
COMPACT_COLUMNS = RAW_KEY + ['speed_kmh','volume_count','occupancy_pct','speed_sd_kmh',
                            'valid','conflict','signature','available_at','source_file']
DETECTOR = re.compile(rb'<detector>.*?</detector>', re.DOTALL)
IDENTIFIER = re.compile(rb'<detector_id>(.*?)</detector_id>', re.DOTALL)


def parse_rows(payload: bytes, member: str, ids: set[str] | None = None) -> list[dict]:
    """Flatten original XML without a DataFrame per snapshot; optional explicit cohort."""
    if ids is not None:
        encoded = {s.encode() for s in ids}
        def keep(match):
            identity = IDENTIFIER.search(match[0])
            if identity is None:
                raise SchemaError('Missing detector_id')
            return match[0] if identity[1].strip() in encoded else b''
        payload = DETECTOR.sub(keep, payload)
    root = ET.fromstring(payload)
    if root.tag != 'raw_speed_volume_list':
        raise SchemaError('Unknown raw XML root')
    day = date.fromisoformat(root.findtext('date'))
    available = datetime.strptime(Path(member).name[:13], '%Y%m%d-%H%M').replace(tzinfo=HK)
    def text(element, tag, empty=False):
        field = element.find(tag)
        if field is None or (not empty and not (field.text or '').strip()):
            raise SchemaError('Missing field: ' + tag)
        return (field.text or '').strip()
    rows = []
    for period in root.findall('./periods/period'):
        start = datetime.combine(day,time.fromisoformat(text(period,'period_from')),HK)
        end = datetime.combine(day,time.fromisoformat(text(period,'period_to')),HK)
        if end < start: end += timedelta(days=1)
        if (end-start).total_seconds() != 30 or available < end:
            raise SchemaError('Non-30s interval or observation later than capture')
        for detector in period.findall('./detectors/detector'):
            identity, direction = text(detector,'detector_id'), text(detector,'direction')
            for lane in detector.findall('./lanes/lane'):
                rows.append({'detector_id':identity,'direction':direction,'lane_id':text(lane,'lane_id'),
                             'timestamp':end,'period_start':start,'available_at':available,'source_file':member,
                             'valid':text(lane,'valid',True),'speed_raw':text(lane,'speed',True),
                             'volume_raw':text(lane,'volume',True),'occupancy_raw':text(lane,'occupancy',True),
                             'sd_raw':text(lane,'s.d.',True)})
    return rows


def compact_rows(rows: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Quarantine within-snapshot conflicts; retain distinct capture versions.

    Cross-batch conflicts are additionally reconciled before coverage/bin formation.
    Occupancy and speed SD are retained; neither is imputed or used in labels.
    """
    raw = pd.DataFrame(rows)
    if raw.empty: return pd.DataFrame(columns=COMPACT_COLUMNS), {'input_rows':0}
    for name in ['timestamp','period_start','available_at']:
        raw[name] = pd.to_datetime(raw[name], utc=True).dt.tz_convert('Asia/Hong_Kong').dt.as_unit('ns')
    raw['signature'] = raw['valid']+'|'+raw['speed_raw']+'|'+raw['volume_raw']+'|'+raw['occupancy_raw']+'|'+raw['sd_raw']
    source = raw.drop_duplicates().copy()
    key = RAW_KEY + ['source_file','available_at']
    source['conflict'] = source.duplicated(key,keep=False)
    quality = {'source_rows_before_batch_deduplication':len(raw),
               'source_offline_rows':int(source.valid.eq('N').sum()),
               'unknown_validity_rows':int((~source.valid.isin(['Y','N'])).sum()),
               'conflicting_keys_quarantined':len(source.loc[source.conflict,key].drop_duplicates())}
    # Equivalent domains to clean_traffic; capture identity prevents a later
    # revision from retroactively altering an earlier available observation.
    for field,normalized,integer,bound in [('speed','speed_kmh',True,None),
            ('volume','volume_count',True,None),('occupancy','occupancy_pct',True,100),
            ('sd','speed_sd_kmh',False,None)]:
        value=pd.to_numeric(source[field+'_raw'],errors='coerce').astype('Float64')
        invalid=value.isna()|value.isin([float('inf'),-float('inf')])|value.lt(0)
        if integer: invalid |= value.mod(1).ne(0).fillna(False)
        if bound is not None: invalid |= value.gt(bound).fillna(False)
        source[normalized]=value.mask(invalid|~source.valid.eq('Y')|source.conflict)
    clean = source.drop_duplicates(key)
    return clean[COMPACT_COLUMNS], quality
