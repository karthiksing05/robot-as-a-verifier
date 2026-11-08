# MC-6 — bench placement, mounting, weight, forces

## Placement (unchanged from `device.yaml`)
- Centrifuge product origin at **x = 313.3 mm, y = 0** from the arm base, **yaw 180°**, so its front (+X, control face and display) faces the arm.
- It stands on an **82 mm board** on the desk (the sim's arm is 140 mm above its desk; the CAD expects 58 mm).
- The MC-R4 rack sits at its CAD position beside the centrifuge (product-frame bodies `rack_*`, around x 21–133, y 106–225).
- **Both clamped** to the bench: the centrifuge by its rear base lip, the rack by its base.
- The Arduino + breadboard sit behind the centrifuge, out of the arm's way. Keep the USB cable and the jumper bundle behind the back panel.

## Size
- Centrifuge: 144 (X) × 133 (Y) × 118 (Z) mm, product-frame box x −80…64, y −66.5…66.5, z 0…118.
- Rack: 112 × 118 × 102 mm box (x 21…133, y 106…225).

## Weight
| | CAD estimate (wood, acrylic, PLA) | + bought parts | `device.yaml` (sim) |
|---|---|---|---|
| Centrifuge | 182 g | ~70 g (3 buttons, toggle, pot, OLED, ring, 2 sensors, wires) → **~0.25 kg** | 0.75 kg |
| Rack + cover | 71 g | 2 tubes ~10 g → **~0.08 kg** | 0.2 kg |

Plywood taken as 600 kg/m³, acrylic 1190, PLA 1240 at 100 % infill (prints are lighter). Nobody has weighed the real build yet; the sim values are larger and harmless while both are clamped.

## Forces (assumed, not measured)
| Part | Force |
|---|---|
| START / STOP / TIME+ caps | ~3 N, click at 1.0 mm of 1.5 mm travel |
| POWER toggle | ~2–3 N at the lever tip |
| SPEED dial | ~0.01–0.02 N·m, no detents |
| Lid | lifts against its own weight, ~60 g at the front lip ≈ 0.3–0.4 N; no latch |
| Rack cover | own weight only, no latch |
| Tube into well A | Rev B: drops in under its own weight; Rev A: won't seat |
