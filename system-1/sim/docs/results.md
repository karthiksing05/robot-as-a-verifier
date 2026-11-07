# Results

[← Back to the overview](../README.md)

All numbers are from the simulation; nothing has run on hardware yet (see [Sim vs real](sim-vs-real.md)). The headline is the team's setup: the USB camera, servos as soft as the team's (18 N·m/rad), and the SensX 25 pad.

**Nov 7: the sim now uses the bench-measured camera and servos, and surveys with the wrist camera instead of the iPhone.** The team's setup was rerun on the new model on the same 16 devices; its rows are marked "new model". Every other number on this page is from the earlier model (a 1280x720 camera from the datasheet, guessed servo numbers, an iPhone survey) and wasn't rerun.

## Headline: end to end on devices nobody had seen

The whole pipeline, from survey to report, on preset device C and 15 generated devices (seeds 1650 to 1664). Those seeds were reserved on Nov 5, before the last round of fixes, and never used to develop or tune anything. Each generated device gets a random spot on the desk, and every device gets its own joint calibration errors (standard deviation 0.5° by default).

| Setup | Tests attempted | Passed | Failed | Missed | Devices with every test passed |
|---|---|---|---|---|---|
| **Team's setup, new model** | 115 | **110 (96%)** | 0 | 5 | 13 of 16 |
| Team's setup: soft servos + SensX pad | 122 | 119 (98%) | 0 | 3 | 14 of 16 |
| Same arm, load cell instead of the pad | 122 | 120 (98%) | 0 | 2 | 14 of 16 |
| Same arm, servo current only | 122 | 116 (95%) | 0 | 6 | 11 of 16 |
| Same arm, ideal 3D sensor (reference) | 117 | 115 (98%) | 0 | 2 | 14 of 16 |
| Team's setup with ±2° joint calibration error | 109 | 104 (95%) | 0 | 5 | 12 of 16 |

