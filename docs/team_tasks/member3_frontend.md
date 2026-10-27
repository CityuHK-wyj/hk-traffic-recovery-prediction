# Member 3 — frontend event explorer

## Mission and scope
Own `frontend/` (React/TypeScript/Vite, MapLibre, ECharts). This is a temporary
assignment replacing external-context work; coordinate with the team before
resuming `external/`. Consume the documented read-only API, do not fork data or
change backend schemas unilaterally. Target a usable, accurate research explorer.

## P0 by October 29
1. Run the slice and manually check event selection, 404/503, loading/empty state,
   selected lane and map location, HKT times, recovery/censor labels, speed curve,
   missing bins and prediction-unavailable message. Verify map failure and keyboard
   navigation/responsive layout. Capture pass/fail/browser/OS, not invented results.
2. Add offline component/integration tests with explicitly synthetic fixtures for
   nulls, unavailable predictions, unknown outcome, out-of-order request handling,
   map error and post-prediction observations. Keep genuine observations separate.
3. Improve UX and accessibility: filter/pagination as needed, meaningful event IDs,
   units, qualitative data quality, map attribution and provenance. No claims of
   historical datum accuracy or verified directed network links.
4. Provide visible separate retrospective outcome and prediction displays; only
   render actual model probabilities after Member 4 integrates provenance-checked
   predictions. Never treat labels as forecasts, null as zero, or mock as real.

## P1 and interfaces
- Add available model version/fit cutoff/horizon display under an agreed shared PR;
  make no assumptions about a model until API returns evidence. Review semantics in
  [integration_plan.md](integration_plan.md); API `values` is currently null.
- Support many events without loading giant files into the browser; use bounded API
  pagination. Map tiles currently call the public OSM service: development use only;
  consult its usage policy before any public hosting.
- Request backend changes from Member 4 with response examples and tests; don't
  alter data, modelling or topology. No deployment, secrets or third-party analytics.

## Run and acceptance

```text
uv sync --locked
uv run --locked uvicorn traffic_recovery.api.app:app --host 127.0.0.1 --port 8000
npm ci --prefix frontend
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173
npm run build --prefix frontend
npm audit --prefix frontend
```

See root README for missing local real-data evidence. An offline API-fixture mode
may be added **only** when visibly labelled synthetic. Record browser smoke results;
existing smoke tested HTTP/Vite proxy but not interactive rendering. Acceptance:
build/tests pass; no uncaught crash on null/503; map caveat and attribution shown;
future curve/outcomes clearly retrospective; nothing visually claims model or
network verification. Existing bundle is large; code-splitting is a P1 improvement.
Create `feature/member3-frontend-<topic>`, draft PR, record commands and blockers;
do not push/merge without authorization.
