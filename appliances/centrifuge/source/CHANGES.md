# MC-6 — changes, v6 (old `centrifuge_cad_v6`) → v7 (this folder)

## Mechanical
- **Buttons:** the 3 printed bezels + laser caps + 12 mm tactile switches are gone. START, STOP and TIME+ are now 16 mm panel pushbuttons (same as the microwave) in 16.2 mm holes in the control face, nut behind. Bodies: `button_*` (fixed) + `cap_*` (moving). Cap travel 1.5 mm, click at 1.0 mm (was 0.3 mm travel).
- **Control face** re-cut for the 16.2 mm holes (bayonet notches removed). Its old cap discs are no longer cut.
- **Sensors:** the MOC7811 slotted switches and their mounts are replaced by Grove Light Sensors v1.2 (20 × 20 mm boards):
  - lid sensor on the inside of the left side panel, facing the lid fin (3.9 mm gap when closed);
  - tube sensor flat on one riser under well A, looking up (the second riser, `riser_2`, is removed).
- **Pico removed:** no `pico_frame`, no Pico engraving on the base. The Arduino Uno + shield + breadboard sit outside the centrifuge.
- **POWER toggle lever** is its own body now (`ref_toggle_lever`), so it can be animated.
- **Fault F1 (Stop bezel) dropped.** F2 and F3 unchanged.
- Everything else (box, lid, hinge, wells, rack, tubes, placement) is unchanged from v6.

## Electronics
- Raspberry Pi Pico → Arduino Uno + Grove Base Shield v2.
- Pins: START D2, STOP D3, TIME+ D4, POWER D5, ring D6, SPEED A0, lid light A1, tube light A2, OLED I2C (header A4/A5).
- Channel names are unchanged (`power`, `btn_start`, `btn_stop`, `btn_time`, `speed`, `lid`, `tube`, `run`, `time`).
- New behaviour vs. `device.yaml`'s state machine: STOP in READY resets the time to 30 s; opening the lid during a run aborts it (`run:"abort:LID"`, red, `LID`); DONE also times out to READY after 60 s.

## Checks run on v7
- 23/23 feasibility checks pass, Rev A and Rev B; zero solid overlaps in either.
- Full-travel sweep of each button cap: no collisions.
