# Executable experiment contract v1

`configs/experiment_contract.json` freezes the executable candidate interface for
model-ready event rows. It does **not** change the scientific status of the lane
event definition, censoring policy or split boundaries: Member 1 and Member 4
review remains required before model results are presented as research findings.

## Frozen candidate

- Grain: one unique `event_id` per row at its aware Hong Kong `prediction_time`.
- Outcomes: nullable `label_15m`, `label_30m` and `label_60m`; missing means
  censored/unknown and is never converted to zero.
- Splits: chronological `train`, `validation`, `test` and `purged` using the
  configured boundaries. Every non-purged maximum-horizon window must end before
  its next boundary.
- Features: only names listed under `feature_groups` may enter a model. Outcome
  times, recovery state, label/reason fields and later observations remain outside
  the allowlist.
- Availability: every present group watermark listed in `availability_columns`
  must be no later than `prediction_time`.

`traffic_recovery.models.contract` validates these rules and selects known-label
rows for a requested horizon without admitting outcome columns. It also records
SHA-256 hashes for the exact event Parquet and contract configuration.

## Validate a frozen cohort

The repository currently does not contain the ignored full pilot cohort. After
Member 1 produces and hands off the approved event Parquet, run:

```text
uv run --locked python scripts/validate_experiment_contract.py --events data/local/pilot/derived/events.parquet --report reports/local/experiment-contract.json
```

The command refuses to overwrite an existing report. A successful manifest records
the input and contract hashes, row/known-label counts, contract approval status and
software versions. Preserve that manifest with every later experiment run.

## Approval gate

Before training, the team must review the prediction unit, reference fit,
censoring, split dates and event separation. Change the configuration's
`scientific_approval` only in the reviewed PR that records that decision. Passing
software tests alone is not scientific approval.
