# Milestone 1 verification record

Subsequent records: [bounded-memory verification](pilot_memory_verification.md) and
[medium-scale verification](medium_pilot.md). This document's results below remain
the original milestone-1 results and are not updated retroactively.

Executed **October 27, 2026**. No Git commit, push or merge was performed.
The existing feature branch was `feature/bootstrap-data-audit` throughout.
Pre-existing untracked `.agents/`, `.python-version`, `skills-lock.json` were
preserved; the initial minimal untracked `pyproject.toml` / `uv.lock` were extended.

## Environment actually observed

- Ubuntu **26.04 LTS**, kernel identifying as
  `6.6.114.1-microsoft-standard-WSL2`; x86_64.
- Python **3.12.16**, uv **0.13.6**.
- Final locked pandas **2.3.3**, NumPy **2.3.5**, pytest **9.1.1**.
- Early exploratory runs resolved NumPy 2.5.4 and emitted timedelta deprecation
  warnings with pandas 2.3. NumPy is an existing pandas dependency, not an added
  framework: a documented uv constraint `<2.4` now locks a warning-free tested
  combination. The full audit was rerun with the final lock; its `software` and
  `uv_lock_sha256` fields record the actual environment.

## Commands and actual results

| Command | Result |
|---|---|
| `uv sync --locked` | Exit 0; final lock synchronised |
| `uv run --locked python --version` | Python 3.12.16 |
| `uv run --locked pytest` | **33 passed in 3.17s**, no warnings; latest post-smoke `pytest -q`: **33 passed in 3.04s** |
| `uv run --locked traffic-audit --help` | Exit 0; installed package/CLI discoverable |
| `uv run --locked python -m compileall -q src scripts` | Exit 0 |
| `git diff --check` | Exit 0 |
| `uv build --wheel` | Exit 0; built `dist/hk_traffic_recovery_prediction-0.1.0-py3-none-any.whl` (ignored) |
| Report consistency / lock hash checks | Passed; row accounting, snapshot counts, sorted gap transitions, segment key counts and final `uv.lock` SHA-256 verified |
| `git check-ignore` on raw ZIP, full network GML, discovery store and venv | All confirmed ignored |
| Local Markdown link check | No broken local links |

Full official-source audit executed successfully (exit **0**):

```text
uv run --locked traffic-audit --start 2026-10-19 --end 2026-10-21 --output data/local/audit-20261019-21 --report reports/data_audit.json --daily --network --reuse
```

Original HTTP requests were performed before checksum-verified replay. The final
run reused preserved responses, parsed **all 3,121** snapshots again and inspected
the actual downloaded CENTERLINE. It returned `status=completed`, `errors=[]`.
Aggregate counts and source manifests live in `reports/data_audit.json`; recorded
stdout/progress are `reports/evidence/final_audit_stdout.json` and
`reports/evidence/final_audit_trace.txt`. Replay is not claimed to be a new HTTP
retrieval; provenance retains original per-response retrieval times.

The README's smaller live command was also executed after the full replay:

```text
uv run --locked traffic-audit --start 2026-10-19 --end 2026-10-21 --snapshots-per-day 3 --output data/local/smoke-audit --report reports/local/smoke-audit.json
```

Result: **exit 0**, `status=completed`, **9** historical snapshots parsed,
`errors=[]`. This verifies the individual-version download path separately from
daily ZIP handling. Its sparse selection is **not** a continuity estimate.

Other real commands executed:

```text
uv run --locked python scripts/probe_archive.py --source raw --time 20210329-0908 --time 20261026-2359 --output data/local/raw-boundary-probe --report reports/local/raw-boundaries.json
uv run --locked python scripts/probe_archive.py --source segment --time 20210330-0909 --output data/local/segment-boundary-probe --report reports/local/segment-boundary.json
uv run --locked python scripts/profile_sample.py --sample data/sample/verified/cleaned_sample.csv.gz --detectors data/sample/verified/detectors.csv --report reports/evidence/cleaned_sample_profile.json
```

- Raw boundary probe: **exit 1 as expected**; genuine empty earliest raw XML,
  recent raw version parsed 4,164 rows. Both responses downloaded successfully.
- Segment boundary probe: **exit 0**, 63 rows, all offline/masked. A successful
  parser exit is not a claim of usable measurements.
- Exported-sample profile: **exit 0**, 12,503 rows and 135 literal direction
  disagreements among 779 distinct observed detector-direction pairs.

## Testing boundaries and evidence checks

Routine tests make **no live government requests**. Transport integration tests
use an in-process local HTTP server with explicitly synthetic bodies and isolated
temporary paths. TEST* XML fixtures are labeled synthetic. Separate regression
tests inspect authentic checksummed source samples, including real conflicts and
the empty historical boundary response.

Verified behaviors: lane/segment XML parsing, midnight HK timestamp normalization,
required fields/types, offline/unknown validity, exact duplicate collapse, explicit
conflict quarantine/default failure, missing versus zero, invalid/nonfinite
numbers, paths with spaces/Unicode, checksum/reuse/no-overwrite, HTTP 404 body
preservation, 429 retry, timeout/network error evidence, empty/unexpected formats,
archive URL encoding/truncation, network key/CRS inspection and observation-time
(rather than capture-order) gap accounting.

Review found that capture order is not always observation order. Gap accounting
was corrected and regression-tested before the final replay: the final histogram
counts exactly `unique_observation_keys - lane_direction_series_count` transitions.
No accuracy/F1/AUC, detector spatial-matching success rate, events or labels were
computed. No claims of tests beyond the commands above are implied.

## Unverified platforms and limits

- **Native Windows and hosted GitHub Actions jobs remain pending CI.** The workflow
  matrix includes Ubuntu and Windows with Python 3.12, `uv sync --locked` and pytest.
- Actual local WSL2 execution is verified; native Windows behavior is not inferred
  from pathlib tests or a workflow file.
- Multi-year continuous data coverage, road topology/matching, context sources,
  event definitions and the final research cohort remain unverified. See
  `docs/data_audit.md` for scientific limitations and next-stage gates.
