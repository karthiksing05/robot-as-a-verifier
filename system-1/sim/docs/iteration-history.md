# How we got here

[← Back to the overview](../README.md)

This project trained no neural networks. The two image models, OWLv2 and SAM 2.1, are used as they were published. What improved over time was the system's design, its rules and its thresholds. That happened through a loop of building something, measuring it on devices it had never seen, and changing it when the numbers said so. This page explains that loop, then tells the story of the five big changes of direction it forced, and the final round of polish.

## The loop

```
   build ──► independent review ──► fix ──► recheck ──► next piece
     ▲        (fresh devices,         │       (did the fix
     │         own test runs)         │        break anything?)
     └────────────────────────────────┘
```

**Who did the work.** Most of the code was written by AI coding agents (separate Claude instances, each given one job and its own instructions), run in parallel and coordinated by a lead agent. Joseph, on the team, set the goals and made the calls: dropping CAD and tags, using an RGB camera, sensing through the servos, adding the SensX pad.

**Build.** One agent owns one piece of the system (perception, touch, skills, the film) and is the only one allowed to edit its files. It develops and tunes on one set of generated devices.

**Review.** A different agent, which didn't write the code, reruns it on devices the builder never saw. It does not take the builder's numbers on trust: it reproduces them with its own scripts and tries to break them. It sorts what it finds into blockers, majors and minors.

**Fix and recheck.** The builder fixes the blockers and majors. Then a reviewer checks again, because a fix can break something else. That happened twice on the last day alone (see below).

**Seeds work like a train/test split.** Every generated device comes from a numbered seed, and each piece reserves seed ranges: one for tuning, one for its reviewer, and one, never touched, for the final benchmark. For example, perception was tuned on devices 1000 to 1049 and reviewed on 1100 to 1149, and the final benchmark uses 1650 onwards. A rule that only works on the devices it was tuned on shows up as a drop on the review seeds.

**Verdicts come from the device.** A test only passes when the simulated device's own microcontroller reports the change: a button's state, a slider's value, a door's latch. The robot's account of what it did never counts.

**Claims that close off options get tested too.** Several turns below happened because a "this can't work" or "this is good enough" claim was checked against a real measurement instead of being argued about.

## How the design changed

### 1. From CAD and tags to nothing at all (Nov 1 to Nov 3)

The first sim (`demo.py`, [described here](original-demo.md)) followed the team plan: the robot knows the appliance's CAD model and finds it from a printed tag. That worked. With a camera look before testing, a 12-placement test plan passed 58 of 60 steps, against 18 of 60 without one.

On Nov 3 the goal changed: no CAD and no tags on the device. The robot should find and classify the controls itself. Before designing anything, real-world evidence was gathered on how button-pressing robots actually work. The pattern was consistent. They find targets in 2D, use depth only for the rough plane, end every press on force, and fix the last millimetre by measuring at the fingertip: wrist markers, or touching. An elevator-riding robot got 298 of 305 presses after fixing a 3 cm hand-eye error with wrist markers (Mueller et al., ECMR 2023). A mobile chemistry-lab robot went from 10 mm to 0.12 mm accuracy by touching reference points (Burger et al., Nature 2020).

### 2. The depth camera that only worked in the sim (Nov 3 to Nov 4)

The first no-CAD design used a close-range depth camera on the wrist (a RealSense D405) to measure every part's shape. In the sim it was excellent: three films passed 10 of 10, 9 of 9 and 10 of 10 tests.

