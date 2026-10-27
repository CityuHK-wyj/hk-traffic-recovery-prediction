# Candidate 3: AID01125 → AID01127

**PENDING — no human verification, no approved feature use.** Arrows are candidate travel directions, not certified upstream/downstream relationships.

- Candidate arcs: `57654:F` → `57646:F`; shared endpoint `(836847.01, 825100.98, '0')`; source intersection `23255`.
- Source endpoint elevation: `0`; intersection evidence: [CSV](pair-3-intersection.csv).
- 0 TURN records reference either route (not necessarily this movement): [complete rows](pair-3-turns.csv).
- [Detailed map](pair-3.png) and [all 50 m detector alternatives](pair-3-alternatives.csv).
- Network identifier: `centerline-sha256:4fad0303e65c759ac7abe8eea3920b3ffcfcd5149c978fa9540bf032933a32c2`; source revision cut-off is not historical validity.

### AID01125: selected route 57654
- Feed direction: North East; current metadata direction: North East; literal agreement: True.
- Source road: LION ROCK TUNNEL ROAD; detector description: Lion Rock Tunnel Road near Worldwide Gardens - Northbound ; name evidence: name_in_detector_description.
- Candidate distance: 5.44 m; bearing difference: 3.89°; ambiguity: True.
- Source travel-direction code: 3; elevation: 0; creation/update: 20090508200000 / 20260120120253.

### AID01127: selected route 57646
- Feed direction: North East; current metadata direction: North East; literal agreement: True.
- Source road: LION ROCK TUNNEL ROAD; detector description: Lion Rock Tunnel Road near Kak Tin Village - Northbound (2) ; name evidence: name_in_detector_description.
- Candidate distance: 0.08 m; bearing difference: 4.31°; ambiguity: False.
- Source travel-direction code: 3; elevation: 0; creation/update: 20090508200000 / 20260120101849.

## Independent reviewer checklist

- [ ] Verify both detector coordinates, physical carriageway and historical effective dates against authoritative evidence.
- [ ] Resolve feed-versus-metadata direction, local line bearing, lane orientation and all plausible alternatives.
- [ ] Confirm source route geometries meet at the actual junction and are on the same navigable level.
- [ ] Inspect every applicable TURN row, including EDGE1END, positions, vehicle/time restrictions and multi-edge paths.
- [ ] Confirm this directed movement is permitted and source/network versions were valid at prediction time.
- [ ] Record decision (verified / rejected / ambiguous), reviewer, evidence URLs/checksums, method and validity interval.
- [ ] If anything is unresolved, retain `pending`; do not feed this pair into directed spatial features.
