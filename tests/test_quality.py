"""Public quality accounting tested with explicitly synthetic observation sequences."""
from pathlib import Path

import pandas as pd

from traffic_recovery.data.quality import QualityAccumulator
from traffic_recovery.data.traffic import clean_traffic, parse_traffic


def test_coverage_counts_gaps_and_repeated_snapshots_separately() -> None:
    fixture = Path(__file__).parent / "fixtures" / "raw_synthetic.xml"
    parsed = parse_traffic(fixture.read_bytes())
    clean, stats = clean_traffic(parsed)
    accumulator = QualityAccumulator()
    accumulator.add(clean, stats)
    accumulator.add(clean, stats)
    later = parsed.copy()
    later["timestamp"] += pd.Timedelta(seconds=60)
    later["period_start"] += pd.Timedelta(seconds=60)
    later_clean, later_stats = clean_traffic(later)
    accumulator.add(later_clean, later_stats)
    report = accumulator.report()
    assert report["files_parsed"] == 3
    assert report["output_rows"] == 3
    assert report["unique_observation_keys"] == 2
    assert report["cross_file_exact_duplicate_rows"] == 1
    assert report["missing_global_slots_between_extrema"] == 1
    assert report["missing_series_slots_between_each_series_extrema"] == 1
    assert report["max_series_gap_seconds"] == 60
    # An archive arriving later can fill an earlier observation slot. Gap
    # accounting must use observation-time order, not archive arrival order.
    middle = parsed.copy()
    middle["timestamp"] += pd.Timedelta(seconds=30)
    middle["period_start"] += pd.Timedelta(seconds=30)
    middle_clean, middle_stats = clean_traffic(middle)
    accumulator.add(middle_clean, middle_stats)
    final = accumulator.report()
    assert final["series_gap_seconds_counts"] == {30: 2}
    assert final["out_of_order_unique_rows"] == 1
    assert final["missing_global_slots_between_extrema"] == 0
