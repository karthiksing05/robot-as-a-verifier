# MW-1 — faults (answer key only)

Not for the manual. One fault. Rev A has it, Rev B doesn't. STEP bodies that differ carry `_revA` / `_revB`.

| ID | Parts (STEP bodies) | Rev A (faulty) | Rev B (fixed) | What it breaks |
|---|---|---|---|---|
| **F1** | `hinge1_wall_leaf`, `hinge1_door_leaf`, `hinge1_pin`, and the same for `hinge2` (each `_revA` / `_revB`); print files `print/hinge_*_rev*.stl` | The door hinge exactly as given in Onshape `Hinge.step`: **0.025 mm** clearance everywhere — pin to bore (Ø4.254 pin in Ø4.306 bores) and knuckle to knuckle. The pin has a collar at **both** ends, so it can't be put in after printing; printed in place, 0.025 mm gaps fuse. Result: a stiff or seized door that won't swing, or a hinge that can't be assembled. Leaves also meet at 135°. | Same envelope and screw holes. Bores opened to **0.25 mm** radial clearance, **0.4 mm** gaps around and between the knuckles, pin with a head on top only so it drops in from above. Door swings freely to ~145°. | Opening and closing the door (the manual: "pull straight toward you… swing the door open"). |

Notes
- Both hinges (`hinge1` at z ≈ 30, `hinge2` at z ≈ 112) use the same part; the fault is on both.
- The latch, door sensor and buttons are the same in both revs.
- Measured on the CAD (`checks.py`): Rev A min leaf-to-leaf gap 0.025 mm, pin gaps 0.025 mm; Rev B 0.375 mm leaf-to-leaf, 0.25 mm pin-to-wall-leaf.
