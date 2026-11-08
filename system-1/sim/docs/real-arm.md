# The real arm

[← Back to the overview](../README.md)

The skills (`touch.py`, `affordances.py`, `skills.py`) never touch the simulator directly. They drive the arm through a few calls, listed by `rig.Arm` in `system-1/core/rig.py`: read the joints, send a pose, wait one tick, read the force. `robot.SimArm` answers them in the sim, and `real_arm.RealArm` (in `system-1/hardware`) answers them with the team's SO-101, through LeRobot, so the same skills can run on hardware. `hw_rig.make_rig` builds the real arm and its wrist camera as a `rig.Rig`, the object the pipeline runs on.

None of this has run on the real arm. It has been tested against a simulated motor bus, which is described at the end of this page.

## What it is

| Part | What it does |
|---|---|
| `real_arm.RealArm` | The arm. It talks to the six servos through LeRobot's `SerialMotorsBus`, the same class the team's bring-up scripts in `system-1/arm/bringup/` use |
| `real_arm.make_bus` | Builds that bus from a serial port and the calibration file `lerobot-calibrate` writes |
| `real_arm.OperatorReadout` | The device's readout, which every verdict reads. In the sim this is the device's simulated microcontroller. Here it is a person at the terminal, who says what the device did after each step |
| `pico_readout.PicoReadout` | The readout from the printed appliance's own Pico over USB, which reports every control as it changes. `hw_rig.make_rig(..., readout_port="COM7")` uses it instead of the operator. [The firmware's README](../../subjects/appliance/firmware/README.md) has the line format |
| `tools/arm_check.py` | The first script to run on the built arm: joint readings and the fingertip's position, with torque off. Run it from `system-1/hardware` |
| `tools/hand_eye.py` | Measures where the wrist camera really sits on the arm, with torque off, from views of the desk board. `real_wrist` reads the result |

**Why the bus and not LeRobot's `SO101Follower`.** The follower is the class LeRobot's own scripts use, but its `connect()` always ends with torque on. And if the motors don't match its calibration file, it starts an interactive calibration that rewrites the motors' homing offsets. With the bus, torque goes on only when the code asks for it, and a mismatched file is an error.

**What happens each tick** (50 per second, `rig.CONTROL_HZ`): RealArm writes the goal positions, waits for the tick to end, then reads every joint once. Between ticks, `read_q()` and `tip_pose()` return that last reading, just as the sim does between physics steps. Forward kinematics, IK and the gravity model all come from the sim's own model file, with no physics.

**Force.** There's no force sensor yet, so RealArm uses the same estimate as the sim's `--sensing current`. Each servo's goal minus its present position, in encoder steps, gives its torque. The model's gravity is subtracted, and what remains is turned into a force at the fingertip through the arm's geometry. That code is in `RealArm._sense`. It is a copy of `SimArm._sense` rather than shared code, because the sim's version adds noise and bus delay that a real bus already has. The least-squares fit and the probe-axis maths are shared with `SimArm` through `rig.ArmBase`.

## The joint mapping

LeRobot and the MuJoCo model each have their own idea of a joint's zero, and RealArm has to convert between them.

- **LeRobot's side.** `lerobot-calibrate` has you hold every joint at the middle of its range, then sweep each one from stop to stop. The file it saves records the lowest and highest encoder step of each sweep. LeRobot's "degrees" reading is zero halfway between them.
- **The model's side.** The model file is `so101_new_calib.xml`. TheRobotStudio's SO-ARM100 README says that in this "new calibration" version each joint's zero is the middle of its range. The older `old_calib` version used the arm stretched out flat.
- **The link between them.** LeRobot's own kinematics code (`lerobot-find-joint-limits`, its phone and end-effector examples) loads this same model. It feeds the degrees reading in with nothing but a degrees-to-radians conversion: no sign flips and no offsets.

So RealArm uses sign +1 and no offset on every joint: the model angle is LeRobot's degrees reading. The constants are `SIGN` and `OFFSET_RAD` at the top of `real_arm.py`. The model's own zero pose agrees with this. At zero, the upper arm stands vertical, and the forearm and gripper are level and point straight forward, with the fingertip at (398, 0, 224) mm. That is the pose in LeRobot's calibration diagram. (The upper arm has a 14° dog-leg, so the line from the shoulder axis to the elbow axis leans 14° forward of vertical even though the link is upright. That is not an offset.)

How sure each part is:

