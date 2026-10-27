# Candidate 1: AID01114 → AID01115

**PENDING — no human verification, no approved feature use.** Arrows are candidate travel directions, not certified upstream/downstream relationships.

- Candidate arcs: `104767:F` → `104875:F`; shared endpoint `(836437.88, 819854.5, '0')`; source intersection `22530`.
- Source endpoint elevation: `0`; intersection evidence: [CSV](pair-1-intersection.csv).
- 0 TURN records reference either route (not necessarily this movement): [complete rows](pair-1-turns.csv).
- [Detailed map](pair-1.png) and [all 50 m detector alternatives](pair-1-alternatives.csv).
- Network identifier: `centerline-sha256:4fad0303e65c759ac7abe8eea3920b3ffcfcd5149c978fa9540bf032933a32c2`; source revision cut-off is not historical validity.

### AID01114: selected route 104767
- Feed direction: North East; current metadata direction: North; literal agreement: False.
- Source road: PRINCESS MARGARET ROAD; detector description: Princess Margaret Road near Oi Man Estate - Northbound ; name evidence: name_in_detector_description.
- Candidate distance: 12.68 m; bearing difference: 35.37°; ambiguity: True.
- Source travel-direction code: 3; elevation: 0; creation/update: 20090508200000 / 20090508200000.

### AID01115: selected route 104875
- Feed direction: North East; current metadata direction: North East; literal agreement: True.
- Source road: PRINCESS MARGARET ROAD; detector description: Princess Margaret Road near Yu Chun Keung Memorial College - Northbound ; name evidence: name_in_detector_description.
- Candidate distance: 0.39 m; bearing difference: 18.76°; ambiguity: True.
- Source travel-direction code: 3; elevation: 0; creation/update: 20090508200000 / 20090508200000.

## Independent reviewer checklist

- [ ] Verify both detector coordinates, physical carriageway and historical effective dates against authoritative evidence.
- [ ] Resolve feed-versus-metadata direction, local line bearing, lane orientation and all plausible alternatives.
- [ ] Confirm source route geometries meet at the actual junction and are on the same navigable level.
- [ ] Inspect every applicable TURN row, including EDGE1END, positions, vehicle/time restrictions and multi-edge paths.
- [ ] Confirm this directed movement is permitted and source/network versions were valid at prediction time.
- [ ] Record decision (verified / rejected / ambiguous), reviewer, evidence URLs/checksums, method and validity interval.
- [ ] If anything is unresolved, retain `pending`; do not feed this pair into directed spatial features.
