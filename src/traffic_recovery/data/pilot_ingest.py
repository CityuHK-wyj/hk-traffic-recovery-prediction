"""Incremental real-archive ingestion to compact, source-linked Parquet partitions."""
import argparse
from datetime import date, datetime, timedelta
import json
import logging
from pathlib import Path
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traffic_recovery.data.http import EvidenceClient, sha256_file
from traffic_recovery.data.sources import RAW, archive_url, list_versions
from traffic_recovery.data.traffic import HK, RAW_KEY, clean_traffic, parse_traffic

LOGGER = logging.getLogger(__name__)
VERSION = "pilot-ingest-1"


def compact_snapshot(payload: bytes, member: str) -> pd.DataFrame:
    """Retain one row/key, masking ALL ambiguous values; never resolve conflicts.

    Carries original strings as a signature so cross-file conflicts can also be
    quarantined downstream. Original XML remains authoritative in the ZIP.
    """
    raw = parse_traffic(payload)
    if not raw.timestamp.sub(raw.period_start).eq(pd.Timedelta(seconds=30)).all():
        raise ValueError("Pilot requires 30-second source intervals")
    frame, _ = clean_traffic(raw, conflicts="quarantine")
    ambiguous = raw.drop_duplicates().loc[lambda x: x.duplicated(RAW_KEY, keep=False)]
    if len(ambiguous):
        bad = ambiguous.drop_duplicates(RAW_KEY).copy()
        bad["speed_kmh"] = float("nan")
        bad["volume_count"] = float("nan")
        frame = pd.concat([frame, bad], ignore_index=True)
    frame["conflict"] = frame.set_index(RAW_KEY).index.isin(ambiguous.set_index(RAW_KEY).index)
    frame["signature"] = frame[["valid", "speed_raw", "volume_raw", "occupancy_raw", "sd_raw"]].astype(str).agg("|".join, axis=1)
    frame["available_at"] = datetime.strptime(Path(member).name[:13], "%Y%m%d-%H%M").replace(tzinfo=HK)
    if (frame.available_at < frame.timestamp).any():
        raise ValueError("Capture precedes observation")
    frame["source_file"] = member
    return frame[RAW_KEY + ["speed_kmh", "volume_count", "valid", "conflict", "signature", "available_at", "source_file"]]


def ingest_day(archive: Path, destination: Path, listing: dict) -> dict:
    """Stream at most 32 XML snapshots/batch, atomically publish one daily file.

    Bounded memory depends on snapshot size, not total archive XML size. A
    manifest verifies ZIP and output hashes on restart; partial files are not reused.
    """
    manifest = destination.with_suffix(".json")
    source_hash = sha256_file(archive)
    if destination.exists() or manifest.exists():
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if (record["source_sha256"] != source_hash or record["version"] != VERSION
                or record["parquet_sha256"] != sha256_file(destination)):
            raise ValueError(f"Stale or corrupt partition: {destination}")
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".partial")
    writer = None
    rows = 0
    with zipfile.ZipFile(archive) as bundle:
        members = sorted(m for m in bundle.namelist() if m.endswith(".xml"))
        stamps = [Path(m).name[:13] for m in members]
        if sorted(stamps) != sorted(listing["timestamps"]):
            raise ValueError("ZIP members differ from complete daily listing")
        batch = []
        try:
            for index, member in enumerate(members):
                batch.append(compact_snapshot(bundle.read(member), member))
                if len(batch) == 32 or index == len(members) - 1:
                    table = pa.Table.from_pandas(pd.concat(batch, ignore_index=True), preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
                    writer.write_table(table)
                    rows += table.num_rows
                    batch.clear()
                if index % 200 == 0:
                    LOGGER.info("ingest_progress archive=%s snapshots=%s total=%s", archive.name, index + 1, len(members))
        finally:
            if writer is not None:
                writer.close()
        if not rows:
            raise ValueError("Empty archive")
        temporary.replace(destination)
        record = {"version": VERSION, "source": archive.as_posix(), "source_sha256": source_hash,
                  "source_metadata": json.loads(archive.with_name(archive.name + ".meta.json").read_text(encoding="utf-8")),
                  "snapshots": len(members), "rows": rows, "zip_bytes": archive.stat().st_size,
                  "xml_bytes": sum(bundle.getinfo(m).file_size for m in members),
                  "parquet_bytes": destination.stat().st_size, "parquet_sha256": sha256_file(destination)}
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> None:
    """Acquire complete daily listings/ZIPs with evidence; failures are explicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--existing", type=Path, default=Path("data/local/audit-20261019-21"))
    parser.add_argument("--output", type=Path, default=Path("data/local/pilot"))
    args = parser.parse_args()
    if args.end < args.start or (args.end - args.start).days > 30:
        parser.error("Require 1–31 days")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    records = []
    day = args.start
    while day <= args.end:
        token = day.strftime("%Y%m%d")
        root = args.existing if (args.existing / f"raw_{token}.zip").exists() else args.output / "http"
        client = EvidenceClient(root, reuse=True)
        listing = list_versions(client, RAW, day, day, f"versions_{token}.json")
        archive = client.fetch(archive_url("get-file", url=RAW, time=token), f"raw_{token}.zip")
        records.append(ingest_day(archive, args.output / "lane_snapshots" / f"{token}.parquet", listing))
        (args.output / "ingest.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        day += timedelta(days=1)


if __name__ == "__main__":
    main()
