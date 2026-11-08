# How RAAV's design changed

Each turn below came from a measurement or a failure that disagreed with the plan. For each one: what we tried, what we learned, and why we changed course. Numbers are from the simulation unless a line says otherwise. Nothing has run on the real arm yet. Anything not done yet is marked **planned** or **in progress**.

The Console's wiki shows the same turns as a timeline (Wiki → Journey), and the model results under Wiki → Models.

Sources: [sim iteration history](../system-1/sim/docs/iteration-history.md), [sim results](../system-1/sim/docs/results.md), [decisions](decisions.md), [frontier integration plan](frontier-integration.md), and the model runs in `system-2/runs/`.

## The robot

### 1. No CAD, no tags (Nov 1 to 3)

- **Tried:** The first sim knew the appliance's CAD model and found it from a printed tag. With a camera look before testing, a 12-placement plan passed 58 of 60 steps, against 18 of 60 without the look.
- **Learned:** It worked, but only on products we had modelled and tagged. Published button-pressing robots find targets in 2D, end every press on force, and fix the last millimetre by touch or wrist markers. One elevator robot got 298 of 305 presses that way (Mueller et al., ECMR 2023).
- **Changed:** On Nov 3 the goal became no CAD and no tags. The robot finds and classifies the controls itself.

### 2. The depth camera that only worked in the sim (Nov 3 to 4)

- **Tried:** A close-range wrist depth camera (RealSense D405). In the sim, three films passed 10 of 10, 9 of 9 and 10 of 10 tests.
- **Learned:** The sim added noise to perfect depth, but the real D405 is a stereo pair with no projector, so it can't measure plain plastic. Re-modelled as a real stereo pair, perception found 28 of 66 parts and lost every door and display.
- **Changed:** Stop trusting a sensor model we hadn't checked against how the sensor works, and design around a plain camera.

### 3. One cheap camera, plus touch (Nov 4)

- **Tried:** OWLv2 boxes and SAM outlines for finding parts in 2D, heights from the shift between nearby photos (a plane sweep), and fingertip taps for the panel's plane. Four prototype tracks were each reviewed independently before anything was built.
- **Learned:** Outlines came within 0.41 mm, plane-sweep heights were 93 to 95% within 1 mm, and the touched plane was 0.15 to 0.38 mm off. Monocular depth networks were 1.6 to 8 times off at 12 to 20 cm, so they were rejected.
- **Changed:** This became the perception pipeline, using the team's $19 USB wrist camera.

### 4. Force from the servos alone (Nov 4 to 5)

- **Tried:** The skills, written for a perfect force sensor, on servo feedback only.
- **Learned:** They passed 0 of 89 steps. Gear friction hides pushes from about 0.4 N up to 16 N, and the best effort signal is the servo's position error, not its current.
- **Changed:** Zero the estimate once the arm slows near the part, ignore it until then, and keep thresholds above its noise. That brought it to 84 of 89. Reviews then found friction modelled at half strength and a safety cap tripping on harmless moves, and both were fixed.

### 5. A pressure pad on the fingertip (Nov 5)

- **Tried:** The team's SensX 25 pad, modelled on the probe's face.
- **Learned:** MuJoCo's point contacts put a whole push on one cell, which saturated, so presses ran to 10 to 15 N.
- **Changed:** Spread each contact over a disc, as the pad's rubber does. With the clean signal, contact thresholds dropped from 2.5 N to 0.3 N. On the skills matrix the pad missed no attempted step, while servo-only sensing missed 4.

### 6. Reviews on devices the builder never saw (Nov 5 to 6)

- **Tried:** 52 end-to-end runs across five arm setups. There were no crashes and no false failures, but toggles passed only 2 of 10 with stiff servos.
- **Learned:** SAM's outline of a toggle includes its lever, so the pivot was placed 2 to 5 mm off and flips stopped short. Separately, a toggle's 2 to 3 N push-back sat right at the servo estimate's noise floor.
- **Changed:** Trim the lever before measuring, and wait for the pad to pass the lever's centre before deciding it let go. Toggle flips on fresh devices went from 4 passing to 10. Every fix was rechecked by a second agent on seeds the builder never used, and one fix that caused false safety stops was reverted.

### 7. Two systems, one narrow channel (Nov 6, D28)

- **Problem:** A model turn takes seconds, while the arm's control loop runs at 50 Hz. A prompt must never be able to drive a joint.
- **Changed:** System 1 owns the arm, its perception, its safety limits and its verdict rules. System 2, the harness and the model, can only start named routines from a closed list of skills, and the robot clamps every parameter. Telemetry goes one way, to the screen, never to the model.

