# arm

The real SO-101.

| Folder | What's in it | State |
|---|---|---|
| [`bringup/`](bringup) | Joseph's servo scripts, run one motor at a time: `motor_check`, `which_motor` (finds a lone motor's id at any baud rate and nudges it), `setup_one_motor`, `watch_position`, `bus_jitter`, `stiffness_test`, `strain_test`, `p_gain_sweep`. Results in [`bringup/results.md`](bringup/results.md) | Run on the six loose servos, except `stiffness_test` (needs the built arm) |
| [`camera/`](camera) | The wrist camera's bench test, `camera_test.py`: frame rate, JPEG quality, ChArUco calibration from the tablet, focus, noise, and the image models on real photos. [Runbook](camera/README.md), [results](camera/results.md) | Run on the Innomaker U20CAM. Windows only. Calibration at 1080p in `camera/camera_out/calib.json` |
| [`../hardware/real_arm.py`](../hardware/real_arm.py) | `RealArm`: lets the skills drive the real arm over LeRobot's bus. It shares the IK and force estimate with the sim through `system-1/core/rig.py` | Tested against a simulated bus, and its read-only check and one-joint move on loose servos. Not yet run on the built arm |
| [`src/rav_arm/lerobot_arm.py`](src/rav_arm/lerobot_arm.py) | The original `LeRobotArm` skeleton | Superseded by `RealArm`, and its `ArmBackend` by `rig.Arm` |

## Setup

```bash
uv sync --extra sim --extra arm
```

That installs LeRobot 0.7.0 from PyPI. Its `lerobot.motors.SerialMotorsBus` is the bus class the bring-up scripts and `RealArm` use; LeRobot 0.6 had a different one. For a newer LeRobot, clone https://github.com/huggingface/lerobot into `bringup/lerobot` (git ignores it) and install it from there.

Scripts take the serial port as an argument: `COM5` on Windows, `/dev/tty.usbmodem...` on a Mac. Find it with `lerobot-find-port`.

## Order of work

1. Motor IDs with `lerobot-setup-motors`, gripper first. Then `lerobot-calibrate`.
2. E-stop on servo power, then software limits.
3. Hello world: connect, home, move to three poses, one guarded press with a force reading.
4. The [bench tests](../sim/docs/sim-vs-real.md#first-things-to-measure-on-the-real-arm), with the numbers put back into `robot.py`.
5. Run `RealArm`: the read-only joint check first, then one press. Steps are on [the real-arm page](../sim/docs/real-arm.md).
