# Four-member architecture and working agreement

| Owner | Package / test prefix | Responsibility and first deliverable after this milestone |
|---|---|---|
| Member 1 — Traffic Data Engineering | `src/traffic_recovery/data/`, `tests/test_traffic*`, `tests/test_acquisition*`, `tests/test_quality*` | Historical acquisition, parsing, missingness, events and recovery labels. Next: coverage-filtered pilot and justified label definitions. |
| Member 2 — Road Network and Spatial Analysis | `src/traffic_recovery/network/`, `tests/test_network*` | Official roads, directed graph, detector-road matching, upstream/downstream and spatial features. Next: version reconciliation and a manually checked small matching pilot. |
| Member 3 — Frontend (temporary integration assignment) | `frontend/` | Event explorer, MapLibre, observation quality and ECharts. External/context work remains optional and deferred; coordinate any future change with the team. |
| Member 4 — ML, Evaluation and API | `src/traffic_recovery/models/`, `src/traffic_recovery/api/`, `tests/test_models*`, `tests/test_api*` | Temporal baseline/evaluation and local FastAPI integration; actual research model fitting awaits approved cohort/labels/splits. |

Temporary allocation follows the current user-requested handoff: Member 3 owns the frontend rather than external context, and Member 4 owns API integration in addition to models. Confirm with the team at the next meeting. Names are placeholders for the team's assignment, not inferred identities. All four
participate in research design, verification, documentation and the poster.
Package markers for external/models deliberately reserve boundaries without adding
speculative implementations or heavy dependencies. The road audit is limited to
schema/identifier inspection, not matching or graph construction.

## Milestone-2 handoff (review pending)

Member 1 now supplies `data/coverage.py`, `pilot_ingest.py`, `events.py` and
`pilot.py`; Member 2 supplies `network/pilot.py`. Member 3's external module and
Member 4's model module remain unchanged. Contract v0.2 records a **lane-unit**
pilot and explicit outcome/feature separation, not approved segment-level labels.
Member 1/4 must approve censoring, normal-speed reference and temporal splits;
Member 2 must manually review maps, directions, turn handling and version validity.
No PR approval is implied by implementation or passing tests. No ML was started.

## Shared interface changes

- `docs/data_contract.md` is the shared proposal registry. Changes to identifier
  semantics, timezone, feature availability, sampling, label policy or file format
  require coordination with affected owners and a reviewed PR.
- Each owner supplies data through documented tables/files, not private imports
  into another module. Reuse the acquisition transport where appropriate.
- The current raw parser and quality report are implemented APIs; event, network
  feature, context, ML and experiment tables remain proposals.
- Test public parsing/cleaning, acquisition/provenance and quality boundaries.
  Synthetic fixtures test behavior, never scientific feasibility. Routine CI is offline.
- Keep PRs within a module where possible; shared `pyproject.toml`, `uv.lock`,
  `AGENTS.md`, CI and contracts are coordinated files. Do not regenerate the lock
  casually while working on unrelated modules.
- Use feature branches, small reviewed PRs and passing tests. Do not commit
  local data stores, secrets or trained artifacts. No direct main pushes.

## Handoff gates and schedule

1. **This milestone:** audited source evidence and architecture, complete.
2. **Next:** jointly approve prediction unit, coverage policy, event/label rules,
   availability semantics and network version. Each owner runs a small handoff
   validation, including censored horizons and ambiguous lane keys.
3. Freeze a modest, traceable pilot cohort; agree temporal/event split boundaries
   and fitted-transform rules before feature/model comparison.
4. Complete core experiments by **November 4, 2026**; preserve configs, data hashes,
   seeds, software versions and results. Reserve **November 6–7** for poster work.

Given the short schedule, prefer a valid local-only baseline and a small defensible
spatial ablation over unverified enrichment or complex models. Findings may justify
a narrower cohort or scope, but never invented data or performance.
