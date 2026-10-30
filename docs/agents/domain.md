# Domain documentation

This repository uses a single-context domain documentation layout.

## Before domain-sensitive work

Read the following material when it exists and is relevant:

- `GLOSSARY.md` at the repository root for project terminology.
- ADRs under `docs/adr/` for accepted architectural and scientific decisions.
- `docs/data_contract.md` for shared keys, units, availability and modeling contracts.
- `docs/ownership.md` for module ownership and handoff gates.

Missing glossary or ADR files are expected. Continue without creating placeholders; use the domain-modeling workflow when the team actually resolves a new term or decision.

## Layout

```text
/
|-- GLOSSARY.md
|-- docs/
|   |-- adr/
|   |   |-- 0001-example-decision.md
|   |-- data_contract.md
|   `-- ownership.md
`-- src/
```

## Vocabulary and decisions

Use terms as defined in `GLOSSARY.md`. If a needed concept is absent, first check the existing data contract and source terminology; record a genuine vocabulary gap for domain modeling instead of silently inventing a synonym.

Surface conflicts with an existing ADR explicitly. Cite the ADR and explain why the decision may need to be revisited rather than overriding it implicitly.
