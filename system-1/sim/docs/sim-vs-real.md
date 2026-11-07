# Sim vs real

[← Back to the overview](../README.md)

Every number in these docs comes from a simulation. This page says what the sim models faithfully, what it makes easier than reality, and the cheap bench tests that would tell us how far off it is. The wrist camera and the loose servos have been measured on the bench ([camera results](../../arm/camera/results.md), [servo results](../../arm/bringup/results.md)), and the sim uses those numbers. The arm isn't built yet.

## What the sim models

| Thing | How it's modelled | Based on |
|---|---|---|
| Arm geometry | The SO-101 model file | The MuJoCo model published with the SO-ARM100 arm design |
| Soft servos (`--slop`) | Each servo corrects its position using the encoder on its output shaft, ignores errors under 5 encoder counts (about 0.44°), pushes back at 18 or 36 N·m/rad, and has 0.75° of gear play | The dead zone from a loose RobiServo-01 at P=160 (the team's servo). Stiffness and gear play from one published bench test of an STS3215 |
| Gear friction (with any of the three real sensing modes) | Load-dependent friction: about 0.28 x the held load, 0.43 x when moving slowly | Rhoban's BAM bench measurements of the STS3215 servo (their model m5) |
| Joint calibration error | The arm believes it is at the true angle plus an offset: σ 0.5° by default, ±2° with `--offsets 2` | Assumed |
| Servo readings | 12-bit encoders with 0.95 counts of jitter (1σ), read over the bus at 50 Hz | Jitter of a loose RobiServo-01 holding at P=160; 50 Hz is `RealArm`'s control tick |
| USB wrist camera | 1920x1080, undistorted to 75 x 47°, the lens's distortion, a deep depth of field, JPEG quality 51, noise | The bench test of the team's Innomaker U20CAM-1080P: calibration, focus sweep, noise, a frame's JPEG tables |
| iPhone | RGB plus LiDAR depth good to about 1 cm. Used only by the depth-camera route (`--depth`); the team dropped it | Published iPhone LiDAR accuracy |
| SensX 25 pad | 5 x 5 cells, whole kPa from 0 to 534, 1 kPa noise, a 3 kPa threshold, reads 15% low | Cells, range and units from the vendor's driver; noise, threshold and calibration are guesses |
| Devices | Procedurally generated sloped panels with buttons, toggles, sliders, dials, knobs, doors and displays, each wired to a simulated microcontroller with readouts | `device.py` |

## What the sim makes easier

- **Rendered images are clean.** MuJoCo has no glare, no reflections off glossy plastic, no fingerprints and no motion blur. Real segmentation and plane-sweep heights will be worse. How much worse is the biggest unknown here.
- **The devices come from one family.** Real products have parts, colours and finishes `device.py` never generates. Perception was tuned on these devices, so treat its 93-95% as a ceiling.
- **Contacts are idealised.** MuJoCo contacts are points with hand-set stiffness, so the pad model spreads each contact over a 3 mm disc as a stand-in for the pad's rubber cover. Real buttons have travel, wobble and cheap-switch bounce the sim doesn't.
- **The servo model rests on one bench test.** Stiffness is the least certain number. That's why the skills are tested at both 18 and 36 N·m/rad. The end-to-end benchmark used 18.
- **Noise models are assumed.** Encoder jitter, the force estimate's model errors, and all three of the pad's noise numbers are reasonable guesses, not measurements.
- **The sim knows the truth, and the film uses it.** The robot never reads true part positions (reviews checked this). But the film frames its shots on the device's true extent, and draws the overlay in the true place when the arm has calibration error.

- **Devices report their own state.** Every simulated device has a microcontroller that tells the robot each control's state, and every verdict rests on it. A real product won't do that. The robot would have to read its display or indicator lights with the camera, or the device would need wiring. Neither is built yet.
- **No device is ever broken.** The generated devices have no faults, so a correct FAIL has never been tested.

## What the sim makes harder

- **The plain plastic is plainer than real plastic.** MuJoCo surfaces have no micro-texture at all. That's why the stereo depth camera failed so badly, and real panels with labels and moulding marks would give a plane sweep more to match.

## First things to measure on the real arm

Each test is cheap, and each settles a number that changes the results.

1. **Servo stiffness, about 10 minutes.** Hold a pose at LeRobot's default gain. Press the probe on a kitchen scale, then hang 100-200 g at the tip, and log each servo's goal minus present position, Present_Load and Present_Current. That gives the stiffness (18 or 36 N·m/rad?) and shows which register carries the most signal, which decides whether servo-only sensing can work.
2. **The SensX 25, about 15 minutes.** Press it with known weights from 0.1 to 10 N, then leave one on for a minute. That gives its noise, smallest readable force, calibration and drift. Put the numbers into `robot.PAD_NOISE_KPA`, `PAD_THRESHOLD_KPA` and `PAD_GAIN` and rerun the benchmark.
3. **One real photo of a device panel** from the USB camera at 12 cm, through `rgbperceive.py`. That shows how much the clean renders flatter segmentation.
4. **Calibration offsets.** Command the arm to touch three known points on the desk board and compare. That says whether σ 0.5° is optimistic.
5. **The real controls' forces.** Press each control on the target device with a kitchen scale, so the skills' force limits (5-6 N) can be checked against what the device needs.
6. **How the device will report its state.** Pick the real target device and decide how each test's result will be read: its display, its lights, or a wire. Until that's decided, the verdict logic has nothing real to read.

Next: [Results](results.md) · [Force sensing](sensing.md) · [How it works](how-it-works.md)
