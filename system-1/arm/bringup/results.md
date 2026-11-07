# Servo bench results: Robify RobiServo-01 (12 V STS3215 clone)

## LeRobot handshake and the real-arm code (Nov 6, night)

- `lerobot-calibrate --robot.type=so101_follower --robot.port=COM10` gets past LeRobot's handshake (model number and firmware check) on all six clones. The hand sweep couldn't be finished on loose motors: the 345:1 gearbox is too stiff to turn by the shaft. On the built arm the links give leverage.
- A throwaway calibration file was read back from the motors (`bench_test.json`, limits 0-4095). `system-1/sim/tools/arm_check.py` reads all five joints through it at 0.0 deg, fingertip (416, 0, 227) mm, the model's zero pose. `system-1/sim/tests/test_real_arm.py`: 8 of 8 pass in the repo environment on Windows.

## P gain: LeRobot's 16 is too soft for these servos

`arm_check.py --move elbow_flex` at P=16 (what `lerobot-calibrate` writes) reached only +2.3 of +5 deg and didn't come back. `p_gain_sweep.py` on loose motor 3 (encoder steps; 57 steps = 5 deg):

| P | Smallest step it follows | 5 deg move: stops short by | Back to 0: ends at | Jitter holding |
|---|---|---|---|---|
| 16 (LeRobot) | none, not even 57 | 57 (didn't move) | 0 | 0 |
| 32 (STS3215 factory) | about 20 (moves 2) | 24 | +27 | 0.43 |
| 64 | about 20 (moves 4) | 14 | +12 | 0.16 |
| 160 (RobiServo factory) | 10 (moves 6) | 5 (0.4 deg) | +5 | 0.95 |

- At P=160 the dead zone is about 5 steps, close to the sim's realistic arm (it ignores errors under 4 counts). At 16 the motor barely moves.
- LeRobot's `SO101Follower` writes P=16 every time it connects (calibrate, teleop). `RealArm.enable()` now sets the five arm joints to 160 (`real_arm.SERVO_P`) before torque goes on. Rerun of `arm_check.py --move elbow_flex` through it: back within 0.53 deg of its start (was 2.37 at P=16), force estimate at rest 3.3 N (was 10.7). The gripper stays at 16; nothing drives it.
- Not measured: whether P=160 oscillates with the arm's weight on it, and the servo stiffness at P=160 (`real_arm.SERVO_NM_PER_RAD`, which the force estimate needs). Both need the built arm.
