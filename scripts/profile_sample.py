"""Describe only an exported sample; never extrapolate these counts to all days."""
import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> int:
    """Profile sample speeds, zero-volume records and metadata direction conflicts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--detectors", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    frame = pd.read_csv(args.sample)
    locations = pd.read_csv(args.detectors, encoding="utf-8-sig")
    pairs = frame[["detector_id", "direction"]].drop_duplicates().merge(
        locations[["AID_ID_Number", "Direction"]], left_on="detector_id",
        right_on="AID_ID_Number", how="left", validate="many_to_one")
    disagreements = pairs.loc[pairs.direction.ne(pairs.Direction)].to_dict("records")
    report = {
        "scope": "Only the supplied exported sample; not all audited rows. See sample provenance for selection.",
        "rows": len(frame),
        "speed_kmh_quantiles": {str(k): float(v) for k, v in frame.speed_kmh.quantile([0, .25, .5, .75, .95, 1]).items()},
        "zero_valid_volume_rows": int(frame.volume_count.eq(0).sum()),
        "positive_speed_with_zero_valid_volume_rows": int((frame.volume_count.eq(0) & frame.speed_kmh.gt(0)).sum()),
        "unique_detector_direction_pairs": len(pairs),
        "direction_disagreement_count": len(disagreements),
        "direction_disagreements_with_current_metadata": disagreements,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "direction_disagreements_with_current_metadata"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
