# MC-6 — how each moving part moves

Units mm and degrees. Coordinates are the product frame used by the STEP files and `device.yaml`: origin at the centre-line of the base's bottom face, **+X toward the arm (front)**, +Z up. The control face is sloped 45°; its outward normal is **n = (0.7071, 0, 0.7071)**.

Body names match the STEP (`step/bodies.csv`). Bodies starting with `ref_` are bought electronics.

## Buttons — START, STOP, TIME+ (16 mm panel pushbuttons, momentary)
| | START | STOP | TIME+ |
|---|---|---|---|
| Moving body | `cap_start` | `cap_stop` | `cap_time` |
| Fixed housing | `button_start` | `button_stop` | `button_time` |
| Cap top centre (released) | (46.04, −22.86, 80.04) | (46.04, 0, 80.04) | (46.04, 22.86, 80.04) |

- Cap: Ø13 mm, top 5 mm proud of the control face, inside an Ø18 mm fixed ring.
- Press direction: **−n** = (−0.7071, 0, −0.7071).
- **Travel 1.5 mm** to the hard stop. **Switch closes at about 1.0 mm.**
- Momentary, spring return. Force about 3 N (assumed; typical for 16 mm panel buttons, not measured).
- All three are the same part now. There is no bezel or twist-lock any more.

## SPEED dial
- Moving body: `dial_knob` (knob with a pointer fin) on a 10 kΩ pot (`ref_pot`).
- Knob (v7.2, 2× the v7 knob): Ø20 mm hub, fin 6 mm wide reaching 18 mm from the axis, 12 mm tall (4 × 3 mm plies). Its underside sits 5 mm above the control face.
- Axis: along n, through the pot shaft at y = 50.5 on the control face's centre line.
- Nothing touches anywhere in the 360° sweep, and the fin never passes over the TIME+ cap (min gaps: TIME+ housing 3.1 mm, TIME+ cap 3.1 mm, control face and side panel 5 mm).
- **Range 270°.** Joint angle q runs from 0 (minimum, 1000 rpm) to −270° (maximum, 6000 rpm) about +n, i.e. **clockwise seen from the front raises the speed**.
- Hard end stops at both ends (the pot's own stops).
- **No detents.** It's continuous; the firmware rounds to 50 steps of 100 rpm. Light friction, stays where it's left.
- Turning torque about 0.01–0.02 N·m (assumed, typical WH148 pot).

## POWER toggle (SPDT, latching)
- Moving body: `ref_toggle_lever` (split out of `ref_toggle` in v7). Fixed body: `ref_toggle`.
- Pivot (bushing) at about (46.74, −50.5, 80.74); hinge axis (0, −1, 0).
- **Throw 30°** total: q = 0 leaning toward the bottom edge of the face = **OFF**; q = 30° toward the top edge = **ON**.
- **Latching**, snaps over centre at 15°: it stays in whichever end it's pushed to.
- Lever about 10 mm long from the pivot, Ø3 mm. Force at the tip about 2–3 N to flip (assumed).

## Lid
- Moving group: `lid`, `lid_hinge_leaf`, `lid_handle_revA`/`lid_handle_revB`, `lid_sensor_fin`. Fixed: `lid_hinge_base`, `lid_hinge_pin`.
- Hinge axis (0, −1, 0) through (−56.5, y, 102), at the back.
- **Range 0–105°.** Closed at 0. Opening lifts the front.
- **Closes under its own weight**; no latch, no spring. Past vertical it rests open on its stop at 105°.
- Lifted by the lid handle (see faults.md for how Rev A and Rev B handles differ).
- `lid_sensor_fin` hangs down beside the lid light sensor; closed = sensor shaded (fin gap 3.9 mm).

## Rack cover (MC-R4)
- Moving group: `rack_cover`, `rack_hinge_leaf`, `rack_cover_lip`. Fixed: `rack_hinge_base`, `rack_hinge_pin`.
- Hinge axis (−0.64, −0.77, 0) through (60.39, 179.66, 86.2).
- **Range 0–105°**, closes under its own weight, rests open past vertical. No latch. Lift by the lip.

## Tubes
- `tube_1`, `tube_2` (one print file, ×2). Loose objects. Ø16 mm body, 55 mm long, with a collar and a top loop.
- Seated in well A = collar resting on the well; the tube bottom then sits 3.2 mm above the tube light sensor and shades it.

## Fixed parts
Everything else is fixed to `base_plate` (the centrifuge) or `rack_base` (the rack).