- **Signs:** fairly sure. LeRobot's examples steer real SO-100 and SO-101 arms with IK on this model, and a wrong sign would send a joint the wrong way. This hasn't been checked on the team's arm.
- **Offsets:** expect a few degrees. The middle of a hand sweep isn't exactly the model's middle. One of LeRobot's own examples (its Isaac teleop) starts from a pose with shoulder_lift at -103°, past the model's -100° limit.
- **Scale:** LeRobot counts 4095 steps a turn and RealArm counts 4096. That is a 0.04° difference at most.

`tools/arm_check.py` is how to check all three. A sign or offset it finds goes into `SIGN` or `OFFSET_RAD`.

## Install

From `system-1/`:

```bash
uv sync --extra sim --extra arm
```

That installs the sim and LeRobot 0.7.0 together. The backend needs LeRobot 0.7 or later: from 0.7 its `SerialMotorsBus` talks to the servos through rustypot, the same bus class the bring-up scripts in `system-1/arm/bringup/` use. LeRobot 0.6 used a different Feetech bus, and the backend won't run on it. The tests in this repo were run against both LeRobot 0.7.0 from PyPI and the team's 0.7.1 checkout.

The workspace keeps only `opencv-contrib-python` (see `system-1/pyproject.toml`), because LeRobot's own OpenCV package would overwrite the `cv2` module and lose the ChArUco code the sim needs.

## First run

1. **Calibrate with LeRobot**, in LeRobot's own environment: `lerobot-calibrate --robot.type=so101_follower --robot.port=COM5 --robot.id=makecu`. This is LeRobot's normal procedure. It turns torque on while it connects, and it writes a P gain of 16 to every servo. That is far too soft for the team's RobiServo clones: at 16 a loose motor didn't follow a 5° move at all, and at their factory 160 it stopped 5 steps short ([results](../../arm/bringup/results.md)). So `RealArm.enable()` sets the five arm joints back to `real_arm.SERVO_P` (160) before torque goes on, every time. LeRobot's teleop drops it to 16 again. It also runs LeRobot's handshake, which checks each motor's model number and that all six report the same firmware. The team's clones pass it (tested Nov 6). The file it saves is `~/.cache/huggingface/lerobot/calibration/robots/so_follower/makecu.json`, called `CAL` below.
2. **Read-only check.** Run `python tools/arm_check.py COM5 CAL`. It turns torque off on every motor as it connects, so an arm that was holding a pose drops: it asks you to support the arm first. After that the arm is limp and nothing moves. Pose the arm by hand and check:
   - In LeRobot's calibration pose, every joint reads within a few degrees of 0.
   - Each joint's reading goes up when you move it the way the script's header says (for example, folding the forearm down raises elbow_flex). A joint that reads backwards needs its `SIGN` set to -1.
   - The fingertip position follows a ruler. Slide the tip 100 mm forward and x should go up by 100. The frame has x forward, y left and z up, with z measured from the underside of the arm's base.
   - A joint that is off by a steady amount gets that amount, in radians, in `OFFSET_RAD`.
3. **One joint at a time.** Run `python tools/arm_check.py COM5 CAL --move elbow_flex`. It asks first, then turns torque on, moves that joint 5° and back at about 2.5°/s, and waits for you to hold the arm before torque goes off. Check that it went the way the header said. It also prints the force estimate with the arm at rest. A value well over 2.5 N means the model's masses, or the servo stiffness it assumes (`real_arm.SERVO_NM_PER_RAD`), are off. Do this for each joint.
4. **One press.** Find the button's position by resting the fingertip on the centre of its cap while `arm_check.py` runs. Use the panel's outward direction as the normal. Then, in Python from `system-1/hardware`:

```python
import sys; sys.path.insert(0, "../core")   # affordances, features, skills
import numpy as np, affordances, features, real_arm, skills
pos, normal = np.array([0.280, 0.066, 0.054]), np.array([-0.64, 0.0, 0.77])   # from arm_check, in m
button = features.Part("button_1", "button", features.frame(pos, normal, [0, 1, 0]), size=np.array([0.012, 0.012, 0.003]))
with real_arm.RealArm(real_arm.make_bus("COM5", CAL)) as arm:
    arm.app = real_arm.OperatorReadout(arm, {"BTN1": 0})
    arm.enable(confirm=True)
    skills.go_home(arm)
    print(affordances.run_step(arm, [button], {"skill": "press", "target": "button_1"}))
    skills.go_home(arm)
```

