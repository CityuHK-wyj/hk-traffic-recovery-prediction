"""Shared run metadata for reproducible experiment evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import platform
import subprocess
from time import perf_counter
from uuid import uuid4

from traffic_recovery.data.http import sha256_file
from traffic_recovery.models.contract import ExperimentContract


def start_run() -> tuple[datetime, float]:
    """Return UTC wall-clock and monotonic start markers for one run."""
    return datetime.now(timezone.utc), perf_counter()


def _git_state() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True,
            text=True, encoding="utf-8",
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], check=True, capture_output=True,
            text=True, encoding="utf-8",
        ).stdout.strip())
        return {"commit": commit, "dirty": dirty}
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError("Git commit/dirty provenance is unavailable") from error


def run_metadata(
    *, started_at: datetime, started_counter: float,
    contract: ExperimentContract, seed: int | None,
    lock_path: Path = Path("uv.lock"),
) -> dict[str, object]:
    """Capture run identity, timing, split, lock, Git and Python evidence."""
    recorded_at = datetime.now(timezone.utc)
    if not lock_path.is_file():
        raise FileNotFoundError(f"Required lock evidence is missing: {lock_path}")
    lock = {
        "path": lock_path.as_posix(),
        "sha256": sha256_file(lock_path),
        "status": "present",
    }
    return {
        "run_id": f"{started_at:%Y%m%dT%H%M%S.%fZ}-{uuid4().hex[:12]}",
        "started_at": started_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "runtime_seconds": perf_counter() - started_counter,
        "seed": seed,
        "split_boundaries": {
            "validation_start": contract.validation_start.isoformat(),
            "test_start": contract.test_start.isoformat(),
            "test_end": contract.test_end.isoformat(),
        },
        "lock": lock,
        "git": _git_state(),
        "python": platform.python_version(),
    }
