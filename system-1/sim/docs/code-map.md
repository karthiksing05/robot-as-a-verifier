# Code map

[← Back to the overview](../README.md)

About 10,300 lines of Python in three folders of flat modules, no packages. `system-1/core` is the pipeline, which runs the same on the sim and on the real arm. `system-1/sim` is the simulated rig, the film and the benchmark, and `system-1/hardware` has the real arm's and cameras' drivers. Every module has a docstring at the top, most with a usage example, so the fastest way into any file is to read its first 20 lines. This page says which file to open for what.

## Entry points

| Command | What it does |
|---|---|
| `python explore.py [flags]` | The main demo: an unknown device found, scanned, understood and tested. Live viewer, or `--headless --record out.mp4` for a film. Flags are listed in the [overview](../README.md#run-it) |
| `python tools/bench.py OUT.jsonl SETUP SEED [flags]` | One end-to-end run with no film, appended as a JSON line. This is how the [results](results.md) were measured |
| `python demo.py` | The original CAD-and-tag demo ([here](original-demo.md)) |
| `python tools/arm_check.py COM5 CAL`, from `system-1/hardware` | The first check on the built arm ([the real arm](real-arm.md)) |

The first three run from `system-1/sim` and put `core/` on the path themselves.

## The rig

Everything the pipeline needs from the world goes through a `rig.Rig`: an arm and its cameras. `core/rig.py` lists what the pipeline calls on each, as the `Arm`, `Camera` and `Readout` protocols. `sim/sim_rig.py` builds the sim's rig and `hardware/hw_rig.py` the real one, and `core/pipeline.py` runs on whichever it is given. `tests/test_boundary.py` checks that `core/` imports nothing from `sim/` or `hardware/`, and `hardware/tests/test_real_arm.py` checks that both arms and both wrist cameras have every call the protocols list.

## The pipeline, file by file

In the order a run uses them:

| File | Lines | What it does | Start reading at |
|---|---|---|---|
| `sim/world.py` | 222 | The desk scene: desk, lights, the ChArUco board, the phone's tripod. `build_world(seed)` makes a scene around a generated device | `build_world` |
| `sim/device.py` | 919 | Procedurally generated devices: layout, MuJoCo bodies, the microcontroller that turns joint motion into readouts (BTN1, FAN, POWER...), the LCD, and sim truth for scoring | `make_spec`, `DeviceMCU` |
| `sim/robot.py` | 437 | The simulated arm: the safety layer, the soft-servo model, and every force-sensing mode (ideal, servo current, SensX pad, load cell). `hardware/real_arm.py` provides the same calls on the real arm | The `SimArm` docstring |
| `core/rig.py` | 283 | What both arms share: IK (inverse kinematics: the joint angles that put the fingertip at a given pose), the limits, the safety stop, the desk height, the force estimate's fit, and the camera frame. `rig.Arm` lists the calls the pipeline makes on an arm: `read_q`, `send`, `tick`, `tip_force` and `tip_pose`, plus `tip_force_vec`, `tare`, the IK solver, a few sensing attributes, the clock (`arm.d.time`) and the device's readout (`arm.app`) | `Arm`, `Rig` |
| `sim/sim_rig.py` | 62 | Builds the sim's rig: the device, its placement, the joint errors, `SimArm` and the cameras, in a fixed random order. With `driver="real"` the rig's arm is `RealArm` on a simulated motor bus over `SimArm`, reading the sim's pad with `sensing="tactile"` | `make_rig` |
| `sim/sensors.py` | 340 | The cameras: the USB wrist camera (`usb=True`, the bench-measured Innomaker), the D405 depth camera (`stereo=True` for its realistic stereo model), and the iPhone (RGB plus LiDAR) the depth route still uses | `WristCamera` |
| `hardware/real_cameras.py` | 305 | The real iPhone behind `sensors.py`'s interface, so the pipeline runs unchanged on the rig: Record3D over USB (RGB plus LiDAR) or Continuity Camera (RGB only), a frame grabber per camera, and `RunVideo` for the run folder's stills and videos. `hardware/tools/cam_check.py` brings them up | The module docstring |
| `core/pipeline.py` | 53 | The stages explore.py films and the tool server runs: `scan_device`, `touch_plane`, `touch_parts` and `last_look`, each touch falling back on what the scan found | The module docstring |
| `core/perceive.py` | 1083 | The depth-camera pipeline (`--depth`), plus pieces both pipelines share: the phone survey, wrist view planning, and the per-kind builders that turn measurements into parts | `survey`, `plan_views` |
| `core/rgbperceive.py` | 1151 | The default RGB pipeline: scan, bundle adjustment, orthophoto, segmentation, plane sweep, classification | `perceive_rgb`, then `analyse` |
| `core/segmodels.py` | 130 | Thin wrappers for OWLv2 (boxes from text) and SAM 2.1 tiny (outlines from boxes, plus automatic sub-part masks) | `owl`, `sam_boxes`, `sam_auto` |
| `core/features.py` | 104 | The part record perception hands to the planner: kind, pose, size, motion axis. Format from GAPartNet and SceneFun3D | `Part` |
| `core/touch.py` | 543 | The probe's touches (panel plane, part heights) and the camera's last look before each test | `touch_plane`, `touch_parts`, `make_refine` |
| `core/affordances.py` | 922 | Test planning and the part-level skills (press, flip, slide, turn, push latch) as guarded motions with readout-backed verdicts | `plan_tests`, `run_step` |
| `core/skills.py` | 281 | Motion primitives (joint moves, straight lines, going home) and the original appliance skills | `move_joints`, `move_line` |
| `sim/viz.py` | 786 | Drawing: 3D overlays, ghost arms, camera panels, the dashboard and video writing | `Overlay`, `Dashboard` |
| `sim/explore.py` | 1345 | The showcase: stage order, camera direction and narration. It only directs and draws; every decision is made in the modules above | `STAGES` |
| `hardware/real_wrist.py` | 143 | The real wrist camera with `sensors.WristCamera`'s calls (`capture`, `K`, `close`): frames through ffmpeg on Windows, undistorted with the bench calibration, posed by forward kinematics. `system-1/arm/camera/camera_test.py` uses its capture code | `WristCamera` |
| `hardware/real_arm.py` | 296 | The real SO-101 through LeRobot's motor bus, with the calls the skills use on `SimArm`, plus a terminal readout of the device. `hardware/tools/arm_check.py` checks it on the built arm, `hardware/tests/test_real_arm.py` on a simulated bus ([the real arm](real-arm.md)) | `RealArm` |
| `hardware/pico_readout.py` | 70 | The device's readout from the printed appliance's Pico over USB serial, one JSON line per change ([format](../../subjects/appliance/firmware/README.md)). `hardware/tests/test_pico_readout.py` checks it against a stand-in on a socket | `PicoReadout` |
| `hardware/hw_rig.py` | 28 | Builds the real rig: `RealArm` with torque off, the USB wrist camera, and the Pico's readout if given its port. Untested without the arm | `make_rig` |

The original demo's files, in `sim/`, are `appliance.py` (the parametric appliance), `vision.py` (tag-based localisation) and `demo.py` (viewer, prompt and plan runner), with `plans/` and `runs/`.

## How the pieces talk

```
explore.py ─► pipeline.scan_device: rgbperceive.survey_wrist, then perceive_rgb (USB cam) ─► scene.parts (features.Part list)
            ─► pipeline.touch_plane, touch_parts   ───► parts with touched plane and heights
            ─► affordances.plan_tests              ───► steps
            ─► affordances.run_plan(refine=pipeline.last_look(usb_cam, plane))
                     └─► per step: last look ─► guarded motion (skills, the rig's arm) ─► verdict from device readout
```

The tool server's `PipelineRobot` (`system-1/server`) makes the same calls without the film.

Everything the robot uses comes from camera frames, the poses it believes those frames were taken from, its own joint readings, and its own force readings. Sim truth (`world.truth`, `device` internals) is only used for scoring, and by the film to frame shots.

## Things that are easy to change

| To change | Edit |
|---|---|
| Servo stiffness, gear play, friction | Constants at the top of `robot.py` (`SERVO_NM_PER_RAD`, `BACKLASH_DEG`, `FRICTION_SCALE`), or `--stiffness` |
| The pad's noise, threshold or calibration | `robot.PAD_NOISE_KPA`, `PAD_THRESHOLD_KPA`, `PAD_GAIN` |
| The load cell's noise, drift or calibration | `robot.LC_NOISE_N`, `LC_DRIFT_N`, `LC_GAIN` |
| The words OWLv2 searches for | `segmodels.QUERIES` |
| Which parts get the camera's last look | `touch.REFINED` |
| Force limits and speeds for each skill | Constants at the top of `affordances.py` and `skills.py` |
| What devices get generated | `device.make_spec` |
| A new exploration step, such as scanning one area of the panel | A function in `core/pipeline.py`, and a method on the server's `PipelineRobot` |

## Conventions

- Lengths are metres in code and millimetres in text. Angles are radians in code, except where a name or docstring says degrees (`BACKLASH_DEG`, `touch.PLANE_TILT`, a turn step's `angle`).
- The arm frame has x forward, y left and z up, with the origin at the arm's base.
- A device seed is an integer, and preset C is the hand-designed demo device. The same seed always gives the same device, placement and joint errors.

Next: [How it works](how-it-works.md) · [Results](results.md)