After the press, the terminal asks what changed on the device. Type `BTN1` if it responded, or press Enter if it didn't. That gives a PASS or a FAIL. To type a value rather than a press (`POWER 1`, `FAN 0.8`), declare the channel first in the `OperatorReadout(...)` line with where it starts. Sliders and dials need that.

5. **The camera's mount.** Run `python tools/hand_eye.py COM5 CAL` with the wrist camera plugged in and the desk board in place. Torque stays off: you hold the arm at 30 poses over the board and press Enter at each. It shows the result and saves it only if you type `yes`. See [the next section](#the-wrist-cameras-mount).

The sim's arm sits on a 140 mm post above the desk (`rig.TABLE_Z`), and the skills were only tested at that height. Mount the real arm the same way, or expect different reach.

## The wrist camera's mount

Each wrist photo's pose is the model's `wrist_cam` by forward kinematics of the joint readings, times a fixed correction for where the camera really sits on the arm (`T_hand_eye`). Measuring that correction is called hand-eye calibration. `tools/hand_eye.py` measures it and, once you have seen the result and typed `yes`, writes `system-1/arm/camera/camera_out/hand_eye.json`. `real_wrist.WristCamera` loads that file and prints that it did. Without the file the correction is identity.

At each pose the script reads the joints five times before the frame and five times after, and averages them. If the two averages differ by over 2 encoder steps, the arm moved and it asks for that view again. It finds the board's pose in the camera with PnP. It then solves for the correction that keeps the board still across all views, first with Park's method, then with a least-squares fit to every board corner seen. On the sim's frames, Park's method alone was 0.15° and 1.5 mm off, because one view's PnP is only good to a few tenths of a degree. OpenCV's own `calibrateHandEye` would have done the first step, but opencv-contrib-python 5.0 doesn't include it.

**In the sim** (`tests/hand_eye_check.py`, one run), the USB camera's render was moved 1° and 2 mm off the model's `wrist_cam`, and the joints were read through the fake bus as encoder steps. From 20 views, the tool found the move to within 0.07° and 0.6 mm. Given the exact joint angles instead, it finds it to 0.02° and 0.07 mm, so the encoders' 0.088° step is what limits it. The steps also leave each view about 1.5 px off. More views is the way around them.

A mount error is the same in every photo, so the scan's plane sweep barely feels it (what breaks the sweep is error that changes from photo to photo, below). What it does change is where parts land in the arm's frame: by up to the rotation error times the scan's 0.12 m standoff, plus the translation error (the two partly cancel, so this is an upper bound). The touches fix each part's height, and the last look before a step re-places buttons and doors, though with the mount error still in, but toggles, sliders and dials are tested where the scan put them. So the script turns its result's expected error into that placement error and warns when it is over 1 mm, small against the sim's 14 mm buttons. On synthetic corners with the joints read as steps and 0.2 px of noise, 30 runs for each count:

| Views | Mount off by (rms) | Parts placed off by (rms) | Worst | Runs over 1 mm | Runs the script warns on |
|---|---|---|---|---|---|
| 15 | 0.097°, 0.42 mm | 0.74 mm | 1.48 mm | 5 of 30 | 13 |
| 20 | 0.090°, 0.36 mm | 0.67 mm | 1.04 mm | 2 | 5 |
| 30 | 0.067°, 0.27 mm | 0.50 mm | 0.84 mm | 0 | 0 |
| 50 | 0.054°, 0.21 mm | 0.40 mm | 0.69 mm | 0 | 0 |

The placement columns were worked out at 0.2 m rather than 0.12 m, so they overstate a little, and the script now warns on fewer runs than the last column shows.

No run from 30 views was over 1 mm, and 50 buys little more, so the default is 30. The script gets the expected error by solving again with each view left out in turn. From 20 views up that came within about 15% of the true rms; with fewer it ran about 30% high, so it errs toward asking for another run. Views turned less (about 40° apart instead of 50°) nearly doubled the errors, so spread the poses.

The encoders' resolution alone also leaves each wrist photo's pose about 0.056° and 0.16 mm off (rms), calibrated or not. That is the "0.05°, 0.2 mm" row of [the camera bench's table](../../arm/camera/results.md), where the coins' height came out right in one run and one coin was lost in another. That figure counts encoder rounding only, as with torque off. With torque on, as in a scan, a holding servo's reading flickers about 0.95 steps (1 sigma, the bench's figure, unmeasured on this arm). From one reading per photo, as `WristCamera` takes, the pose is then about 0.2° and 0.54 mm off, past the "0.1°, 0.5 mm" row where the scan was lost. Expect to need `rgbperceive.adjust` on the real arm.

