### HS-20 tube heat sealer (`tube-sealer`)
**Split:** dev. **Revisions:** A, B, M1, M2.

A benchtop sealer that heat-seals the cap of one sample tube, with a one-tube stand beside it. You lift the tube from the stand into the sealing slot, flip the CLAMP lever up, and press SEAL; the display counts down 5 seconds and shows `DONE`, and the status light goes white, amber, green (red on a refusal).

**Controls:** CLAMP lever (toggle), SEAL button, sealing slot (sensed), tube stand, one tube, display and status light. No power switch.
**Theory pieces:** requires (SEAL needs a seated tube, shown as `NO TUBE`, and the clamp closed, shown as `CLAMP`), a sensed container and an object (pick and place), a latching toggle that isn't power, a momentary button, displays (message and countdown; light colour by mode), a timed `running` mode, and two roots.
**Faults:** F1 firmware: SEAL runs with no tube in the slot (the tube check is missing). F2 mechanical: the slot's bore is too tight, so a tube stops high and isn't sensed. F3 ergonomic: the CLAMP lever's spring is too stiff for a fingertip push to throw. F1 is masked by F3: with the clamp stuck open, SEAL on an empty slot is refused with `CLAMP`, which the manual allows, so the missing tube check never shows. M1 fixes F3 alone to unmask it (the clamp closes, and SEAL then seals an empty slot); M2 has F1 alone.
