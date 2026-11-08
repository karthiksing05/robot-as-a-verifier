### MC-6 mini centrifuge (`centrifuge`), the reference device
**Split:** dev. **Revisions:** A, B, M1.

A benchtop mini centrifuge (v7: Arduino Uno, 16 mm panel buttons, light sensors) with a separate four-position tube rack. You take a tube from the rack into well A, close the lid, set the time and speed, and run it; the display counts down and the light ring shows the state.

**Controls:** POWER toggle; START, STOP and TIME+ buttons; SPEED dial (270°, no detents); lid handle; rack cover lip; display and light ring; wells A and B; two tubes.
**Theory pieces:** enables (power), interlocks (open lid blocks START and aborts a run, shown as `LID`), requires (a seated tube, shown as `TUBE`), drives (dial to speed, TIME+ to time, STOP resets it), displays (speed and time; ring colour by mode), momentary and latching returns, two hinge mechanisms, a sensed container and objects, a timed `running` mode and a timed return from `done`.
**Faults:** F2 ergonomic: the lid handle is a pinch fin with no lip to hook. F3 mechanical: well A is too tight (Ø15.6 mm for a 16 mm tube), so the tube sits high and isn't sensed. F3 is masked by F2 (the lid can't be opened), and M1 fixes F2 alone to unmask it.
**Source notes (manual vs firmware, kept as the firmware does it):** the display reads `1000rpm` / `0:30` where the manual shows `1000 RPM 0:30`; at power-on the speed is wherever the dial is, not 1000 rpm; after a `TUBE` refusal, seating the tube and pressing START again gives `TUBE` until STOP or TIME+ brings back READY (the tube light is only read under steady white); TIME+ stops at 10:00 rather than wrapping.