**Joint offsets.** Hand-eye can only correct the camera's mount. A joint offset that `real_arm.OFFSET_RAD` doesn't know moves the camera differently at each pose, so the correction can't absorb it. The same 20 views, solved again with offsets added to the readings:

| Joint offsets | Mount off by | Reprojection | Board off by | Photo poses off by (median) |
|---|---|---|---|---|
| none | 0.07°, 0.6 mm | 1.45 px | 0.06°, 0.6 mm | 0.07°, 0.6 mm |
| shoulder_pan +0.5° | 0.07°, 0.6 mm | 1.45 px | 0.52°, 2.4 mm | 0.51°, 1.7 mm |
| shoulder_lift, elbow_flex or wrist_flex +0.5° | 0.14-0.17°, 0.7-1.5 mm | 2.4-2.9 px | 0.33-0.39°, 2.1-2.4 mm | 0.60-0.62°, 1.2-1.5 mm |
| wrist_roll +0.5° | 0.52°, 0.9 mm | 1.45 px | 0.06°, 0.6 mm | 0.07°, 0.6 mm |
| elbow_flex +2° | 0.58°, 2.9 mm | 10.1 px | 1.33°, 9.2 mm | 2.4°, 3.5 mm |
| all five, random within ±2° | 1.65°, 2.5 mm | 3.8 px | 1.65°, 9.0 mm | 1.8°, 6.1 mm |

"Board off by" is where the views put the board, against where `vision.T_BASE_BOARD` says it is fixed. Only `wrist_roll`'s offset folds into the mount, because nothing moves between that joint and the camera. `shoulder_pan`'s turns the whole arm frame. It leaves the mount and reprojection alone, so only the board's place shows it. The others pass almost whole into every photo's pose. They show as reprojection errors over about 2 px and as the board several millimetres away. Offsets can partly cancel, as in the last row, so check the board's place as well as the reprojection error. That check only works if the printed board sits where `vision.T_BASE_BOARD` says to well under a millimetre: a board placed 2 mm off looks like a joint offset. Fix offsets with `arm_check.py` first, then run `hand_eye.py` again. The script saves each view's joint readings and corners in the file, so a later fit could solve for the offsets from the same views. Nothing does that yet.

## Safety

- **Torque goes on only through `arm.enable(confirm=True)`.** Anything other than exactly `True` is refused. It reads every joint again first and holds the arm where that reading says, because the limp arm may have been moved since the last one. It refuses while a joint reads outside the model's limits, because the first command would snap it back inside. If that happens, move the joint in by hand first. `send()` refuses while torque is off.
- **Moves are limited.** Every command is clipped to the model's joint limits and to 0.06 rad (3.4°) per tick, `rig.MAX_STEP_RAD`. LeRobot also writes each joint's calibrated range into the servo's position-limit registers, which an STS3215 keeps its goal within (not checked on the RobiServo clone).
- **The force cap.** A force estimate over 15 N backs the fingertip 10 mm off along the probe and raises `SafetyStop`, just as in the sim. Inside a test step, that step is ABORTED and the arm goes home, with torque still on. The estimate carries about 2.5 N of noise and has no term for the arm's own inertia, so a fast knock can slip past it. The skills move slowly near contact for that reason.
- **There is no collision check.** The sim stops when any part of the arm other than the jaws near their tips touches something. The real arm can't sense that. Keep a hand near the power switch.
- **Torque goes off on every motor** when the `with` block ends, on any exception, on Ctrl+C, and when Python exits. The arm then goes limp and falls, so hold it or rest it first. If Python is killed outright (Task Manager, closing the window), nothing runs: switch off the power.

## What isn't built

