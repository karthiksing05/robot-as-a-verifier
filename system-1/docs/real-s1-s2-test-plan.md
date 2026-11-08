# The real arm through System 2: what's ready, and a first session

Written Nov 8, 2026, on top of `merge-all`.

System 2 can already drive System 1's real path end to end, and it worked with `RealArm` on the simulated motor bus.
It is not ready for the real arm from this branch, though. `rav-server --robot real` here has none of the settings
the hardware work found on `system1-arm-check-speed`. It would put the desk 14 cm below the arm's base (the sim's
post), use zero joint offsets, and judge contact from the servo force estimate, which drifts 2.5 to 10 N in free air
on the real arm. So the first step is merging that branch (below). The Console's Prod mode isn't wired to anything
yet, so the first session uses the `rav` CLI.

## The path

```
rav (System 2)  --MCP over HTTP-->  rav-server --robot real  -->  RealBackend (sim_backend.PipelineRobot)
                                                                    hw_rig.make_rig: RealArm on LeRobot's bus,
                                                                    the USB wrist camera, real_arm.OperatorReadout
```

- **Server.** `rav-server --robot real --arm-port COM11 --calibration CAL.json` builds the rig with torque off, then
  asks "Type yes to turn torque on". `--enable-torque` skips that question. CAL.json is lerobot-calibrate's file,
  `~/.cache/huggingface/lerobot/calibration/robots/so_follower/<robot.id>.json`. Ctrl+C stops sending goals, stops
  the routine at its next step, then turns torque off as the server exits, so the arm goes limp.
- **Readout.** After each test motion the server's terminal asks "What changed on the device?". Type a channel name
  for a momentary event (`START`), or press Enter for nothing. A press passes on any event you type.
  `hardware/pico_readout.py` exists, but only the hardware branch adds a `--readout-port` flag for it.
- **Explore** is more than the scan: survey, views and segmentation (OWLv2 and SAM), then 3 touch-offs on clear panel
  and touches on parts that need them (never buttons), then the last-look setup. Every test step re-looks at its
  part from the approach pose. The hardware tools never ran these touches on a real panel.
- **System 2.** `rav explore --url URL` scans only. `rav run --url URL` explores, then runs the rule-based plan.
  `rav agent --url URL --model M` puts a model in charge (needs `.env` at the repo root). New on this branch: on a
  real arm, `rav run` and `rav agent` print each plan and ask "Type yes" at their own terminal. Before, `rav run`
  approved by itself and `rav agent` refused. `rav run --only button_1` cuts the plan to the steps on those controls.
- **Console Prod.** `ENVIRONMENTS.prod.connected` is false in `console/web/src/lib/session.ts`, and `rav-agent`
  launches its own `rav-server` for every run, with sim flags. For a real device that command exits with "--robot
  real needs --arm-port and --calibration". Wiring it means `rav-agent` attaching to a server that is already
  running, and the Console starting runs on physical projects in Prod.

## Rehearsal without hardware

- `tests/test_real_backend.py` and `hardware/tests`: 13 passed. They cover torque only after a yes, Ctrl+C
  mid-routine, and torque off with the port closed however the server ends.
- `hardware/tools/sim_bus_server.py` runs the real server with the sim's rig behind `RealArm` on the simulated bus.
  Against it, `rav explore` found the preset device's 8 controls in 84 s, and `rav run --only button_1` showed the
  step, took the yes and passed it. The full `rav run` passed 3 presses and 2 slides. Its 2 flips and 2 turns were
  refused ("the gripper can't open on this arm"), as expected without `grip()`. That scan missed the door and display.
- What broke: the auto-approval above, fixed here. Also, the first scan saw nothing, because the sim's cameras render
  through OpenGL tied to the thread that built them, and routines run on another thread. That only affects the
  rehearsal, since the real camera reads ffmpeg frames, and the tool works around it.
- Not covered: the real camera, the serial bus, the readout's questions (the sim's readout answers), real speeds.

## What the hardware branch has that the server's real path lacks

| On `system1-arm-check-speed` | In `rav-server --robot real` here |
|---|---|
| Desk at the arm's base (`table_z` 0), workspace floor 5 mm above it | Sim's post: desk at -140 mm, floor at -120 mm |
| Joint offsets: lift -1.9, elbow -4.8, wrist_flex -2.24 deg | All 0 |
| Model's camera moved to `hand_eye.json` (`real_wrist.move_mount`), real gripper mask, real-panel rules (`FLAT_BUTTONS`, `PANEL_NZ`, toggle size) | Sim's camera and rules; `hand_eye.json` only for photo poses |
| Contact by stall: the command running 4 mm ahead of the joints, at 15 mm/s | Servo force estimate |
| Scan views 140 mm out, tilted up the slope, one row; camera on top at home | Sim's views |
| Presses 40% toward straight down, to a fixed 9 mm, after `press_part`'s 5.4 mm shift | Along the normal, stop on contact, no shift |
| Gripper driven closed when torque goes on | Gripper limp |
| No hard cap on the force estimate (it read 35-60 N on free moves home) | 15 N cap on the estimate |
| `scan_check`/`press_part` put the arm back where it rested before torque goes off | Torque off wherever it is |

