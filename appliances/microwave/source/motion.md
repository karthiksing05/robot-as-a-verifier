# MW-1 — how each moving part moves

Units mm and degrees. Coordinates are the **sim frame** used by the STEP files: origin at the centre of the base's bottom face, **+X toward the arm (the front, door side)**, +Z up. Seen from the front (looking along −X), +Y is to the right, so the door hinges are on the −Y side and the control panel is on the +Y side.

(The design CAD used a different frame. The STEPs are already converted: rotate +90° about Z, origin moved to the base centre. The 4 × 4 matrix is in `README.md`.)

## Door
- Moving group: `door`, `door_window`, `door_strike`, `handle`, `hinge1_door_leaf_rev*`, `hinge2_door_leaf_rev*`.
- Fixed: `hinge1_wall_leaf_rev*`, `hinge2_wall_leaf_rev*`, `hinge1_pin_rev*`, `hinge2_pin_rev*` (pins sit in the wall leaves).
- **Hinge axis vertical**, through (66.9, −119.9), z 3 → 139. Axis direction (0, 0, −1) for positive = opening.
- **Range: 0 → 130°** (Rev A, then the hinge leaves meet). Rev B frees up to about 145°. The manual says "about 130°".
- Swings outward toward +X, to the left as seen from the front.
- **Stays where it's left.** Vertical axis, no spring, so it doesn't fall shut or fall open.
- **Snap latch when shut:** a printed spring arm (`door_catch`, on the catch shelf inside) drops a bump into a notch in `door_strike`. Bump lift 1.0 mm, arm stiffness ~4.3 N/mm → **~4 N to pull open** at the handle, and a click when pushed shut.
- Handle: `handle`, a D-handle on the door front near the free edge.
- Door light sensor: closed door shades the Grove Light Sensor on the sensor shelf (`ref_light_door`).

## Buttons (5 × 16 mm momentary panel pushbuttons)
| Button | Moving cap | Fixed housing | Cap front centre (released) |
|---|---|---|---|
| TIME | `ref_cap_TIME` | `ref_button_TIME` | (72.0, 48.3, 72.0) |
| POWER | `ref_cap_POWER` | `ref_button_POWER` | (72.0, 48.3, 47.0) |
| STOP | `ref_cap_STOP` | `ref_button_STOP` | (72.0, 48.3, 22.0) |
| +30s | `ref_cap_+30s` | `ref_button_+30s` | (72.0, 92.8, 72.0) |
| START | `ref_cap_START` | `ref_button_START` | (72.0, 92.8, 47.0) |

- Cap Ø13 mm and 5 mm thick, in front of an Ø18 mm ring; cap front 7 mm proud of the control panel (panel front face at x = 65).
- Press direction **−X**. **Travel 1.5 mm**, **switch closes at about 1.0 mm**. Momentary, spring return, ~3 N (assumed).

## Display
- Grove LCD RGB 16 × 2 behind a 71 × 24 mm window, window centre (65, 70.6, 108) on the panel front face. Not moving.

## Fixed parts
Everything else is fixed to `base`.
