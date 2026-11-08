# MC-6 mini centrifuge — source files (v7, November 2026)

Everything needed to rebuild the sim model and the real unit. Replaces `centrifuge_cad_v6/`, `sim/`, the old Pico-era `device.yaml` copy and the old manual PDF (git has them).

**Units: mm. Frame: the product frame of `device.yaml`** — origin at the centre of the base's bottom face, +X toward the arm (front), +Y to the operator's right, +Z up.

## What's here
| Path | What |
|---|---|
| `step/mc6_revA.step`, `step/mc6_revB.step` | Full assembly, one named solid per part, mm, product frame. Rev A has the faults, Rev B is fixed. Parts that differ carry `_revA` / `_revB` in their name. Bought electronics are `ref_*` placeholders. |
| `step/bodies.csv` | Every body: part, kind (laser / print / bought), material, whether it moves, volume, estimated mass. |
| `motion.md` | How each moving part moves: buttons, dial, toggle, lid, rack cover, tubes. |
| `electronics/electronics.md` | Channel table, display and light behaviour, what each button does in each state. Schematic and port map next to it. |
| `../firmware/MC6_firmware/` | The Arduino controller code (beside this folder, as asked). |
| `manual/` | The user manual as it ships (PDF + text). No faults or revisions in it. |
| `faults.md` | Answer key: F2 lid handle, F3 well A. F1 dropped. |
| `logistics.md` | Bench placement, clamping, size, weight, forces. |
| `CHANGES.md` | v6 → v7 change list. |
| `laser/` | DXFs, 3 mm plywood and 3 mm clear acrylic. `1_single_parts_nominal/` = true size, one file per part (`__x4` = cut 4). `2_nested_sheets_kerf_applied/` = ready-to-cut 600 × 300 sheets (kerf 0.15 mm, outside +0.075, holes −0.075). Layers: CUT (red), ENGRAVE (blue). |
| `print/` | STLs, flat on the bed, PLA. `well_insert_A_revA/revB` are the F3 pair; print the one you want. |
| `photos/` | Renders (no real photos of the v7 build yet) and the control face drawing. |

## Building notes
- The nested plywood sheet includes **both** lid-handle versions (Rev A: `lid_handle_revA_*`, Rev B: `lid_handle_revB_ply`). Glue up the one you want.
- Hinge pins are 1.75 mm PLA filament, cut to length.
- Bought: 3 × 16 mm momentary panel buttons, SPDT mini toggle, WH148 10 kΩ pot, 24-LED WS2812B ring, SSD1306 0.96" OLED, 2 × Grove Light Sensor v1.2, Arduino Uno + Grove Base Shield v2, half breadboard.

## Assumptions (things nobody has measured)
- Button force ~3 N, toggle ~2–3 N, pot torque ~0.01–0.02 N·m: typical datasheet values.
- Mass from CAD volume and nominal densities; the real unit hasn't been weighed.
- Placement, stand height and clamping are copied unchanged from the repo's `device.yaml`.
- Light-sensor thresholds (55 % / 70 % of the open level) need checking on the real build; they're `const`s in the firmware.
- `device.yaml`, `verify.yaml`, `wiring.md` and `build/` in the repo were not touched. They still describe the Pico, the MOC7811s and F1, and need regenerating from these files.
