"""SYNTHETIC external records; behavior tests, never source observations."""
from pathlib import Path

import pandas as pd
import pytest

from traffic_recovery.external.build import ContextRules, build_context_features
from traffic_recovery.external.calendar import calendar_features
from traffic_recovery.external.incidents import incident_features
from traffic_recovery.external.major_events import major_event_features
from traffic_recovery.external.pipeline import build_context_dataset
from traffic_recovery.external.weather import weather_features


HKT = "Asia/Hong_Kong"
PREDICTION = pd.Timestamp("2026-01-01T11:00:00", tz=HKT)
ROOT = Path(__file__).parents[1]
PROVENANCE_COLUMNS = ["source_url", "source_retrieved_at", "source_sha256"]


def provenance(size: int, name: str) -> dict[str, object]:
    return {
        "source_url": [f"https://example.invalid/{name}"] * size,
        "source_retrieved_at": pd.DatetimeIndex([
            pd.Timestamp("2026-01-02", tz=HKT)
        ] * size),
        "source_sha256": ["0" * 64] * size,
    }


def events() -> pd.DataFrame:
    return pd.DataFrame({
        "event_id": ["SYNTHETIC-EVENT"],
        "prediction_time": pd.DatetimeIndex([PREDICTION]),
        "segment_id": ["SYNTHETIC-SEGMENT"],
        "weather_station_id": ["SYNTHETIC-STATION"],
    })


def holidays() -> pd.DataFrame:
    return pd.DataFrame({
        "holiday_id": ["H1", "H2", "FUTURE-PUBLICATION"],
        "local_date": ["2026-01-01", "2026-01-02", "2026-01-01"],
        "holiday_name": ["Synthetic holiday", "Synthetic next day", "Unavailable"],
        "available_at": pd.DatetimeIndex([
            pd.Timestamp("2025-05-01", tz=HKT),
            pd.Timestamp("2025-05-01", tz=HKT),
            pd.Timestamp("2026-01-01T12:00:00", tz=HKT),
        ]),
        **provenance(3, "holidays"),
    })


def weather() -> pd.DataFrame:
    return pd.DataFrame({
        "station_id": ["SYNTHETIC-STATION", "SYNTHETIC-STATION"],
        "observed_at": pd.DatetimeIndex([
            pd.Timestamp("2026-01-01T10:00:00", tz=HKT),
            pd.Timestamp("2026-01-01T10:30:00", tz=HKT),
        ]),
        "available_at": pd.DatetimeIndex([
            pd.Timestamp("2026-01-01T10:05:00", tz=HKT),
            pd.Timestamp("2026-01-01T12:00:00", tz=HKT),
        ]),
        "temperature_c": [20.0, 99.0],
        "relative_humidity_pct": [70.0, 99.0],
        "rainfall_mm": [1.0, 99.0],
        "wind_speed_kmh": [12.0, 99.0],
        **provenance(2, "weather"),
    })


def incidents() -> pd.DataFrame:
    return pd.DataFrame({
        "incident_id": ["I1", "I1", "UNPUBLISHED"],
        "segment_id": ["SYNTHETIC-SEGMENT"] * 3,
        "available_at": pd.DatetimeIndex([
            pd.Timestamp("2026-01-01T10:10:00", tz=HKT),
            pd.Timestamp("2026-01-01T11:30:00", tz=HKT),
            pd.Timestamp("2026-01-01T12:00:00", tz=HKT),
        ]),
        "effective_start": pd.DatetimeIndex([
            pd.Timestamp("2026-01-01T10:00:00", tz=HKT),
            pd.Timestamp("2026-01-01T10:00:00", tz=HKT),
            pd.Timestamp("2026-01-01T10:00:00", tz=HKT),
        ]),
        "effective_end": pd.DatetimeIndex([
            pd.NaT,
            pd.Timestamp("2026-01-01T10:45:00", tz=HKT),
            pd.NaT,
        ]),
        "distance_m": [50.0, 50.0, 10.0],
        "is_road_closure": [True, True, False],
        **provenance(3, "incidents"),
    })