Most of this is `RealArm` class attributes and `hw_rig` settings, so it arrives with the merge. Three things live
only in the tools and need porting into `RealBackend`: the 5.4 mm shift, going back to rest before torque off, and
skipping touches if we want that. Two files aren't in git: `hand_eye.json` (meant to be tracked: `.gitignore`
excepts it) and `gripper_px.json`, both in `system-1/arm/camera/camera_out/` of the hardware checkout. Whichever
checkout runs `rav-server` needs both.

A dry merge (`git merge-tree`) conflicts in two files. Everything else merges, including `main.py`,
`real_backend.py`, `rig.py`, `touch.py` and `hw_rig.py`.

- `core/perceive.py`, `_coarse_panel` (3 hunks): keep both sides. That is the branch's `PANEL_NZ` and
  `PANEL_PLANES` settings, plus main's fallback to an upright panel (the wall thermostat).
- `core/affordances.py` (9 hunks): two different stall checks in `_guarded`. Main's (#13) is for descents only: the
  pad covered under 20% of its command's travel over 0.3 s, plus a weighted force check, tuned in the sim. The
  branch's covers every guarded move, measured on the real arm. Suggested: the branch's when `arm.stall_m` is set
  (`RealArm`), main's otherwise. The other hunks put main's dial arcs, jaw opening and press search beside the
  branch's press direction, press depth and reused approach bias, and both sides can stay.

Decisions for you:

1. **Hard cap.** The branch has no cap on the force estimate on the real arm. Keep none, or set one above the false
   trips (60 N, say) as a last resort?
2. **Touches in explore.** Run them on the real panel (untested there; stall contact after the merge), or skip them
   in `RealBackend` as `scan_check` does?
3. **Press search.** Main re-presses 4 mm off each way when a press changed nothing: up to 4 more presses, each
   asking at the terminal. Keep that on the real arm?
4. **The 5.4 mm shift.** A `RealArm` setting applied after the scan and after each last look, or fix its cause
   (the camera mount) first?
5. **Rest at shutdown.** Move the arm back to rest in `close()`, or keep "hold the arm, then Ctrl+C"?

## First session, after the merge

Two terminals: A in `system-1`, B in `system-2`. Before System 2 touches anything, run
`python hardware/tools/scan_check.py COM11 CAL.json` on the merged code. If it finds what it found before, the merge
kept the real rig intact.

**1. Scan only.**

```bash
uv run rav-server --robot real --arm-port COM11 --calibration CAL.json
```

Check the arm is clear, put a hand on the power switch, and type yes in A. Then in B:

```bash
uv run rav explore --url http://127.0.0.1:8780/mcp --id real-scan-1
```

Watch that the survey poses stay in front of the arm, and that the touch-offs (if kept) stop at the panel instead
of pushing on. Compare the list it prints with `scan_check`'s. The record is in `runs/real-scan-1/events.jsonl`.

**2. One press.**

```bash
uv run rav run --url http://127.0.0.1:8780/mcp --id real-press-1 --only button_1
```

It scans again, prints the one step, and asks in B. Then in A, type what changed (`START`) or press Enter. Watch the
jaw land on the cap. If you answer Enter and keep the press search, expect up to 4 more presses.

**3. Full plan.**

```bash
uv run rav run --url http://127.0.0.1:8780/mcp --id real-full-1
```

Flips and turns are refused on this arm, so expect presses only. After that, `rav agent` adds the model, with the
same approval in B.

**Safety.**

- Torque goes on only after the yes in A. Don't pass `--enable-torque` in these sessions.
- The torque yes is also the consent for the scan and the touches: explore moves the arm with no approval in B.
- After the merge as it stands, nothing in software caps force on the estimate (decision 1). A press is bounded by
  the stall check, the 9 mm depth and the servos' own torque limit (680/1000) and overload protection. The workspace
  box stops any target below 5 mm over the desk.
- Stop the arm from A (Ctrl+C) or the power switch, not from B: if System 2 stops, System 1 finishes the step it's
  on before it holds. Ctrl+C in A drops the arm limp, so hold it first. Keep a hand on the power switch for every motion.
