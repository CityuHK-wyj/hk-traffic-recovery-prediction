# Four-member architecture and working agreement

| Owner | Package / test prefix | Responsibility and first deliverable after this milestone |
|---|---|---|
| Member 1 — Traffic Data Engineering | `src/traffic_recovery/data/`, `tests/test_traffic*`, `tests/test_acquisition*`, `tests/test_quality*` | Historical acquisition, parsing, missingness, events and recovery labels. Next: coverage-filtered pilot and justified label definitions. |
| Member 2 — Road Network and Spatial Analysis | `src/traffic_recovery/network/`, `tests/test_network*` | Official roads, directed graph, detector-road matching, upstream/downstream and spatial features. Next: version reconciliation and a manually checked small matching pilot. |
| Member 3 — External Data and Context | `src/traffic_recovery/external/`, `tests/test_external*` | Verify weather, holidays, incidents/closures; parking/attractions only if feasible. Next: source/availability audit before any contextual joins. |
| Member 4 — Machine Learning and Evaluation | `src/traffic_recovery/models/`, `tests/test_models*` | Baselines, Random Forest / XGBoost comparisons if justified, temporal splits, horizon evaluation, spatial ablation, interpretation and figures. Next: evaluation protocol, not model training until labels pass review. |

Names are placeholders for the team's assignment, not inferred identities. All four
participate in research design, verification, documentation and the poster.
Package markers for external/models deliberately reserve boundaries without adding
speculative implementations or heavy dependencies. The road audit is limited to
schema/identifier inspection, not matching or graph construction.

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
