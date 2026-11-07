# Mates to add in Onshape

Group everything glued or tabbed (panels, hinge bases, gussets, Pico frame, risers, lid sensor fin into the lid) and fix the base plate.

| Moving part(s) | Mate | Axis | Limits |
|---|---|---|---|
| Lid group: `lid`, `lid_hinge_leaf`, `lid_handle_revA/B`, `lid_sensor_fin` | Revolute | pin through (-56.5, y, 102.0), along Y | 0° to 105° (printed stop) |
| Rack cover group: `rack_cover`, `rack_hinge_leaf`, `rack_cover_lip` | Revolute | pin through [60.4, 179.7, 86.2], direction [-0.64, -0.77, 0.0] | 0° to 105° |
| `dial_knob` (4-ply stack) | Revolute | pot shaft through [49.9, 50.5, 83.9], direction [0.71, 0.0, 0.71] | 0° to 270° |
| `bezel_stop_revA/B` | Revolute (bayonet) | control face hole axis | 0° in the notch, 45° locked |
| `cap_stop` | Slider in the bezel | bezel axis | 0–0.3 mm |
| `cap_start`, `cap_time` (laser stacks) | Slider in the plain hole | hole axis | 0–0.3 mm |
| `well_insert_A_revA/B` | Revolute (bayonet) | vertical | 0° in the notch, 45° locked |
| `lid_handle_revA/B` (inside the lid group) | Slider | +X | 0 locked, 3 mm forward to unlock |
| `tube_1`, `tube_2` | Cylindrical | well axis | rests on its collar |

Swap sequences:
- **F1:** twist 45°, pull out with its cap, push in, twist back.
- **F2:** slide 3 mm forward, lift, drop in, slide back.
- **F3:** lid open, tube out, twist 45°, lift, drop in, twist back.