def major_events() -> pd.DataFrame:
    return pd.DataFrame({
        "major_event_id": ["M-ACTIVE", "M-UPCOMING", "M-UNPUBLISHED"],
        "segment_id": ["SYNTHETIC-SEGMENT"] * 3,
        "available_at": pd.DatetimeIndex([
            pd.Timestamp("2025-12-01", tz=HKT),
            pd.Timestamp("2025-12-01", tz=HKT),
            pd.Timestamp("2026-01-01T12:00:00", tz=HKT),
        ]),
        "start_time": pd.DatetimeIndex([
            pd.Timestamp("2026-01-01T10:00:00", tz=HKT),
            pd.Timestamp("2026-01-01T12:00:00", tz=HKT),
            pd.Timestamp("2026-01-01T10:00:00", tz=HKT),
        ]),
        "end_time": pd.DatetimeIndex([
            pd.Timestamp("2026-01-01T11:30:00", tz=HKT),
            pd.Timestamp("2026-01-01T14:00:00", tz=HKT),
            pd.Timestamp("2026-01-01T12:00:00", tz=HKT),
        ]),
        "distance_m": [100.0, 200.0, 1.0],
        **provenance(3, "major-events"),
    })


def test_calendar_uses_civil_date_and_publication_availability() -> None:
    row = calendar_features(events(), holidays()).iloc[0]
    assert row.is_public_holiday and row.is_day_before_holiday
    assert row.calendar_source_observed
    assert row.holiday_count == 1
    assert row.calendar_max_source_available_at < row.prediction_time


def test_weather_is_backward_and_availability_aware() -> None:
    row = weather_features(events(), weather(), max_age=pd.Timedelta(hours=2)).iloc[0]
    assert row.temperature_c == 20.0
    assert row.weather_age_minutes == 60
    assert row.weather_available_at <= row.prediction_time
    assert not row.weather_missing


def test_weather_marks_observation_outside_tolerance_missing() -> None:
    row = weather_features(events(), weather(), max_age=pd.Timedelta(minutes=30)).iloc[0]
    assert row.weather_missing and pd.isna(row.temperature_c)


def test_incident_uses_latest_snapshot_available_at_prediction() -> None:
    row = incident_features(events(), incidents(), max_distance_m=100).iloc[0]
    assert row.active_incident_count == 1
    assert row.incident_records_observed
    assert row.active_road_closure_count == 1
    assert row.nearest_incident_distance_m == 50
    assert row.incident_max_available_at <= row.prediction_time


def test_incident_preserves_unknown_closure_status() -> None:
    source = incidents()
    source["is_road_closure"] = source.is_road_closure.astype("boolean")
    source.loc[0, "is_road_closure"] = pd.NA
    row = incident_features(events(), source, max_distance_m=100).iloc[0]
    assert pd.isna(row.active_road_closure_count)
    assert row.active_road_closure_status_missing


def test_major_events_exclude_unpublished_records() -> None:
    row = major_event_features(events(), major_events()).iloc[0]
    assert row.active_major_event_count == 1
    assert row.major_event_records_observed
    assert row.upcoming_major_event_count == 1
    assert row.nearest_major_event_distance_m == 100
    assert row.minutes_to_next_major_event == 60


def test_integration_preserves_one_row_per_event() -> None:
    result = build_context_features(
        events(),
        holidays=holidays(),
        weather_observations=weather(),
        incidents=incidents(),
        major_events=major_events(),
        rules=ContextRules(
            weather_max_age=pd.Timedelta(hours=2), incident_max_distance_m=100
        ),
    )
    assert result.event_id.tolist() == ["SYNTHETIC-EVENT"]
    assert result.iloc[0].temperature_c == 20
    assert result.iloc[0].active_incident_count == 1
    assert result.iloc[0].active_major_event_count == 1
    assert result.iloc[0].context_version == "external-context-v1"