- **The SensX pad.** RealArm takes a `pad` object, with `read()` returning newtons and `noise_n`, and then uses it for the force along the probe, as `--sensing tactile` does in the sim. That hook has only run on the simulated bus, reading the sim's pad (see Tests below), and no driver for the pad exists.
- **Reading the device.** `PicoReadout` has only run against a stand-in Pico on a local socket: the appliance's firmware isn't written yet. Without a Pico, `OperatorReadout` asks a person, and within a step the operator isn't asked, so a dial turn that changed nothing can't tell, and tries again further out along the fin. Reading a device's display or lights with the camera is left for the team. Any readout needs only `readings`, `events` and `lcd`.
- **The cameras.** `real_wrist.WristCamera` captures the real wrist camera (Windows only), with the same calls as the sim's. Its pose comes from forward kinematics of the joint readings, which is too coarse for the scan's plane sweep. `tools/hand_eye.py` measures the camera's mount, but it hasn't run on the real arm, so the correction is identity for now. `rgbperceive.survey_wrist` replaces the iPhone's survey, but it hasn't run on the real arm, so part positions still have to be given by hand, as in step 4.
- **Calibrating the model to the arm.** The joint mapping is LeRobot's default, and `arm_check.py` checks it by hand. Nothing measures the offsets automatically yet, for example by touching known points on the desk board.
- **Servo numbers.** The force estimate turns each servo's position error into torque with a stiffness, `real_arm.SERVO_NM_PER_RAD`. It is the sim's 36 N·m/rad, which came from a bench test at an unknown P gain. The stiffness at the P of 160 that `enable()` sets is unmeasured. A 2x error either way breaks something, and which way it's off is unknown: the 36 came from an STS3215 at an unstated gain, and the team's clones run at P 160, five times the STS3215's default of 32. These runs are RealArm driving the sim through a simulated bus (see Tests below), preset C's ten steps, one run each:

  - **Servos softer than 36, at 18.** The estimate reads about twice the true force, and it no longer cancels the arm's own weight, so it drifts as the arm moves. The presses passed with peaks of 11 to 14 N against 4 to 5 N true, but the toggle and both slides missed, and the door push tripped the 15 N cap with nothing touching: 5 of 10. Told 18, RealArm passed 10 of 10 on the same servos.
  - **Servos stiffer than 36, at 72.** The estimate reads low. All ten steps passed, but one dial turn reached 12.0 N true while the estimate read 5.0 N, so the 15 N cap would let through about twice that.
  - **The pad doesn't help at 18.** With `--sensing tactile`, RealArm passed 3 of 10. The pad read correctly, but the hard cap also reads the servo estimate along the probe, and at 18 that read anywhere from 0 to 9 N between steps, and on the way to a part, with nothing touching, it went over the 15 N cap twice (15.2 N on the way to button_3, 15.1 N at the door). With the servos alone, a press stops as soon as that estimate passes 6 N, at 4.4 to 5.2 N true. With the pad, a press keeps going until the pad reads 6 N, about 7 N true, and the estimate crossed 15 N on the way. Three presses, a slide and the door stopped at the cap, though the true force never passed 7.0 N, and both toggle flips missed. Told 18, RealArm passed 10 of 10 with the pad too.

  To fix it, run `system-1/arm/bringup/stiffness_test.py` on one motor at P 160, and put the result in `real_arm.SERVO_NM_PER_RAD`. `system-1/arm/bringup/bus_jitter.py` measures the other two guesses: how fast the bus reads, and how much a held position flickers (the sim uses the bench's 0.95 steps). Both feed the 2.5 N noise floor the skills keep their contact thresholds above. The `Present_Load` register (`robot.SENSE_REGISTER = "load"`) isn't supported.
- **Bus timing.** The code assumes one write and one read of five servos fit in each 20 ms tick. That hasn't been measured (`system-1/arm/bringup/bus_jitter.py` does). A slow USB adapter could make ticks run long, and then moves run slower than planned, never faster.
- **The gripper** is never driven. Its torque stays off.

## Tests

```bash
cd system-1/hardware
uv run python tests/test_real_arm.py          # all ten, about 30 s
uv run python tests/test_real_arm.py torque   # those with "torque" in the name
```

They need no hardware and open no serial port. `tests/fake_bus.py` stands in for rustypot's bus, underneath LeRobot's real `SerialMotorsBus`. A goal written to it moves a `SimArm(slop=True, sensing="current")` by one tick, and a position read from it is that sim's encoder reading, in raw steps. `FakePad` gives RealArm that sim's pad reading as its `pad`, when the sim has `sensing="tactile"`.

| Test | What it shows |
|---|---|
| `mapping_round_trips` | Steps to angle to steps is exact. Angle to steps to angle is within half a step (0.044°). The angle matches LeRobot's own degrees reading of the same steps to 0.044°. `make_bus` reads the file exactly as LeRobot writes it |
| `go_home_and_presses_agree_with_sim` | On preset C, RealArm goes home and presses all three buttons: PASS, PASS, PASS, with the same verdicts and channels as SimArm. Peak forces are within 0.2 N of SimArm's and first contact within 0.2 mm |
| `torque_off_after_exit_exception_and_ctrl_c` | Torque is off and the port closed after a normal exit, an exception, and Ctrl+C |
| `refuses_torque_without_confirmation` | `enable()` refuses without `confirm=True`, and with a joint pushed past its limit since the last reading. After the elbow is moved 20° by hand, `enable()` holds it where it is now. `send()` refuses with torque off. A calibration file that doesn't match the motors is refused at connect |
| `hard_cap_stops_a_push` | Pushing 15 mm into a button trips the cap. The estimate read 15.5 N while the true force was 10.9 N, and the tip then backed off to 4.6 mm clear |
| `tick_paced_at_control_hz` | 25 ticks take 0.50 s |
| `operator_readout_judges_presses` | The operator is asked after each press, again after each search poke when nothing registered, and not about going home between steps. Typing `BTN1` gives PASS, and pressing Enter gives FAIL |
| `both_rigs_have_what_the_pipeline_calls` | `SimArm` and `RealArm` have every call in `rig.Arm`, both wrist cameras every call in `rig.Camera`, and both readouts `rig.Readout`. A call missing from `RealArm`, as `arm_bodies` once was, fails it |
| `arm_check_reads_and_moves_one_joint` | Read-only drives nothing, and neither does answering "no". Answering "yes" moves elbow_flex to +5.0° and back, leaves the other joints still, and ends with torque off |
| `hand_eye_solve_finds_a_moved_camera` | `hand_eye.solve` finds a camera moved 1° and 2 mm to within 0.003° and 0.01 mm, from 15 views of the board's corners with exact joint angles and 0.2 px of noise. It takes 2 s. `tests/hand_eye_check.py` runs the whole tool on the sim's rendered frames, which takes about 2 minutes |

`tests/test_pico_readout.py` runs `PicoReadout` against a stand-in Pico on a local socket: the readings follow it while a step reads them, only int channels log events, and a Pico quiet for 2 s stops the next step.

`sim_rig.make_rig(driver="real")` runs the whole pipeline this way: RealArm drives the sim through this bus, and the cameras and the device's readout stay the sim's. `explore.py --slop --sensing current --real-driver` is the showcase through RealArm, and with `--sensing tactile` RealArm reads the sim's pad through `FakePad`. `tools/bench.py` passes the flag on. On preset C's depth route (add `--depth`, which needs no image models), RealArm passed all ten steps, as SimArm did (Nov 7, one run each). That plan has three presses, two toggle flips, two slides, two dial turns and the door. The RGB route's touch stage, run on the same scan, also worked through RealArm. Judged through `PicoReadout` instead, reading a stand-in Pico that mirrored the sim's readout over a socket in real time, SimArm's ten steps gave the same ten verdicts and channels.

With the pad, SimArm passed 10 of 10 and RealArm 9 of 10. RealArm's first toggle flip stopped at its 5 N limit before the lever went over: sideways force still comes from the servo estimate, and it read 5.0 N against 3.6 N true. At `robot.SENSE_SEED` 1 and 2 both arms passed 10 of 10, but on that flip RealArm read 0.7 to 1.4 N higher than SimArm at all three seeds (4.3 to 5.0 N against 3.6 to 3.7 N), so its margin under the 5 N limit is thin. The presses and the door read the same through both arms, 6.0 N on the pad against 7.1 to 7.6 N true (the sim's pad reads 15% low), with first contact within 0.4 mm of each other.

These runs exercise RealArm's step limit, its force estimate and hard cap on whole encoder steps, and LeRobot's bus code. They can't catch a wrong `SIGN` or `OFFSET_RAD`: the simulated bus turns angles into steps and back with `real_arm.to_raw` and `to_model` themselves, so whatever sign and offset RealArm uses comes back out unchanged. `mapping_round_trips` checks the mapping against LeRobot's own reading, and only `tools/arm_check.py` on the arm can check the sign and offset. Nor do the runs exercise bus timing or read errors, the P gain (the bus records the write, but the sim's servos keep their stiffness), a limp arm (with torque off the sim stands still), or the collision check the real arm lacks (the bus logs what the sim hit, and explore.py prints it). The wrist camera's pose still comes from the sim's own joint readings, not RealArm's.

Next: [Sim vs real](sim-vs-real.md) · [Force sensing](sensing.md) · [Code map](code-map.md)
