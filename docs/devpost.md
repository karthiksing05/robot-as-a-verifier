## Inspiration

Some of the fastest recent progress in AI-assisted research has come from automatic verifiers. In mathematics, proof assistants like Lean check every step of a proof mechanically, so a model can propose thousands of attempts and keep only the ones that check out. In combinatorics and complexity research, systems now propose new constructions and bounds, and a short program scores each one instantly. The pattern is the same each time: a generator proposes, a verifier that can't be argued with decides, and the loop runs fast enough to iterate. A good verifier is what turns a model's guesses into progress.

Physical hardware has nothing like this. A prototype gets handed to a few testers, someone writes "button 2 feels sticky," and a week later a designer guesses at a fix in CAD and reprints. Nobody can tell whether the new revision is actually better without testing it all again by hand. So hardware can't iterate the way a proof search can, and an AI that designs physical things has no ground truth to learn from, only its own opinion of its work.

We wanted to build that missing verifier: a robot that tests the real object with force and vision, writes evidence you can trace, and scores every revision on the same tests, so a fix only counts if the score goes up.

Medical hardware is where this matters most. Infusion pumps, insulin pens, glucose meters, hospital beds and lab instruments like centrifuges are used by tired clinicians, older patients and people with arthritis or limited grip. A button that takes too much force, a latch that needs a pinch, or a step the manual gets wrong isn't an annoyance there, it's a safety risk. Medical devices already have to go through usability testing before they reach patients, and today that is slow, manual and hard to repeat. A robot verifier can run the same procedure on every revision, flag a control that's too stiff for weaker hands, and check a fix the day it's printed. That's why our test subjects are lab appliances, a centrifuge and a microwave, and why rules like "usable with no thumbs" are tests the robot runs, not guidelines.

One rule held the project together: **the model thinks, code moves, sensors decide.** Whatever proposes a plan or a fix has no say in how it's scored.

## What it does

Robot-As-A-Verifier (RAAV) is a verifier for hardware R&D. You give it a product, its instruction manual and, if you have one, its CAD model. A low-cost robot arm (an SO-101 with a $19 wrist camera) then:

1. **Finds the controls itself.** No CAD and no fiducial tags are needed. It scans the panel with the wrist camera, finds buttons, switches, knobs, lids and wells, and measures where they are and which way they face.
2. **Builds a test plan from the manual.** An LLM reads the manual and turns it into steps ("power on, set speed, close lid, press START"). A person approves the plan before the arm moves.
3. **Runs the tests.** The arm presses, flips, turns, hook-pulls and places, and every step ends on force and on what the appliance itself reports over Wi-Fi. If the arm misses, it can re-calibrate itself and retry.
4. **Writes bug reports you can trace.** Each finding says what happened, what the manual says should happen, the force trace and frames as evidence, and links back to the exact step. A robot's own miss is reported apart from a real device fault, and a failure that doesn't repeat is reported as intermittent.
5. **Fixes the CAD.** A CAD analyst agent reads the findings, works out the root cause from the actual geometry, edits the model (in Onshape on its own branch, or in CadQuery offline), and must pass automatic geometry checks: only the faulty control's reprintable part changes, nothing collides, parts still move freely, and the robot can still reach and hook each control. A person approves the patch.
6. **Retests.** The patched part goes back through the same tests. The fix only counts if the reward (control coverage × pass rate, recomputable from the logs) goes up.

You can watch and steer all of this from a web Console: a live 3D view of the arm, the camera feeds, the test flowchart, approvals, pause/skip/prioritize, and a one-click replay of any past run.

Our test subjects are two mock lab appliances we built at the event: the **MC-6 centrifuge** and the **MW-1 microwave**, each with real buttons, a switch, a knob, a lid or door, a display and an Arduino Uno R4 WiFi reporting its state.

## How we built it

We split the project into two systems that talk through a deliberately narrow channel.

