# MW-1 — change list

This is the first MW-1 in the repo; the list is against the earlier Onshape design (`step/originals_onshape/Frame.step`, `Hinge.step`) and our v3 laser build.

## v4 (this folder)
- **Door sensor:** MOC7811 slotted switch + the door fin → Grove Light Sensor v1.2 standing on the sensor shelf, facing the door. The shut door's plywood shades it. The `door_fin` part and its slot in the door are gone.
- **Controller:** Raspberry Pi Pico + half breadboard → Arduino Uno + Grove Base Shield v2 on the base in the bay (engraved ARDUINO mark). No breadboard.
- **Buzzer added** (Grove Buzzer on port D8, engraved BUZ mark in the bay): key beep, DONE beeps, refused beeps. Earlier notes called it a sound sensor on A1; it's a buzzer and it's on D8.
- **Rev B hinge added** (fault fix): 0.25 mm pin clearance, 0.4 mm knuckle gaps, pin with a head on one end only. Rev A is the Onshape hinge unchanged.
- **Button caps split** from their housings in the STEP so they can move.
- STEPs exported in the sim frame (front = +X, origin at the base's bottom-face centre).

## v3 (earlier)
- Box trimmed to fit two 600 × 300 plywood sheets: 244 × 138 × 142 mm.
- Grove LCD RGB, 5 × 16 mm panel buttons, printed snap latch (no magnets), engraved front.
