# Candidate 6: AID01111 → AID01112

**PENDING — no human verification, no approved feature use.** Arrows are candidate travel directions, not certified upstream/downstream relationships.

- Candidate arcs: `104992:F` → `105213:F`; shared endpoint `(836697.47, 818389.34, '0')`; source intersection `23025`.
- Source endpoint elevation: `0`; intersection evidence: [CSV](pair-6-intersection.csv).
- 0 TURN records reference either route (not necessarily this movement): [complete rows](pair-6-turns.csv).
- [Detailed map](pair-6.png) and [all 50 m detector alternatives](pair-6-alternatives.csv).
- Network identifier: `centerline-sha256:4fad0303e65c759ac7abe8eea3920b3ffcfcd5149c978fa9540bf032933a32c2`; source revision cut-off is not historical validity.

### AID01111: selected route 104992
- Feed direction: North East; current metadata direction: East; literal agreement: False.
- Source road: HONG CHONG ROAD; detector description: Hong Chong Road near The Hong Kong Polytechnic University - Northbound (1) ; name evidence: name_in_detector_description.
- Candidate distance: 11.12 m; bearing difference: 20.97°; ambiguity: False.
- Source travel-direction code: 3; elevation: 0; creation/update: 20090508200000 / 20220513151308.

### AID01112: selected route 105213
- Feed direction: North East; current metadata direction: East; literal agreement: False.
- Source road: HONG CHONG ROAD; detector description: Hong Chong Road near The Hong Kong Polytechnic University - Northbound (2) ; name evidence: name_in_detector_description.
- Candidate distance: 4.09 m; bearing difference: 23.77°; ambiguity: True.
- Source travel-direction code: 3; elevation: 0; creation/update: 20090508200000 / 20220513151611.

## Independent reviewer checklist

- [ ] Verify both detector coordinates, physical carriageway and historical effective dates against authoritative evidence.
- [ ] Resolve feed-versus-metadata direction, local line bearing, lane orientation and all plausible alternatives.
- [ ] Confirm source route geometries meet at the actual junction and are on the same navigable level.
- [ ] Inspect every applicable TURN row, including EDGE1END, positions, vehicle/time restrictions and multi-edge paths.
- [ ] Confirm this directed movement is permitted and source/network versions were valid at prediction time.
- [ ] Record decision (verified / rejected / ambiguous), reviewer, evidence URLs/checksums, method and validity interval.
- [ ] If anything is unresolved, retain `pending`; do not feed this pair into directed spatial features.