But the sim's depth camera added noise to perfect depth, and a real D405 doesn't work like that. It is a stereo pair with no light projector (and an IR-cut filter, so an external projector wouldn't help), so it can only measure depth where the surface has visible texture. Plastic control panels are mostly plain. When the camera was re-modelled as a real stereo pair, perception collapsed: 28 of 66 parts found, and every door and display lost. Even with perfect depth on the plain areas, the rules for doors and displays broke on small holes.

### 3. No depth camera at all: RGB plus segmentation plus touch (Nov 4)

The team had no D405, and its plan already called for a cheap USB RGB camera on the wrist. So perception was redesigned around what a plain camera can do well:

- **Find parts in 2D** with pretrained segmentation models: OWLv2 boxes, SAM outlines.
- **Get 3D from geometry.** Line the photos up on the panel's print to fix the camera poses, then measure heights from the small shifts between nearby photos (a plane sweep).
- **Let the fingertip measure what matters most:** the panel's plane, and the heights of parts it can touch safely.

Four prototype tracks tested the pieces before anything was built, each reviewed independently:

| Track | Result |
|---|---|
| Segmentation | Outlines within 0.41 mm, 70 of 72 parts outlined |
| Geometry | Plane-sweep heights 93-95% within 1 mm |
| Touch | Touched plane 0.15-0.38 mm off |
| Classification | 99.5% right from perfect outlines |

One alternative was tested and rejected: monocular depth networks like Depth Anything. Their metric versions were 1.6 to 8 times off at 12-20 cm. On real photos of a panel with 3 mm buttons, the multi-view version recovered at most 45% of the buttons' height, and in some settings put them slightly below the panel.

### 4. No force sensor: only what the servos report (Nov 4 to Nov 5)

The team plan had a load cell. The team then decided on servo feedback only. Research found that the finest effort signal a bus servo gives is its position error (goal minus present position), not its current reading. Gear friction hides small pushes, from about 0.4 N in good poses up to 16 N in bad ones.

The skills, as written for a perfect sensor, passed 0 of 89 steps on servo-only sensing. Three changes brought that to 84 of 89:
- zero the estimate once the arm is moving slowly toward the part, so moving joints' friction is subtracted;
- ignore the reading until then;
- keep contact thresholds above the estimate's noise floor (3 N in that prototype, 2.5 N in the final model).

Reviews then found more. Friction had been modelled at half its measured strength. The 15 N safety cap tripped on harmless moves. Short impacts hid inside the reading's averaging window.

The team's actual servos (RobiServo-01, close to a 12 V STS3215) turned out several times stiffer than the 4-8 N·m per radian first feared for the kit's 7.4 V servos: roughly 17 N·m per radian at LeRobot's default gain and 34 at the factory's. That's why the skills are tested at both 18 and 36.

### 5. A pressure pad on the fingertip (Nov 5)

The team got access to TouchTronix SensX 25 pads: 5 x 5 pressure cells over 19 x 13 mm. The pad was modelled on the probe's face, with the servos still supplying sideways force.

The first version was wrong. MuJoCo treats a contact as a single point, so one cell took the whole push and saturated at 5.3 N. Presses then ran to 10-15 N because the reading never reached the force limit. Spreading each contact over a small disc, as the pad's rubber cover would, fixed it.

With the pad's clean signal, the contact thresholds along the probe dropped from 2.5 N to 0.3 N. On the skills matrix (8 devices, 2 servo stiffnesses, perception taken out), the pad then missed no attempted step, while servo-only sensing missed 4.

### The overnight round (Nov 5 to Nov 6)

A benchmark of 52 end-to-end runs across five arm setups had no crashes and no false FAILs. Buttons, sliders, dials and doors passed essentially every attempted test. Every miss but one was a toggle flip (the other was a dial turn with servo-only sensing): toggles passed only 2 of 10 with stiff servos, and 6 of 14 with the pad. Three fixes came out of that. The first two were each built by one agent and checked by another on fresh devices. The third was checked by the lead on the final benchmark's devices before it went in.

- **Toggles were measured from an outline that included the lever.** SAM's outline of a toggle takes in its lever, so the code put the toggle's pivot 2 to 5 mm too far toward the lever. It then underestimated the lever's lean, and planned a flip that stopped short of centre ("the lever still pushed back when the push ran out"). Trimming the lever off the outline before measuring brought the median pivot error from 1.0 to 0.4 mm. With the default sensor, end-to-end toggle flips on fresh devices went from 4 passing and 6 missing to 10 passing and 0 missing. A second guard was added at the same time: if the three panel taps give a plane tilted more than 5° from the camera's, one tap probably landed on a part's rim, so it is dropped and replaced.
- **The pad mode's lost slider came from the scan.** The scan had misjudged that slider's knob as 32 mm long instead of 10, so the push started 30 mm from the knob. The ideal sensor felt the knob when it got there. The pad can't feel sideways force, so the push stopped too early. Now the slide measures from the moment the device's reading starts to change. The same agent made pad mode use the pad from the first moment of every push, and added a cheap load cell as a fourth sensing option to compare against.

- **Toggle flips in the sensing modes gave up too early.** A toggle lever pushes back with 2 to 3 N, right around the servo estimate's 2.5 N noise floor. So the flip's two "the lever let go" checks fired mid-push: the arm stopped pushing, the lever sprang back, and the flip came up short. The checks now wait until the pad has passed where the lever's centre should be. On the final benchmark's 11 devices with toggles, which the agent never saw, this recovered 1 flip with the pad and 4 with the load cell, and no step got worse in 33 runs. It has a cost: once the lever snaps over, the pad now hits it harder. In the skills matrix that's up to 8.8 N held for 20 ms, against at most 5 N with the ideal sensor, still under the 15 N safety cap.

## What the reviews caught on the last day

Each row below is a problem from the final build round (Nov 5) that the builder didn't report, found by a reviewer on devices the builder never saw:

| Piece | Found by review | After the fix |
|---|---|---|
| Perception | The scan crashed on some devices, every time: all the panel samples lay on one line, so the fitted plane could tilt any way | 0 crashes in 75 runs |
| Perception | Toggles were read as buttons, so the arm pressed straight down on the lever | Toggles read as buttons: 16 → 0. Parts right overall on fresh soft-servo devices: 89.5% → 93.0% |
| Perception | Dials and knobs came out too large, so the planner refused tests on their neighbours | Median size error +1.37 mm → +0.10 mm |
| Touch | With servo-only sensing, a false contact near the panel tilted the touched plane by 7-23 mm, and every part was moved onto it | A touch more than 6 mm from the camera's plane is rejected and retried. Plane 0.2-0.5 mm off on the same devices |
| Skills | The 15 N cap could be hidden by a zero taken while already pressing | A fix was made, and then the **recheck** found the fix caused false safety stops (4 of 59 steps). It was reverted: 0 stops |
| Film | A refine failure crashed the film; on-screen text showed internal code names | Fixed, 0 crashes in 11 new runs |

## What iteration hasn't settled yet

Some things only the real arm can answer: the servos' true stiffness, how noisy the pad really is, and how much worse real camera images are than rendered ones. [Sim vs real](sim-vs-real.md) lists them, with the cheap bench test that settles each one.

Next: [Results](results.md) · [Force sensing](sensing.md) · [How it works](how-it-works.md)