**System 1, the robot.** Perception, inverse kinematics, motion skills, safety limits and verdict rules. It never calls an LLM.
- Perception: OWLv2 finds candidate parts, SAM 2.1 outlines them, and a plane sweep over nearby wrist-camera photos gives heights. Shape rules classify each part, and Claude Haiku names the ones with faint labels from the manual and their place on the panel.
- Skills: `press`, `flip`, `turn`, `hook_pull`, `pick`, `place`, all done with the SO-101's stock gripper and each guarded by a 15 N hard force cap and a torque gate. Force comes from the servos' own load estimate, with no added sensor.
- Simulation: a MuJoCo model of the SO-101 rebuilt from our bench measurements (field of view, lens fit, servo dead zone, reading jitter), with 12 hand-authored appliances and seeded random ones.

**System 2, the harness.** The only place an LLM runs: planning from the manual, steering, reports, memory, reward, the CAD analyst and the Console.
- It reaches System 1 through **seven MCP tools**. It can start named routines from a closed list. It has no tool that moves a joint, and System 1 clamps every parameter. A model turn takes seconds while the arm's control loop runs at 50 Hz, so a prompt should never be able to drive a motor.
- Every model call in the harness goes through **Snowflake Cortex**, and the model is a config value (details below). Opus 5.5 runs the CAD analyst.
- The CAD analyst works through its own MCP tools (`get_part`, `measure_gap`, `write_part`, `check`, `submit_fix`) against **Onshape** branches or a sandboxed CadQuery workspace.

**Appliances and networking.** Each appliance's Arduino posts its sensor state over HTTPS to a **Vultr** server, which also carries System 2's tool calls to the robot (details below). If a board goes quiet for 2 seconds, the next step stops instead of running blind.

**The Console.** A Vite + React app with a FastAPI/stdlib bridge. The browser draws the arm from streamed body poses rather than server-rendered frames, so it stays smooth, and every run replays in the same 3D view from its `events.jsonl`.

## How we use Snowflake Cortex

**Why it's integral.** System 2 is the only part of RAAV that thinks, and every one of its model calls goes through Snowflake Cortex: turning the manual into a test plan, deciding what to do when a step fails, handling a person's steering messages, and writing the bug reports. We could only make claims about the models themselves because we had one endpoint and one credential for all of them.

