# MC-6 — faults (answer key only)

Not for the manual. Two faults. Rev A has both; Rev B has neither. The STEP files name the parts that differ with a `_revA` / `_revB` suffix.

| ID | Part (STEP body) | Rev A (faulty) | Rev B (fixed) | What it breaks |
|---|---|---|---|---|
| **F2** | `lid_handle_revA` / `lid_handle_revB` (laser stack, plies in `laser/…/lid_handle_rev*_*.dxf`) | A thin upright **pinch fin** on the lid front. Nothing to get a finger or gripper under, so the lid has to be pinched to lift it. | A **hook lip** that overhangs forward with clearance under it, so the lid lifts from below with one finger or a gripper jaw. | Opening the lid one-handed / with the gripper, as the manual describes ("lift by its front lip"). |
| **F3** | `well_insert_A_revA` / `well_insert_A_revB` (print: `print/well_insert_A_rev*.stl`); `tube_1_revA` / `tube_1_revB` show where the tube ends up | Well A bore **Ø15.6 mm** for a Ø16 mm tube. The tube can't drop in; it sits high on the insert. | Bore **Ø16.8 mm**. The tube drops in and its collar rests on the well. | Tube seated in well A. With Rev A the tube bottom sits 11.1 mm above the tube sensor instead of 3.2 mm, so it doesn't shade it and START gives `TUBE`. |

Notes
- F3 is only reachable once the lid is open, so F2 masks it (same as the existing `build/answer_key.json`).
- F1 (Stop button binding in its bezel) is **dropped** in v7: all three buttons are the same bought 16 mm panel button. `device.yaml`, `verify.yaml` and `build/answer_key.json` in the repo still list F1 and need updating by whoever rebuilds the sim.
- Well B (Ø16.8 mm) and the rack positions are the same in both revs.
