# The original demo: CAD and tags (demo.py)

[← Back to the overview](../README.md)

This page is the original README, kept nearly as written on Nov 1 to 4 and in its author's first person, so a few details are out of date: the D405 depth camera it mentions was later dropped, and "the pad" here means the probe's fingertip, not the SensX pressure pad. It describes the first sim, built on Nov 1 to follow the team plan as written: the robot knows the appliance's CAD model and finds it from printed markers. It still runs, and it is the baseline the no-CAD pipeline grew out of (see [How we got here](iteration-history.md)). Commands below run from the `prototype` folder.

A MuJoCo sim of the MakeCU test rig: an SO-101 arm with a fingertip probe, our parametric appliance (3 buttons and a door on a 45° panel) in a fixture plate, and a scene camera. The camera finds the appliance from printed markers. You give it a plan step like `press btn2`. It moves the arm, pushes until a force or travel limit, retreats, and returns a verdict backed by the tip force and the appliance's own switch readout.

## Run it

```bash
cd prototype
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt
```

Interactive (a viewer window plus a `>` prompt in the terminal):

```bash
.venv/Scripts/python demo.py --rev A
```

Headless plan run. This writes `runs/<plan>_rev<X>/results.json` and a `force.png` with one force trace per step:

```bash
.venv/Scripts/python demo.py --rev A --plan plans/coverage_test.json --headless
```

On macOS use `.venv/bin/python`. The viewer may need `mjpython` instead of `python` there; I only tested on Windows.

## Things to try

| Type this | What you should see |
|---|---|
| `press btn1` | PASS. About 2.9 N peak, 2.3 mm travel, LCD shows `BTN 1` |
| `press btn2` on Rev A | FAIL, "stuck: hit 6 N limit with only 0.15 mm travel" |
| `press btn2 force=13` on Rev A | PASS. The binding button breaks free at about 12 N, twice the 6 N a person should need |
| `latch door` on Rev A | REFUSED before moving: the pinch tab breaks the no-thumbs rule |
| `rev B`, then `latch door` | PASS. The push latch pops the door ajar. A second `latch door` is refused until `reset` |
| `run plans/coverage_test.json` | The whole test, then a summary (Rev A: 2 PASS, 2 FAIL, 1 REFUSED. Rev B: 5 PASS) |
| `goto 220 50 120` | Fingertip moves to x=220, y=50, z=120 mm |
| `follow` | The arm tracks the green sphere. Double-click the sphere, then Ctrl+right-drag it |
| `look` | Camera finds the desk board and the fixture tag, prints each control's position and its error against sim truth, and saves what it saw to `runs/look.png` |
| `shuffle 2`, then `press btn1` | The fixture moves and the camera gets bumped. The press comes back MISSED ("first contact 7.5 mm in front of the CAD surface") because the controls still point at the old spot |
| `look`, then `press btn1` again | PASS. Error after the look is about 0.6 mm |
| `goto 250 0 30` | SAFETY STOP: that point is inside the panel. The arm trips the 15 N cap, backs off 10 mm, and waits |

The overlay at top left shows the current skill phase, tip force, and the appliance state. The plot at bottom right is the last 5 s of tip force.

`--shuffle SEED` on the command line starts with a random placement. A headless run always looks before the plan. `--slop` gives the arm the real servos' gear play and dead band (see Sim shortcuts).

Each step result also has `contact_offset_mm`: how far in front of the CAD surface the probe first touched. It reads 0 to 2 mm when the CAD pose is right. Outside -1.5 to 3.5 mm, a step that didn't pass is reported as MISSED instead of FAIL: the probe probably hit the panel, not the control, so the result says nothing about the product. Missing the control entirely is MISSED too. The trade-off: a cap that is really missing, or sunk more than about 2 mm, also reads MISSED, so a MISSED after a fresh look is worth a human glance.

## How it works

| File | What it does |
|---|---|
| `appliance.py` | Rev A and Rev B as parameter dicts, like the planned CadQuery model. Generates the scene XML and plays the appliance's microcontroller (switches, door latch, LCD text) |
| `robot.py` | The arm. IK, a safety layer, and the tip load cell. The safety layer has joint limits, a per-tick step limit like LeRobot's `max_relative_target`, and a workspace box. It also stops and backs off 10 mm if tip force passes 15 N or any arm part other than the probe touches the rig |
| `skills.py` | `press`, `press_hold`, `push_latch`. Each skill validates the step, goes to a point 30 mm out along the control's normal, moves in at 20 mm/s, creeps the last 10 mm at 6 mm/s (slower as force rises), stops on the force limit or at 90% of the CAD travel, retreats, and judges (PASS, FAIL, or MISSED if first contact was far from CAD) |
| `vision.py` | The scene camera and localization. See below |
| `demo.py` | The viewer, the prompt, and the plan runner |

The original skills in `skills.py` were written around five core arm calls: `read_q`, `send`, `tick`, `tip_force`, `tip_pose`. A LeRobot backend for the real SO-101 would implement those, plus the few extras listed in the [code map](code-map.md).

## How the camera finds the controls

This follows the plan's perception design, in three steps:

1. **Camera pose.** A ChArUco board (a chessboard with ArUco markers in the white squares) is printed on the desk plate, at a known spot relative to the arm. OpenCV finds its corners and solves for where the camera is. No hand-eye calibration is needed, and a bumped camera is fixed on the next look.
2. **Appliance pose.** One ArUco tag sits on the fixture plate. Its four corners are cast from the camera onto the plate's known height, and a 2D fit gives the fixture's x, y and heading. Each control's CAD offset then gives its position and press direction in the arm frame. The skills use these positions.
3. **Detector cross-check.** A detector finds the button caps in the image. Each detection is cast onto that control's surface, and anything more than 5 mm from step 2 gets flagged. In the sim the detector is a colour threshold standing in for Grounding DINO. Labels come from matching each detection to the nearest CAD control.

