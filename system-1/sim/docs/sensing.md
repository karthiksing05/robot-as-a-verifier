# Force sensing

[← Back to the overview](../README.md)

The robot needs to feel when the fingertip touches something, and how hard it's pushing. Without that it can't stop a press at the right force, find the panel by touch, or notice it hit the wrong thing. Four ways of doing that were modelled and compared. The team's setup, the SensX 25 pad plus the servos, is the headline. The others are there to show what it gains or loses.

## The four options

| Option | Flag | What it is | Cost | Feels force along the probe | Feels sideways force |
|---|---|---|---|---|---|
| **SensX 25 pad + servos** (the team's) | `--slop --sensing tactile` | A thin 5 x 5 pressure-cell film on the fingertip's face | Pads the team already has | Yes, cleanly, from the pad | From the servos (noisy) |
| **Load cell + servos** | `--slop --sensing loadcell` | A 2 kg bar load cell (a metal beam with strain gauges) behind the probe, read by an HX711 amplifier chip at 80 Hz | About $10 | Yes, from any contact on the probe | From the servos (noisy) |
| **Servos only** | `--slop --sensing current` | No sensor: force estimated from each servo's position error | $0 | Roughly, about 2.5 N of noise | Roughly |
| **Ideal 3D sensor** (reference) | default | The sim's true contact force, in all three directions, with no noise. The nearest real part is a 6-axis force/torque sensor, which costs hundreds to thousands of dollars | n/a | Perfectly | Perfectly |

The ideal sensor is the sim's default because it's the easiest way to develop skills. Read it as the best any sensor could do, so the other rows show what each real option costs in results.

## How each is modelled

### Servos only (`current`)

A bus servo is a position controller: it pushes harder the further its shaft sits from its goal. So the gap between goal and present position, measured in encoder counts (the servo's position sensor has 4096 counts per turn), tells you its torque. The rig reads that gap on every servo 100 times a second. It subtracts what its own model says holding up and moving the arm costs, and turns the rest into a force at the fingertip through the arm's geometry.

Three things make this hard:

- **Gear friction.** The gearbox's friction is modelled from a published bench measurement of these servos (Rhoban's BAM project), at about 0.28 times the load held and 0.43 times when moving slowly. It hides small pushes, and while joints move it reads as a push that isn't there. So skills zero the estimate once the arm is creeping toward a part, and ignore it until then.
- **Noise of about 2.5 N.** Every contact threshold has to sit above that, so the fingertip presses harder than it needs to.
- **Impacts shorter than one 10 ms reading never reach it.** The arm's own inertia absorbs a very short knock before the servos feel it. Speeds near contact are kept low for that reason.

It also sometimes reads a contact near the panel with nothing touching. When the robot touches bare panel to find its plane, a touch that lands more than 6 mm from the camera's plane is thrown out and retried. The camera's plane was at most 5.5 mm off on 74 test devices, and these false touches put the plane 7 to 23 mm off.

### SensX 25 pad + servos (`tactile`)

The real SensX 25 is a 19 x 13 mm film with 5 x 5 cells, each reporting whole kPa from 0 to 534. The sim's fingertip is a 12 mm disc, so the model lays the sensor's grid over that disc: only the middle cells can ever be touched, each cell keeps the real sensor's size, and the pad is read at the servos' rate. Each MuJoCo contact on the face is spread over a 3 mm disc, as the pad's rubber cover would spread it, and split among the cells it covers. MuJoCo contacts are points, and without the spread one cell took the whole push and saturated at 5.3 N.

The pad only feels force pressing into its face. So it supplies the force along the probe, and the servos still supply the force across it. Two things follow:

- Along the probe, contact thresholds drop from 2.5 N to 0.3 N. The pad's zero doesn't drift with friction, so presses and touches stop early and gently.
- A push with the pad's edge, like flipping a toggle lever sideways, is invisible to the pad and falls back on the servos.

The pad's noise (1 kPa per cell), threshold (3 kPa) and calibration error (reads 15% low) are guesses, because nothing published gives them. A 15-minute bench test with known weights would replace them; see [Sim vs real](sim-vs-real.md).

The pad also says where on its face the pressure is (`SimArm.pad_centre()`). Nothing uses that yet. It could tell the robot it's pressing a button off-centre.

### Load cell + servos (`loadcell`)

A 2 kg bar load cell behind the probe feels every contact on the probe, face or rim, along the probe's axis. An HX711 amplifier samples it 80 times a second, and each sample averages its 12.5 ms window. Its errors are assumptions taken from typical HX711 builds, not measurements:
- 5 mN of noise per sample;
- a slow drift of its zero, about 10 mN over 10 minutes;
- a 2% calibration error;
- 2% of the force across the probe leaking into the reading along it.

Contact thresholds along the probe sit at 0.3 N, as with the pad. Sideways force comes from the servos, as with the pad.

Unlike the pad, a load cell can't say where on the fingertip the contact is. But it feels contacts on the probe's rim and sides along the probe's axis, which the pad's face doesn't.

### Ideal 3D sensor (default)

MuJoCo's true contact force on the probe, read every 2 ms physics step, in all three directions.

One caveat for comparisons: the gearbox friction model is only switched on together with the other three modes. So the ideal-sensor runs have a slightly easier arm as well as a better sensor.

### Pushing light parts sideways

All three real options feel sideways force only through the servos, whose estimate can't see pushes under about 2.5 N. A light slider knob pushes back with less than that, so the robot can't feel the moment the pad meets the knob. With the pad or load cell, a slide therefore measures how far it moved the knob from the moment the device's own reading starts to change. That matters when the scan misjudges a knob: on device 1401 it did, and measuring from the wrong place made the robot skip the second slide.

## Results

All on the same soft-servo arm (18 N·m/rad), except the second number in the skills row, which is the stiffer servos (36). The skills row comes from a separate test with perception taken out: the skills get each part's true position. It was measured before the last toggle fix. Full details are in [Results](results.md).

| | SensX pad | Load cell | Servos only | Ideal sensor |
|---|---|---|---|---|
| End to end, 16 unseen devices: tests passed | **119/122 (98%)** | 120/122 (98%) | 116/122 (95%) | 115/117 (98%) |
| Skills given true part positions, 18 devices: tests missed (soft / stiffer servos) | 2 / 0 | 3 / 0 | 4 / 5 | 0 / 1 |
| Touched panel plane, median error | 0.21 mm | 0.28 mm | 0.28 mm | 0.26 mm |
| Peak force during a touch, median / worst | 2.4 / 3.2 N | 2.5 / 4.5 N | 4.5 / 7.1 N | 0.8 / 1.5 N |
| False contacts near the panel | None | None | Some, caught by the 6 mm check | None |
| Says where on the fingertip it's pressing | Yes (unused so far) | No | No | No |

**What this says.** The pad and the load cell finished one test apart (119 and 120 of 122), with servo current only a few tests behind. On 16 devices, gaps that small could go either way on another 16, so don't read much into the order.

Where they clearly differ is in how hard the robot has to press and what it can trust. With servos only, every contact threshold sits above 2.5 N of noise, so touches hit 4.5 N typically and 7.1 N at worst. It also sometimes "feels" the panel when nothing is there, and only the 6 mm check keeps that from corrupting the touched plane. Either sensor on the probe cuts touches to about half that force and removes the false contacts.

The pad and the load cell are close to each other. The pad can tell where on the fingertip the pressure is, which nothing uses yet but could correct off-centre presses. The load cell feels contacts on the probe's rim, which the pad's face misses, but it adds about $10 of parts.

**Recommendation.** Use the SensX pad the team already has, with servo feedback for sideways force, as modelled here. The first job on the real arm is the 15-minute pad bench test in [Sim vs real](sim-vs-real.md). If the real pad turns out much noisier than assumed, a load cell is a cheap, simple fallback that did nearly as well.

Next: [Results](results.md) · [Sim vs real](sim-vs-real.md) · [How it works](how-it-works.md)
