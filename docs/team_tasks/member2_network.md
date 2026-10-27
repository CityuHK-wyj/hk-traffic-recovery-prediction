# Member 2 — road graph, matching and spatial feasibility

## Mission and scope
Own `src/traffic_recovery/network/`, `tests/test_network*` and spatial evidence.
Independently review [six candidate packets](../../reports/spatial_pair_review/README.md).
Current candidates are **not** reviewed transitions: zero authorized features,
0/40 medium events with approved upstream/downstream observations. Traffic-only
is the default until evidence changes this.

## P0 by October 29
1. Inspect each `pair-N.md`, map, alternative candidates, intersection and TURN
   files. Cross-check authoritative geometry, two carriageways, elevation,
   detector lane/direction, and source dates, including all turn restrictions
   and direction disagreement. Identify missing historical source evidence.
2. Record per detector mapping and transition: `verified`, `rejected` or
   `ambiguous`; reviewer identity, review date, actual source/evidence URLs and
   hashes, reasoning, network version and justified inclusive/exclusive historical
   validity interval. Do not mark independent review if you did not perform it.
   Exact required row semantics live in `network/spatial_features.py` and tests.
3. Resolve neighboring detector dynamic observations and coverage at event-time;
   run `neighbor_features()` only on genuinely approved, compatible rows. Measure
   per-horizon common eligible events, unknowns and coverage, with and without
   spatial information. No forward data and no zero-imputation.
4. Publish a short GO/limited-GO/NO-GO decision with numerical denominator and
   coverage, unresolved cases, reproducible commands, and reviewer sign-off.
   Six source-supported candidates do not establish viable ablation.

## P1 if and only if evidence passes
Propose a minimal connected subset and network version compatibility plan; work
with Member 4 on exact common event cohort and identical temporal splits for both
ablation arms. Consider undirected proximity only as explicitly separate
exploratory feature, never rename as upstream/downstream; it does not satisfy RQ2.

## Acceptance and checks

```text
uv sync --locked
uv run --locked python -m traffic_recovery.network.verify_feasibility
uv run --locked python scripts/spatial_pair_review.py
uv run --locked pytest -q tests/test_network.py tests/test_network_pilot.py tests/test_network_feasibility.py tests/test_network_spatial_features.py
```

Source files and local graph artifacts must exist; see `docs/spatial_feasibility.md`.
Tests validate structural constraints, not human review or real navigability. A
verified row requires evidence, reviewer and justified validity; unknown => null.
Keep review packets reproducible and source geometry/checksums intact. Ask Member 1
for cohort timing and Member 4 for ablation support; do not modify their modules.
Use `feature/member2-network-<topic>`, draft PR and independent review; no push or
merge without authorization. If historical validity or actual connectivity cannot
be established, record NO-GO by October 31 and release Member 4 to traffic-only.