`python vision.py 20` measures this over 20 random placements (fixture moved up to ±3 cm and ±10°, camera bumped up to ±3 cm). It gives a median error of 0.38 mm and a worst case of 1.1 mm. The same 12-placement test plan on Rev B passed 18 of 60 steps without a look and 58 of 60 with one. The two misses were the door, refused as out of reach before moving. Without a look, most failures used to read "stuck", which means a good button reported as a fault. With the MISSED check, 33 of those 36 failures now say MISSED. The other 3 still read "stuck": the probe hit the panel beside the button at almost the button's height, which a single push along one axis can't tell from a jammed button. So always look before testing.

## Where I changed the plan

- **IK uses MuJoCo, not placo.** The robot model we already load for sim gives us Jacobians, so IK is about 55 lines with no extra dependency. It puts the tip exactly on the target first, then points the probe as close to the press direction as the arm allows. You can't point it exactly in every direction: the SO-101's lift, elbow and wrist joints are parallel, so the probe always points within the vertical plane through the base. Buttons 1 and 3 sit 3.5 cm off-centre, so they get pressed about 6° off their axis. The same file could do IK for the real arm.
- **Door pops ajar instead of swinging open.** A push latch that swings fully open toward the arm hits the probe. Real push latches pop a door open a centimetre or two. Opening it fully would be a `hook_pull` job.
- **Press where the CAD says, and use the detector only to flag.** The plan uses a detection when it's within 5 mm of CAD. But even this perfect, noise-free stand-in lands 1 to 4 mm off, because a box around a cap seen at an angle includes the cap's side. Tag plus CAD is under 1.1 mm. So replacing the CAD position with a detection would make presses less accurate.
- **The fixture tag is solved on the desk plane, not with a full pose solve.** Solving the tag's 6-DoF pose from its own four corners was 3.6 mm off. One small tag is weak at telling tilt and distance apart, so I don't solve for those: the plate sits flat on the desk at a known height.
- **Register the fixture to the desk plate.** A fixture 2 to 3 cm closer to the arm puts the door out of the 45° reach. Pins or a corner stop that land it within a few mm would avoid that. The tag then corrects what is left and catches a bumped fixture.
- **The reach numbers in the doc hold up.** My IK, with our 25 mm probe, reproduces the doc's placo reach check: 45° presses work from about 0.20 to 0.36 m out, between 5 cm below and 15 cm above the base. The sloped panel sits inside that.

## Sim shortcuts

- **Binding is scripted.** MuJoCo's joint friction lets a button creep slowly under any steady push, so it can't model "won't move until 12 N". The appliance code instead locks a binding button, releases it once the probe pushes past 12 N, and locks it again when it springs back.
- **Contact stiffness is hand-set** at 15 kN/m. With MuJoCo's default, contact stiffness scales with the light arm's mass, and the probe sank 1 mm into a locked button at 6 N.
- **Force is read every 2 ms physics step** and the peak goes into the log, so the readings are cleaner than an 80 Hz HX711 load cell would give.
- **The camera is ideal.** It has exact known intrinsics, no lens distortion and no autofocus drift, and the image noise is Gaussian. The board's position relative to the arm is exact too. On the rig, 1 px of corner error is about 0.8 mm at this distance, and any error in where the board sits relative to the arm carries straight into every control. Touching the probe to a board corner once is a cheap way to check that.
- **Servo gains come from the SO-ARM100 model file**, not from our servos. Overshoot past the force limit (about 0.1 to 0.5 N here) will differ on hardware.
- **The arm is perfectly stiff unless you pass `--slop`.** With it, each servo is as soft as a real STS3215 (36 N·m per radian instead of the model file's 998), ignores errors under 4 encoder counts, and has 0.75° of gear play, all fitted to one bench test. Gravity then puts commanded poses about 9 mm off, and Rev B passes only because the pad catches the caps' edges. The encoders see the sag, so one slow re-command to `cmd + (q - read_q())` brings it to about 0.3 mm. The stiffness is the least certain number: at 18 N·m per radian (if LeRobot's P=16 halves it) every open-loop button press misses. On the real arm you can measure it in minutes by holding a pose and comparing each servo's goal and present position. Calibration offsets are not included; pass `joint_offsets` to SimArm to test them.
- **Wrist depth ignores surface texture unless you pass `stereo=True`.** A real D405 has no projector, so it can only match depth where the surface has texture, but by default `WristCamera` just adds noise to the true depth. `WristCamera(arm, stereo=True)` renders the second imager 18 mm to the right and matches the pair with OpenCV's semi-global matcher instead. That gives holes and wrong depths on plain plastic, wider parts and shallower seams, and perceive then misses every door and display and most dials, sliders and toggles. It stays opt-in until a real D405 frame of the device shows how close it is. MuJoCo's plastic has no micro-texture, so for plain surfaces it is a worst case.

## Not done

- No real-arm backend. LeRobot isn't installed here.
- No `hook_pull` or `insert`, and no `turn` in `demo.py` (`explore.py` turns dials, in `affordances.py`).
- `demo.py`'s detector is a colour threshold (`explore.py` uses OWLv2 and SAM). No camera intrinsics calibration step, because the sim camera's are known. The `look` always parks the arm at home first, and occlusion by the arm hasn't been tested.
- No sensor noise or latency on `demo.py`'s load cell (`explore.py` models servo, pad and load-cell sensing).
- Joint-space moves between poses don't plan around obstacles. If the arm hits the rig on the way, the safety layer stops it, but nothing reroutes. The included plan has no such hits.
