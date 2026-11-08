# MW-1 mock microwave — source files (v4, November 2026)

**Units: mm. Frame (STEP): sim frame** — origin at the centre of the base's bottom face, **+X toward the arm (the door / front)**, +Y to the right seen from the front, +Z up.

The design CAD (`microwave.py`) used a front-is-−Y frame. Design → sim is a +90° turn about Z plus a shift:

```
x_sim = 62  − y_design
y_sim = x_design − 115
z_sim = z_design
```

## What's here
| Path | What |
|---|---|
| `step/mw1_revA.step`, `step/mw1_revB.step` | Full assembly, one named solid per part. Rev A has the hinge fault, Rev B is fixed; the hinge parts carry `_revA` / `_revB`. Bought parts are `ref_*` (LCD, Uno, buzzer, light sensor, button housings `ref_button_*` and moving caps `ref_cap_*`). |
| `step/bodies.csv` | Every body, material, group (door / body / hinge / pin), volume, estimated mass. |
| `step/originals_onshape/` | The Onshape `Frame.step` and `Hinge.step` this was built from. |
| `motion.md` | Door hinge axis, range, latch; button travel and click point. |
| `electronics/electronics.md` | Channel table, display/backlight/buzzer behaviour, what each button does in each state, the wiring change. |
| `../firmware/MW1_firmware/` | The Arduino controller code. |
| `manual/` | User manual as it ships (PDF + text). No faults or revisions in it. |
| `faults.md` | Answer key: F1 hinge. |
| `logistics.md` | Proposed bench placement, clamping, size, weight, forces. |
| `CHANGES.md` | Change list. |
| `laser/` | DXFs: 3 mm plywood (2 sheets) and 3 mm clear acrylic (1 sheet), 600 × 300. `1_single_parts_nominal/` true size, `2_nested_sheets_kerf_applied/` ready to cut (kerf 0.15). Layers CUT and ENGRAVE. Parts engraved on their outside face are mirrored in the DXF so the engraving ends up outside. |
| `print/` | PLA STLs. Hinges: print the `revA` or `revB` set, 2 of each part. The hinge STLs are in assembly orientation; lay them flat in the slicer. The catch is already on its side. |
| `photos/` | Renders (no photos of the v4 build yet). |

## Bought parts
5 × 16 mm momentary panel buttons, Grove LCD RGB Backlight v4.0, Grove Light Sensor v1.2, Grove Buzzer, Arduino Uno + Grove Base Shield v2, 2 × M4 screws (handle), USB-B cable.

## Assumptions
- Placement isn't decided: there's no `microwave/device.yaml` or registry entry yet. `logistics.md` has a proposal (front toward the arm, clamped).
- Button force ~3 N is typical, not measured. The latch force (~4.3 N) comes from the CAD spring-arm calculation.
- Mass is estimated from CAD volume plus typical bought-part weights.
- Light-sensor thresholds (55 % / 70 %) need checking on the real build.
- Rev B door range (~145°) is from the CAD collision sweep; the manual quotes 130° (Rev A).