- **Four frontier models, one fair comparison.** Cortex serves Claude Haiku 5.5, Claude Sonnet 5.5, GPT-5.4 and Grok 4.7 behind the same account. Every model gets the same prompts, the same tools and the same test devices, and a rule-based baseline runs alongside. Switching models is one config value, never a code change, so nothing gets tuned to one model.
- **A cost ledger for every call.** Each request is appended to a ledger with its input, output, cached tokens and latency, priced in Snowflake AI credits. `rav spend` totals it per model, and `rav eval --budget-usd` won't start a run that could cross the cap. Our first full model round, with its connection tests, cost 0.5 credits.
- **Prompt caching.** The system prompt and tool definitions are cached on Cortex's Messages API, so the long, repeated parts of each turn are cheap.
- **What it showed.** In round 1 (seven scenarios, from planning with a dependent step to telling a robot's miss from a real fault), all four models scored 1.00 and the rules baseline 0.49. That showed tool calling and image reading worked for every model through our harness. It also showed we needed harder rounds, with random planted faults and a 5% chance of an injected error on each action, to separate them.

| Model | Tokens | Tool errors | Median turn |
|---|---|---|---|
| Claude Haiku 5.5 | 388,590 | 1 | 3.4 s |
| Claude Sonnet 5.5 | 243,671 | 3 | 2.5 s |
| GPT-5.4 | 157,810 | 4 | 2.8 s |
| Grok 4.7 | 221,060 | 3 | 2.9 s |

**Challenges.**
- **Before Cortex, we couldn't compare anything.** Our first model test used free API keys from different providers and hit quota limits, an overload error and an 85-second turn. Moving everything to Cortex gave us one route with no free-tier cap.
- **Two wire formats.** Cortex serves Claude through the Messages API and the other models through Chat Completions. We wrote one small provider-neutral client over both, so the harness never knows which it's talking to.
- **Claude's thinking blocks are signed.** The API checks that signature when a thinking block comes back in the next turn, so the client stores each response exactly as it arrived and resends it unchanged rather than rebuilding it.
- **Small protocol surprises.** Cortex refuses requests without an `Accept` header. The newest models refuse a fixed thinking budget and need an effort level instead. Each provider names its reasoning field differently, and many send none.
- **Failing safely when the API does.** The client waits out 429 and 503 responses (honouring `Retry-After`), then falls back to another model. If the budget or the API runs out mid-run, the robot holds the arm safely or falls back to the rule plan, and the run log says so.

## How we use Vultr

**Why it's integral.** Our rule is that sensors decide, and the most important sensor is the appliance itself: did START actually start the centrifuge, did the lid really close. That signal has to get from two Arduinos to the robot reliably and securely, at a venue where everything sits on a phone hotspot. A hotspot's carrier network accepts no incoming connections, and the laptop's address changes. A Vultr server gives us the one fixed, public, TLS-secured address everything can reach.

- **Appliance readouts.** Each Arduino Uno R4 WiFi posts a JSON snapshot of its sensors over HTTPS to Vultr whenever something changes, and at least every 0.5 seconds. Caddy on Vultr terminates TLS and passes each snapshot on to System 1.
- **A reverse tunnel to the robot.** Since nothing can connect in to the hotspot, System 1 opens one outbound WebSocket to Vultr. A relay carries both the appliance snapshots and System 2's MCP tool calls down that tunnel. It forwards raw TCP streams without reading the MCP messages.
- **The harness runs in the cloud.** System 2 runs on the Vultr server and reaches the robot's seven tools through the relay's loopback port. The arm stays on the table, and the planner never needs to be on the same network.
- **A hosted Console.** Vultr also serves a read-only build of the Console, so anyone can replay our recorded runs in 3D from a browser.

**Security we designed in.**
- Three separate credentials: one for the tunnel, one for the MCP tools (which can start robot routines), and one key per appliance, which can only publish that appliance's readings.
- Caddy forwards only POSTs on the public readout route. A public request to `/mcp`, or a GET for a reading, returns 404. A board's key gets 401 on any other board's route.
- A board gets its success response (204) only after System 1 has accepted the snapshot. If the tunnel is down, the board sees an error instead of a false acknowledgement.

**Challenges.**
- **TLS on an Arduino.** The Uno R4 WiFi checks certificates against a root CA bundle in its Wi-Fi chip's firmware, so we needed a proper DNS hostname with a matching certificate. Caddy manages it, and Let's Encrypt's short-lived IP certificates are the fallback.
- **Wi-Fi that blocked the buttons.** The board's Wi-Fi joins and HTTPS calls are synchronous, so a slow retry froze button and sensor polling. We bounded the timeouts and spaced out retries after an error.
- **Presses too short to see.** A quick button press could start and end between two snapshots, so the robot never saw it. The firmware now queues up to eight debounced changes while a POST is in flight, and System 1 keeps the last 32 changes per device. A queued change is dropped after 2 seconds, so an old press can't replay after an outage.
- **Stale data must never pass as fresh.** Every reading carries its age. A reading older than 2 seconds is marked stale, and the real arm refuses to judge a step on it.
- **Reconnects in the middle of a call.** A dropped tunnel can interrupt an MCP call partway through, so after a reconnect the harness checks the robot's status before repeating a command, rather than pressing twice.
- **Debugging blind.** With boards, a hotspot, a VPS and a laptop in the chain, we gave every hop a clear signal: the board logs the HTTP status (`204` accepted, `401` bad key, `502` Vultr can't reach System 1), and `rav readout --watch` on Vultr shows each device as fresh, stale or silent.

## Challenges we ran into

Nearly every big design change came from a measurement that disagreed with our plan.

- **A depth camera that only worked in simulation.** Our sim said the RealSense D405 passed 29 of 29 tests. When we modelled it as what it really is, a stereo pair with no projector, it found 28 of 66 parts on plain plastic and lost every door and display. We dropped it and designed around one cheap RGB camera. Monocular depth networks were 1.6 to 8 times off at 12 to 20 cm, so those went too.
- **Force from servos alone.** Our skills were written for a perfect force sensor. On servo feedback only, they passed 0 of 89 steps, because gear friction hides anything from about 0.4 N to 16 N. Using position error instead of current, zeroing the estimate once the arm slows near a part, and keeping thresholds above the noise got us to 84 of 89.
- **Designing for the gripper we actually have.** Our early simulation modelled a fingertip probe with a pressure pad, but the real arm is a stock SO-101 gripper with nothing added. We rewrote every skill for its jaws: press with the closed tip, flip a lever between open jaws, pinch-turn a knob and re-grip when it slips.
- **Toggles that stopped short.** SAM's outline of a switch includes its lever, which put the pivot 2 to 5 mm off. Trimming the lever before measuring took toggle flips on unseen devices from 4 passing to 10.
- **Keeping the evaluation honest.** It's easy to tune prompts on the devices you score on. We banned device names, layouts and fault types from prompts and harness code (a test scans for them), sampled faults from a generic catalogue, injected a 5% per-action chance of the arm or world misbehaving, and kept planted faults in an answer key only the scorer reads.
- **Real-world calibration at 5 a.m.** Getting the real scan right meant dozens of small changes: how far the camera sits from the panel (140, 155, 160, 170 mm), how many views to take, how far past the cap top to push a real button, and waiting for the wrist camera to stop shaking before trusting a frame. On the appliance side, we had to swap sensor pins and recalibrate the MC-6's lid and tube sensors.
- **API limits.** Onshape's free tier locked one endpoint for 20 hours, which pushed us to build the offline CadQuery path.

## Accomplishments that we're proud of

- **The full loop works end to end in simulation.** On the MC-6 centrifuge, the robot found that a tube dropped into well A stopped 8.15 mm above its seat, so START refused with `TUBE`. The CAD analyst (Opus 5.5, 14 tool calls, 102 seconds, $0.43) traced it to a bore 0.4 mm narrower than the tube body, widened it and added a 45° lead-in. On retest, the tube seated within 0.97 mm and the centrifuge ran. The analyst never saw the designer's own fix and landed within 0.2 mm of it.
- **On an interval timer with three planted faults,** a Claude Haiku run found two of them through its tests, the CAD loop patched them, and the retest's reward rose from 0.42 to 0.64.
- **Perception that generalizes.** On 16 devices held back from all tuning, the sim passed 110 of 115 attempted tests (96%), with no false failures.
- **The real arm runs on our real appliance.** The SO-101 scans the MC-6 panel with its wrist camera, finds and names the controls, flips POWER, pinch-turns SPEED and presses START, while the Arduino reports what actually changed.
- **A safety boundary we trust.** The LLM can plan, steer and explain, but it can't move a joint, can't override a verdict and can't approve its own CAD patch.
- **Honest numbers.** Every claim above comes from a run folder, and our docs say plainly which results are sim and which are real.

## What we learned

- **Check the sensor model against how the sensor works.** Our most expensive mistake was trusting a simulated depth camera that a real one could never match.
- **Cheap hardware can work if you're careful about noise.** A $19 camera and a plane sweep got outlines within 0.41 mm and heights within 1 mm 93 to 95% of the time.
- **Keep the model out of the loop that moves things.** Splitting thinking (System 2) from moving and judging (System 1) made the system safer and also made failures easier to diagnose. Every failure gets filed under Model, Pipeline, Robot or Device.
- **Easy benchmarks don't separate models.** In our first round, all four frontier models scored 1.00 and the rules baseline 0.49. Telling them apart needs random faults, injected errors and held-out devices.
- **Have someone other than the builder review the work.** Every fix was rechecked on seeds its author never used. That caught friction modelled at half strength, a safety cap tripping on harmless moves, and one fix that had to be reverted.

## What's next for Robot-As-A-Verifier

- **Close the loop on real plastic.** Print the analyst's patched part, put it back in the appliance, and show the reward rise on the physical arm, not only in the sim.
- **More skills and more products.** Finish door swings and placing into wells on the stock gripper, and test products we didn't design, including a remote and receiver.
- **Read the product, not the wires.** Today verdicts read the appliance's own Wi-Fi readout. Reading displays, LEDs and motion from the camera would let RAAV test products nobody instrumented.
- **A shared vocabulary for devices.** Describe every product as parts, relations, procedures and test properties, so the planner composes tests from general pieces instead of learning one appliance at a time.
- **A reward for AI-designed hardware.** The long-term goal is to make RAAV the verifier that scores generated designs, so a design model can improve against physical tests instead of its own judgment.
- **Accessibility as a test property.** Rules like "usable with no thumbs" or "opens under 5 N" become tests the robot runs on every revision, so products work for weaker hands from the first print.