def test_context_rules_load_from_versioned_config() -> None:
    rules = ContextRules.from_path(ROOT / "configs" / "external_features.json")
    assert rules.version == "external-context-v1"
    assert rules.weather_max_age == pd.Timedelta(minutes=60)


def test_rejects_naive_source_timestamps() -> None:
    observations = weather()
    observations["available_at"] = observations.available_at.dt.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        weather_features(events(), observations)


def test_rejects_numeric_identifiers_and_missing_provenance() -> None:
    bad_events = events().assign(event_id=[123])
    with pytest.raises(ValueError, match="strings"):
        calendar_features(bad_events, holidays())
    with pytest.raises(ValueError, match="source_sha256"):
        weather_features(events(), weather().drop(columns="source_sha256"))


def test_weather_prefers_newest_observation_over_later_correction() -> None:
    observations = weather()
    observations.loc[1, "available_at"] = pd.Timestamp("2026-01-01T10:45:00", tz=HKT)
    observations.loc[0, "available_at"] = pd.Timestamp("2026-01-01T10:55:00", tz=HKT)
    row = weather_features(events(), observations, max_age=pd.Timedelta(hours=2)).iloc[0]
    assert row.temperature_c == 99.0
    assert row.weather_observed_at == pd.Timestamp("2026-01-01T10:30:00", tz=HKT)


def test_optional_sources_can_be_explicitly_empty() -> None:
    result = build_context_features(
        events(),
        holidays=pd.DataFrame(columns=[
            "holiday_id", "local_date", "holiday_name", "available_at",
            *PROVENANCE_COLUMNS,
        ]),
        weather_observations=pd.DataFrame(columns=[
            "station_id", "observed_at", "available_at", "temperature_c",
            "relative_humidity_pct", "rainfall_mm", "wind_speed_kmh",
            *PROVENANCE_COLUMNS,
        ]),
        incidents=pd.DataFrame(columns=[
            "incident_id", "segment_id", "available_at", "effective_start",
            "effective_end", "distance_m", "is_road_closure",
            *PROVENANCE_COLUMNS,
        ]),
        major_events=pd.DataFrame(columns=[
            "major_event_id", "segment_id", "available_at", "start_time",
            "end_time", "distance_m", *PROVENANCE_COLUMNS,
        ]),
    ).iloc[0]
    assert result.weather_missing
    assert not result.calendar_source_observed
    assert pd.isna(result.holiday_count)
    assert not result.incident_records_observed
    assert pd.isna(result.active_incident_count)
    assert not result.major_event_records_observed
    assert pd.isna(result.active_major_event_count)


def test_context_pipeline_writes_hashed_manifest(tmp_path: Path) -> None:
    frames = {
        "events": events(), "holidays": holidays(), "weather": weather(),
        "incidents": incidents(), "major_events": major_events(),
    }
    paths = {}
    for name, frame in frames.items():
        paths[name] = tmp_path / f"{name}.parquet"
        frame.to_parquet(paths[name], index=False)
    output = tmp_path / "context.parquet"
    manifest_path = tmp_path / "context-manifest.json"
    manifest = build_context_dataset(
        events_path=paths["events"], holidays_path=paths["holidays"],
        weather_path=paths["weather"], incidents_path=paths["incidents"],
        major_events_path=paths["major_events"],
        config_path=ROOT / "configs" / "external_features.json",
        output_path=output, manifest_path=manifest_path,
    )
    assert manifest["rows"] == 1 and len(manifest["output"]["sha256"]) == 64
    assert output.is_file() and manifest_path.is_file()
    with pytest.raises(FileExistsError):
        build_context_dataset(
            events_path=paths["events"], holidays_path=paths["holidays"],
            weather_path=paths["weather"], incidents_path=paths["incidents"],
            major_events_path=paths["major_events"],
            config_path=ROOT / "configs" / "external_features.json",
            output_path=output, manifest_path=manifest_path,
        )