### 8. The sim, rebuilt from bench measurements (Nov 7)

- **Problem:** The camera and servo numbers came from datasheets and guesses, and the survey used an iPhone the team dropped.
- **Changed:** The sim now uses the measured field of view (75 × 47°), lens fit (0.19 px), servo dead zone and reading jitter, and surveys with the wrist camera. On 16 devices reserved before the last fixes and never used for tuning, the team's setup passed 110 of 115 attempted tests (96%), with no false failures, and every test passed on 13 of the 16 devices.

## The model

### 9. An honest test world (Nov 7)

- **Problem:** The only planted fault was one stuck button, so a model could look good by luck. A robot slip followed by a clean retest still reported a broken device.
- **Changed:**
  - Faults are sampled by seed from a generic catalogue.
  - In some runs, each action has a 5% chance that the arm or the world misbehaves. Errors change the world, never the verdict, so the sensors still decide.
  - Planted faults and injected errors go in an answer key that only the scorer reads.
  - A retest rule in code: repeated failures are a failure, and a failure followed by passes is reported as intermittent.

### 10. General, not taught to the test (Nov 7)

- **Problem:** Prompts tuned on the devices we score on would make every result meaningless.
- **Changed:**
  - No device names, layouts or fault types in prompts or harness code. A test scans for them and fails on a match.
  - Devices differ only by data.
  - Dev, validation and held-out sets are kept apart.
  - A fix prompted by a held-out failure must name its general class.

### 11. Four models through one route (Nov 7)

- **Tried:** A first probe of several models on one free API key. It hit quota limits, an overload error and an 85-second turn.
- **Changed:** Compare Claude Haiku 5.5, Claude Sonnet 5.5, GPT-5.4 and Grok 4.7 through Snowflake Cortex. Every model gets the same prompts and tools, the model is a config value, and a rule-based baseline runs on the same tests.

### 12. Round 1: the models all pass (Nov 7)

- **Tried:** Seven short scenarios on a fake robot, one run per model:
  - planning from a manual with a dependent step
  - a real fault in that procedure
  - a real fault next to a robot's miss
  - a failure that doesn't repeat
  - a refused request
  - a safety stop on a healthy product
  - reading a number off an image
- **Learned:** All four models scored 1.00 and the rules baseline scored 0.49. Round 1 doesn't separate the models. It shows that tool calls and image reading work for each one through the harness. Where they did differ:

  | Model | Tokens | Tool errors | Median turn |
  |---|---|---|---|
  | Claude Haiku 5.5 | 388,590 | 1 | 3.4 s |
  | Claude Sonnet 5.5 | 243,671 | 3 | 2.5 s |
  | GPT-5.4 | 157,810 | 4 | 2.8 s |
  | Grok 4.7 | 221,060 | 3 | 2.9 s |

  None of them returned reasoning text, because thinking was off for this round. The round, with the connection tests before it, used 0.5 Snowflake credits. Source: `system-2/runs/soft-1107-154005` and `soft-1107-154819`.
- **Changed:** Harder rounds, below.

### 13. Harder rounds (in progress)

- **Round 2 (running):** The four models on generated sim devices, two runs each, with a random planted fault and a 5% per-action error rate.
- **Round 3 (planned):** The top two models on the centrifuge in the sim. Rev B should pass its whole manual workflow, and Rev A has three built-in faults.

## The devices

### 14. A vocabulary for devices (in progress)

- **Problem:** A model taught one appliance at a time learns that appliance, not appliances.
- **Changing to:** Every device is described with shared pieces: parts, relations, procedures and test properties. The model composes its tests from those pieces. The write-up is in progress in `docs/device-theory.md`.

### 15. Ten hand-made test devices (in progress)

- **Problem:** Generated devices vary in layout more than in how they work.
- **Changing to:** Ten hand-made devices plus the centrifuge. Each is tagged with the theory pieces it exercises and assigned to the dev, validation or held-out set. The write-up is in progress in `docs/devices.md`. A held-out device's faults are never shown.

## Next (planned)

- **The real arm:** bench tests first, then the full pipeline on the printed appliance with its planted fault.

## Updating this page

Model results on the Console come from run folders:

1. List a finished round's folders in `system-2/harness/config/model_rounds.json`.
2. Regenerate the page data from `system-2/`:

   ```
   uv run python -m rav_harness.results_page
   ```