"Attempted" leaves out tests the planner refused before moving. Those were all knobs, which need a pinch grip: 3 or 4 per setup. It also leaves out parts the robot never found, because a part it can't recognise gets no test at all. That's why the ±2° row is smaller: with calibration error the robot found 101 parts on these 16 devices, against 109 in the team's setup. The ideal sensor's arm has no gearbox friction model ([why](sensing.md#ideal-3d-sensor-default)), so its scans and plans differ slightly too.

On the new model the team's setup found 102 parts against 109. Nearly all of the gap is device 1660, where it found none (see [what it still misses](#what-the-teams-setup-still-misses)). Elsewhere it found a slider on 1653 and 1663 and a door on 1661 that the earlier model missed, and missed a toggle on 1659 and a door on 1662 that the earlier model found.

The earlier-model numbers include all three overnight fixes. The last one (installed Nov 6, 03:16) only changes lever pushes in the three sensing modes, so for it the 11 devices with toggles were rerun on the installed code; runs on the other devices, and with the ideal sensor, are unchanged by it.

No test anywhere came back FAIL. A FAIL here would have meant the robot reported a working control as broken, since none of these devices had a broken control. Every miss was the robot failing to carry out a test properly, which it reports as MISSED rather than blaming the device. There were no crashes and no safety stops.

### By kind of control

| Setup | Buttons | Toggles | Sliders | Dials | Doors |
|---|---|---|---|---|---|
| **Team's setup, new model** | 41/41 | **13/18** | 20/20 | 22/22 | 14/14 |
| Team's setup | 45/45 | 21/22 | 17/18 | 21/22 | 15/15 |
| Load cell | 45/45 | 21/22 | 18/18 | 21/22 | 15/15 |
| Servo current only | 45/45 | 20/22 | 17/18 | 19/22 | 15/15 |
| Ideal sensor | 45/45 | 16/18 | 20/20 | 20/20 | 14/14 |
| Team's setup, ±2° error | 44/44 | 13/16 | 16/16 | 16/18 | 15/15 |

Buttons and doors never missed. Toggles were the weakest kind before the Nov 5-6 fixes, and on the new model they are again: every miss in the team's setup is a toggle flip. The "Dials" column counts dial turns only, since every knob turn was refused.

### What the team's setup still misses

On the new model:

| Device | Test | What happened | Notes |
|---|---|---|---|
| 1660 | Every part | The survey found the panel (tilted 50°, true 49°), but segmenting the scan gave 1 outline from OWLv2's 20 boxes, and that outline fitted no kind of control. The robot planned 0 tests | The earlier model found all 8 parts here and passed 9 of 9. Not investigated yet |
| 1654 | Both toggle flips | "The force let go before the push ended: the pad slipped off the lever" | The scan underestimates how far this lever leans (the lever's tip is taken from its highest height readings, and stray readings pull it toward the pivot), so both flips are aimed short. The earlier model missed one of the two |
| 1656 | Both toggle flips | "The lever still pushed back (3.2 N) when the push ran out, so it never went over centre" | Passed on the earlier model. Not investigated yet |
| 1664 | The toggle flip | The same: the lever still pushed back (4.0 N) when the push ran out | Passed on the earlier model. The slide and the dial turn the earlier model missed here now pass |

### How long a test takes

On the development laptop (an RTX 4050 laptop GPU), the earlier model took about 2 minutes of computing per device from survey to report, about 48 s of it in processing the camera scan (image models, stitching and the height sweep). The new model's 1080p frames make that about 2.5 to 3 minutes, with two devices running at once (the last two runs took 46 minutes each, for a reason not looked into, and are left out). In simulated robot time a full run is 4 to 8 minutes. Soft servos and sensing slow the arm's moves near contact.

## Before and after the Nov 5-6 fixes

The same benchmark was run on the evening of Nov 5, before the fixes, on preset C and seeds 1500 to 1509. Those are different devices, so this isn't a strict comparison. The governor that kept the laptop's memory safe killed a few of those runs: the servo-current row covers 10 devices (1506 is missing).

| Setup | Before: passed | Before: toggles | After: passed | After: toggles |
|---|---|---|---|---|
| Team's setup | 80/88 (91%) | 6/14 | 119/122 (98%) | 21/22 |
| Servo current only | 72/81 (89%) | 4/12 | 116/122 (95%) | 20/22 |
| Ideal sensor | 86/88 (98%) | 10/12 | 115/117 (98%) | 16/18 |

On a fixed set of fresh devices, the reviewer measured the toggle fix alone with the ideal sensor: toggle flips went from 4 passed and 6 missed to 10 passed and 0 missed. Details are in [How we got here](iteration-history.md#the-overnight-round-nov-5-to-nov-6).

## The pieces on their own

### Perception

`rgbperceive.py`, on 250 scans (devices 1000 to 1049 under 5 arm setups): 94.6% of parts found with the right kind. The depth-camera pipeline scored 99.4%, but with a depth camera modelled as near-perfect. Modelled realistically, as a stereo pair that needs surface texture, it collapsed (see [How we got here](iteration-history.md#2-the-depth-camera-that-only-worked-in-the-sim-nov-3-to-nov-4)). Heights have a 0.18 mm median error, with 97% within 1 mm. On fresh soft-servo devices (1100 to 1149) it was 93.0%. Toggles are the hardest kind: about a quarter come out as "unknown" parts, which are then not tested.

### Touch

`touch.py`, on soft-servo devices 1100 to 1107:

| Sensing | Touched plane error (median / worst) | Peak force during a touch (median / worst) |
|---|---|---|
| SensX pad | 0.21 / 0.59 mm | 2.4 / 3.2 N |
| Load cell | 0.28 / 0.47 mm | 2.5 / 4.5 N |
| Servo current only | 0.28 / 0.55 mm | 4.5 / 7.1 N |
| Ideal sensor | 0.26 / 0.47 mm | 0.8 / 1.5 N |

The camera alone gets the panel's plane to within 1 to 2 mm typically and 5.5 mm at worst. Touch brings that under 0.6 mm.

### Skills on true part positions

Perception is taken out of the loop here: the skills get each part's true position. These runs were made before the last toggle fix, which recovered a few more toggle flips in the sensing modes. 18 devices (1320 to 1327 and 1600 to 1609), counting passed / missed:

| Servos | Ideal sensor | Servo current only | SensX pad | Load cell |
|---|---|---|---|---|
| Soft (18 N·m/rad) | 132 / 0 | 128 / 4 | 130 / 2 | 129 / 3 |
| Stiffer (36 N·m/rad) | 131 / 1 | 127 / 5 | 132 / 0 | 132 / 0 |

There were no FAILs, no safety stops, and the largest force held for 20 ms was 10.2 N, under the 15 N cap. That worst case was servo current only on the stiffer servos. With the pad, the worst held force was 7.9 N. The last toggle fix has a cost here: right after a lever snaps over, the pad now hits it harder, up to 8.8 N held for 20 ms in its own tests (at most 5 N with the ideal sensor).

## What these numbers don't tell you

- Sim images are cleaner than real ones, and the devices come from one generator. Treat the perception and end-to-end numbers as an upper bound.
- The pass counts cover only parts the robot found, and knobs are never tested.
- No device had a broken control, so whether the robot catches a real fault (a FAIL that's correct) is untested. The simulated devices have no fault injection.
- In the sim, verdicts come from each device's simulated microcontroller. A real product would need its state read some other way, for example from its display.
- The pad's and load cell's noise and calibration figures are assumptions. A bench test with known weights would replace them.
- The servo stiffness is uncertain. The skills matrix covers both 18 and 36 N·m/rad, but the end-to-end benchmark ran at 18 only.
- There was one run per device and setup. The sim is deterministic, so a rerun gives the same answer, but 16 devices is a small sample: one device more or less moves a percentage by several points.

## Reproduce

```bash
cd system-1/sim
PYTHONUTF8=1 python tools/bench.py runs/bench.jsonl slop18 1650 --sensing tactile
```

The new model's results are in [`data/bench_nov7_team.jsonl`](data/bench_nov7_team.jsonl), measured at commit `56e7895`. Since then main has changed only docstrings and the real-camera driver, which the sim doesn't run. The earlier model's raw results are in [`data/bench_final.jsonl`](data/bench_final.jsonl), with the md5 of every code file they were measured on in [`data/bench_final_code_md5.txt`](data/bench_final_code_md5.txt). The "before" run is [`data/bench_before_night_fixes.jsonl`](data/bench_before_night_fixes.jsonl). Each line holds one device's full step list with every verdict and reason.

Next: [Force sensing](sensing.md) · [How we got here](iteration-history.md) · [Sim vs real](sim-vs-real.md)
