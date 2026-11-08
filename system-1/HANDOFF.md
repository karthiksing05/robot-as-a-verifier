# System 1 handoff, Nov 7 2026

For Joseph. This covers what changed in System 1 on `karthik-frontier-integration` since PRs #4–#10, which are now merged in (D34). The earlier handoff's real-arm list lives in the [server README](server/README.md), and that's still the place for how to run things. This file covers what's new, what you need to review, and what's broken.

Your calls stand. The verdict rules, the torque gate and the 15 N cap are as you left them.

## 1. The stock gripper is the default

We no longer have the fingertip probe, so the real arm is a stock SO-101 with its own gripper and nothing else.

- `--effector stock` is the default in `rav-server`, `make_rig`, `SimBackend`, the Console and the evals. `--effector probe` is still in the sim as a reference. A real arm refuses it, along with every other sim-only flag (`main.py`).
- With the stock gripper, `--sensing` defaults to `current`, the servos' own load estimate, because there's no pad.
- Probe results from earlier rounds are sim references only. They aren't evidence about the real arm.
- **Wrist camera only.** The rig has no global camera, so the Console and the harness (launch, CLI, evals) now default to the wrist route, OWLv2 and SAM, as on your real System 1. The depth route, which surveys with the sim's `phone` camera, stays in the sim as a reference.

## 2. New and changed skills

All of these are in [`core/affordances.py`](core/affordances.py) and [`core/manipulate.py`](core/manipulate.py), and run on the stock gripper unless noted.

| Skill | How it works now | Sim status |
|---|---|---|
| `press` | The closed jaws' tip pushes along the normal. A pulse that's on only briefly still counts as a press | 5/5 on every device |
| `flip` | The lever goes between the open jaws, and one jaw pushes it over. Your let-go centre (half of `FLIP_PAST` past centre) now applies to both effectors | 20/20 |
| `turn` | A pinch-turn: the jaws close on the knob and the wrist rolls it. If the knob lags, it grips again, up to 6 times, until it's within 4° of the request. **D35** | Lands short on centrifuge v7 (about 50° for 60°). See section 5 |
| `hook_pull` | Lifts a lid by its handle: ramped moves, a slow final 8 mm, and retries | Opens 27/30, with no cap trips |
| `pick`, `place` | Pick grips the object's faces, shutting by servo load. Place lowers into a well, or drops from `drop_mm` | Pick works on most devices. Place is 0/5 on the centrifuge's well A: the jaws hit the top panel |
| `swing` (door) | Microwave door, using the `_door_*` helpers in `manipulate.py` | In progress: the force estimate trips before the latch breaks |
| `reposition` | The backend moves the whole device. The scene is stale until the next explore | Re-explore after a move sometimes loses the device |

There are two more changes:

- **Contact recovery.** A move that starts already in contact may continue as long as it gets no deeper. `go_home` backs out of contact before it travels.
- **Telling direction.** `_judge` takes a dial's direction from its furthest reading, not its last.

## 3. What needs you

1. **D32: force at stretched poses.** At the low, far-out poses where the dials and toggles sit, the servo estimate reads 6–13 N when about 0–4 N is really on the tip. **The 15 N cap is unchanged.** The skills just don't trust the estimate there for side-force and landing checks. We can't tell from the sim whether this is real or a sim artifact.

   To settle it, try the 2-minute scale test in D32:
   - Hold the tip about 250 mm out and 20–30 mm up, with the tool 45° down.
   - Move 15 mm in free air and log the estimate.
   - Press a kitchen scale with about 3 N and log the estimate again.

   An error under 2 N means it's the sim.
2. **`RealArm` never drives the gripper** ([`hardware/real_arm.py`](hardware/real_arm.py) turns torque on for the five arm joints only). Every stock skill opens and closes the jaws, so on the real arm only `press` (jaws shut) can work as things stand.

   Driving motor 6 (RANGE_0_100) is the one piece of the real path we'd need from you. Pick and place also shut "by the servo's load", which needs motor 6's present load.
3. **D35: closing the loop on a turn.** The turn measures how far the knob went from the robot's own view: the fin's line seen by the wrist camera before and after, or failing that, the wrist's roll while gripping. It **never** uses the device's reading, so a dead pot still shows up as a fault.

   Printed jaws on a real knob may creep like the sim's soft contact does. Please check whether this matches what you see.
4. **D31 defaults are still open:**
   - restarting the server for a new device;
   - `check_steps` validating from the contract alone;
   - `Step.check` reported beside the verdict;
   - a 14 N step limit, rejected rather than clamped.

   Each is yours to overrule.
5. **`effector="stock"` through `driver="real"`** (the sim's motor bus through `RealArm`) is untested. `tests/test_real_backend.py` only covers the default.

## 4. Contracts and flags since your last look

- `make_rig(..., device, rev, effector="stock", mounts, driver="sim")`. `driver="real"` puts `RealArm` over the sim's simulated bus.
- `--rev` takes a named revision (`A`, `B`, `M1`) or a fault map (`F2=B,F3=A`). A device's faults are its parts, so `--fault` must be empty with `--device`.
- `pick`, `place` and `hook_pull` are offered only on a rig with a device file. Stock gets pick and place, probe gets hook_pull (`server/src/rav_server/actions.py`).
- `perceive.refine` sets `meta.seen_x`, the fin's line as seen, which the turn uses.
- Arm errors are injected per action (skill, target, attempt) with `--error-rate`. `--error-schedule` forces them for tests.

## 5. Known limits, in priority order

1. **Turns near the gripper.** From the pinch's look poses, the gripper hides the dial, so the camera can't see the fin and the loop falls back to the wrist. The fix is a look pose that sees the fin.
2. **Centrifuge v7 detection.** The tube rack is lost every time, yaw errors reach 19°, and some parts get the wrong kind or are duplicated.
3. **Centrifuge tube.** Pick works 2/5, and placing in well A works 0/5 because of jaw clearance at the top panel. A drop-in experiment (heights 5–40 mm) is running.
4. **Microwave door.** Unlatching trips the force estimate.
5. **The hotplate's +60° return** is refused near −57°, now that stock turns are accurate. The check needs revisiting.
6. **Real reach.** None of the centrifuge poses have been checked against the real arm's limits.

The v7 centrifuge and the MW-1 microwave are now in `appliances/`, with their sources and firmware. Their skills are still being tuned in sim.

## Tests

```
uv run --extra sim pytest -q        # System 1: 120 pass, 1 skipped on the merge
```

The tests need each device's `build/` and `appliances/registry.json`, which git ignores. Build them first with `system-1/sim/tools/build.py`; its docstring has the command.
