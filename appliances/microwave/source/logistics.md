# MW-1 — bench placement, mounting, weight, forces

## Placement (proposed — the microwave isn't in `registry.json` or any `device.yaml` yet)
- **Front (door + control panel) faces the arm**, i.e. the STEP's +X points at the arm base. In the world frame that's yaw 180° if the microwave sits on the arm's +X side, like the centrifuge.
- Distance: put the door face ~250–300 mm from the arm base, so the handle (x ≈ 65–90 in the STEP) and all five buttons are inside the SO-101's reach. Not tested in the sim yet; adjust after a reach check.
- The door opens toward the arm and to the left (−Y side). Keep ~140 mm clear on that side and in front for the full 130° swing.
- **Clamp it** to the bench (the base overhangs the walls by 4 mm on every side; clamp the base edge at the back or right). Pulling the door needs ~4 N; unclamped, a ~0.5 kg box would slide.
- Same 82 mm stand board as the centrifuge if it shares the desk.

## Size
244 (Y) × 138 (X) × 142 (Z) mm; the handle sticks out a further 25 mm in front. STEP box: x −69…69, y −122…122, z 0…142.

## Weight
| | |
|---|---|
| Structure (CAD: plywood, acrylic, PLA) | 378 g |
| Bought parts (Uno + shield, LCD, 5 buttons, light sensor, buzzer, wires) | ~150 g |
| **Total, estimated** | **~0.53 kg** (not weighed) |

## Forces (assumed unless noted)
| Part | Force |
|---|---|
| Door latch | ~4.3 N peak to pull open (from the CAD: spring arm 4.33 N/mm, 1.0 mm bump lift) |
| Door swing | free, stays where left (Rev B); Rev A: stiff or seized (see faults.md) |
| Buttons | ~3 N, click at 1.0 mm of 1.5 mm travel |
