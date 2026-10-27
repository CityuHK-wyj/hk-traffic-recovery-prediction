# Four-member development handoff — October 28–29

**Goal:** independent implementation while project lead is unavailable; core
experiments due **November 4, 2026**, poster **November 6–7**. All four share
scientific design/review. This allocation temporarily assigns Member 3 frontend
instead of external context, and Member 4 the API in addition to modelling, per the
current request. External data is deferred, not silently claimed complete.

## Current working vertical slice

- Read-only local FastAPI/DuckDB API in `src/traffic_recovery/api/app.py` queries
  actual checksummed medium-pilot Parquet. It serves 40 provisional lane events,
  detector metadata and 5-minute curves; no model is integrated. Synthetic offline
  tests in `tests/test_api.py`. Missing/corrupt inputs give 503, no substitute data.
- React/TypeScript/Vite in `frontend/` uses MapLibre/OpenStreetMap and ECharts.
  It selects events, shows detector location, speed, missing bins, retrospective
  horizon labels and a clearly unavailable prediction. It is not production-ready.
- Medium-pilot inputs under `data/local/pilot/medium-40/` are ignored local data.
  They are convenience samples with a two-day reference, not a research cohort.
  See [medium pilot](../medium_pilot.md), [contracts](../data_contract.md).
- Spatial directionality is **NO-GO for scientific ablation**: six candidates,
  [review packets](../../reports/spatial_pair_review/README.md), zero verified.
  [Spatial assessment](../spatial_feasibility.md). Traffic-only is primary.

## Parallel assignments

| Member | P0 ownership | Deliverable / earliest handoff |
|---|---|---|
| 1 | [`member1_data.md`](member1_data.md) | Audited cohort, versioned events/labels, documented fit/splits/coverage. |
| 2 | [`member2_network.md`](member2_network.md) | Human-reviewed six pair evidence and verified subset or explicit NO-GO. |
| 3 | [`member3_frontend.md`](member3_frontend.md) | Robust frontend and tests using agreed API; no backend changes without PR. |
| 4 | [`member4_models_backend.md`](member4_models_backend.md) | Local-only ML/evaluation scaffolding and read-only API; fit only after data gates. |

## October 28–29 execution order

1. Each member creates their own feature branch and opens a draft PR with the
   assigned scope, commands and blockers. Do not edit shared contracts or locks
   concurrently; propose changes in PRs. Never commit large local evidence.
2. Member 1 validates coverage and labels; Member 2 reviews the six candidate
   packets. Member 3 improves UI against the current read-only API. Member 4
   develops offline synthetic tests and evaluation interfaces without claiming
   research results or waiting on UI.
3. By end October 29, each posts an actionable PR status: passed/failed/not run,
   data hashes, unresolved decisions and next handoff. Avoid requiring lead input
   for reversible naming/UI choices. Record genuine scientific uncertainties.
4. By October 30–31, agree lane unit, prediction-time availability, labels,
   training-only reference and chronological event/embargo splits. If spatial
   sign-off fails, retain traffic-only. Freeze artifacts and checksums before ML.
5. November 1–3 run approved experiments and prepare report figures; **November 4**
   core experiments complete. November 6–7 poster (limitations and provenance).

## Run locally and integration

From repository root, use two terminals:

```text
uv sync --locked
uv run --locked uvicorn traffic_recovery.api.app:app --host 127.0.0.1 --port 8000
npm ci --prefix frontend
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Build/test:

```text
uv run --locked pytest
npm run build --prefix frontend
npm audit --prefix frontend
```

API needs local checked source artifacts; see root [README](../../README.md) for
paths and [medium_pilot.md](../medium_pilot.md) to reproduce. Missing evidence
returns HTTP 503. OSM tiles require network and a suitable provider policy. Do not
expose the dev servers or commit data/secrets. [integration_plan.md](integration_plan.md)
contains schemas, merge order and release checklist. Native Windows/hosted CI and
interactive browser rendering still need separate verification.
