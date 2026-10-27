"""Streaming audit accounting: bounded duplicate window, no model features."""
from array import array
from collections import Counter

import pandas as pd

from traffic_recovery.data.traffic import RAW_KEY, SchemaError


class QualityAccumulator:
    """Accumulate ordered raw snapshots without retaining millions of rows.

    Repeat/conflict detection retains a ten-minute observation-time window.
    Late records beyond that window fail explicitly rather than undercount.
    Field-quality counts are snapshot-row weighted; coverage uses unique keys.
    """

    def __init__(self) -> None:
        self.files = 0
        self.totals: Counter = Counter()
        self.fields: dict[str, Counter] = {}
        self.recent: dict = {}
        self.last: dict = {}
        self.first: dict = {}
        self.series_counts: Counter = Counter()
        self.detectors: set = set()
        self.directions: set = set()
        self.times: set = set()
        self.series_times: dict[tuple, array] = {}
        self.intervals: Counter = Counter()
        self.watermark = None

    def add(self, frame: pd.DataFrame, quality: dict) -> None:
        """Add one cleaned raw snapshot; reject conflicting or very late keys."""
        self.files += 1
        for k, v in quality.items():
            if isinstance(v, int):
                self.totals[k] += v
        for field, stats in quality["measurements"].items():
            self.fields.setdefault(field, Counter()).update(
                {k: v for k, v in stats.items() if k != "clean_missing_rate"})
        self.detectors.update(frame.detector_id)
        self.directions.update(frame.direction)
        self.intervals.update((frame.timestamp - frame.period_start).dt.total_seconds().astype(int))
        # Raw strings define conflict identity, never rounded normalized values.
        columns = RAW_KEY + ["valid", "speed_raw", "occupancy_raw", "volume_raw", "sd_raw"]
        for detector, direction, lane, stamp, *values in frame.sort_values("timestamp")[columns].itertuples(index=False, name=None):
            if self.watermark is not None and stamp < self.watermark - pd.Timedelta(minutes=10):
                raise SchemaError("Out-of-order snapshot exceeds duplicate window")
            series = (detector, direction, lane)
            bucket = self.recent.setdefault(stamp, {})
            signature = tuple(values)
            if series in bucket:
                if bucket[series] != signature:
                    self.totals["cross_file_conflicting_rows"] += 1
                else:
                    self.totals["cross_file_exact_duplicate_rows"] += 1
                continue
            bucket[series] = signature
            self.times.add(stamp)
            self.series_counts[series] += 1
            self.first[series] = min(stamp, self.first.get(series, stamp))
            if series in self.last and stamp < self.last[series]:
                self.totals["out_of_order_unique_rows"] += 1
            if series not in self.series_times:
                self.series_times[series] = array("q")
            self.series_times[series].append(int(stamp.timestamp()))
            self.last[series] = max(stamp, self.last.get(series, stamp))
        newest = frame.timestamp.max()
        self.watermark = max(newest, self.watermark) if self.watermark is not None else newest
        self.recent = {t: rows for t, rows in self.recent.items()
                       if t >= self.watermark - pd.Timedelta(minutes=10)}

    def report(self) -> dict:
        """Return JSON-safe measured statistics; absent time slots are not zeros."""
        if not self.files:
            return {"files_parsed": 0, "status": "no observations"}
        for counts in self.fields.values():
            counts["clean_missing_rate"] = counts["clean_missing"] / self.totals["output_rows"]
        times = sorted(self.times)
        step = self.intervals.most_common(1)[0][0]
        expected_global = int((times[-1] - times[0]).total_seconds() // step) + 1
        expected_series = sum(int((self.last[s] - first).total_seconds() // step) + 1
                              for s, first in self.first.items())
        unique_rows = sum(self.series_counts.values())
        # A later archive file can contain an earlier observation. Sort per-series
        # compact epoch-second arrays before measuring gaps, not capture order.
        gaps: Counter = Counter()
        for stamps in self.series_times.values():
            ordered = sorted(stamps)
            gaps.update(b - a for a, b in zip(ordered, ordered[1:]))
        return {
            "files_parsed": self.files, **dict(self.totals),
            "quality_denominator": "output_rows: per-snapshot rows, including cross-file repeats",
            "measurements": {k: dict(v) for k, v in self.fields.items()},
            "unique_observation_keys": unique_rows,
            "detector_count": len(self.detectors), "lane_direction_series_count": len(self.first),
            "detector_ids": sorted(self.detectors), "directions": sorted(self.directions),
            "observation_min": times[0].isoformat(), "observation_max": times[-1].isoformat(),
            "interval_seconds_counts": dict(sorted(self.intervals.items())),
            "unique_period_end_times": len(times), "expected_global_slots_between_extrema": expected_global,
            "missing_global_slots_between_extrema": expected_global - len(times),
            "expected_series_slots_between_each_series_extrema": expected_series,
            "missing_series_slots_between_each_series_extrema": expected_series - unique_rows,
            "missing_series_slot_rate_between_extrema": (expected_series - unique_rows) / expected_series,
            "series_gap_seconds_counts": dict(sorted(gaps.items())),
            "max_series_gap_seconds": max(gaps, default=0),
            "coverage_caveat": "Between observed extrema only; not a complete detector inventory or uptime measure. Invalid measurements still occupy slots. Conflicts counted, not resolved.",
        }
