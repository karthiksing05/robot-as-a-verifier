# System 1 and System 2

**Read this before adding code.** It says which system a change belongs to, and what may cross between them. To share the short version, use [this page](https://claude.ai/artifact/6d9gQhE7LqDb9xUeMPYPDa).

> **State, Nov 7.** The folders, the seven tools, the stop rules, approval levels and crossing counts are built, and tested on the sim over a network. Rules stand in for the LLM until it's added. Still ahead: [the last steps](#whats-left).
## The split

|  | System 1: the robot | System 2: the harness |
|---|---|---|
| Job | Carry out a routine, measure it, judge it | Decide what to do, and change the plan when it's wrong |
| Holds | Detection, depth perception and 3D mapping, IK, control, skills, sensors, verdict rules, safety, local retries | LLM calls, slash commands, planner, guiding exploration, long-term memory, plan revision, reward, reports, CAD fix loop, Console |
| Runs | On the robot's machine, with no network needed. **Demo: Joseph's Windows laptop** | Anywhere that can reach System 1 and the model's API. **Demo: Joseph's laptop or Karthik's Mac** |
| Time scale | 50 Hz control loop; routines last minutes | Seconds per model turn; only between steps |
| Starts work | **Never by itself.** Only when System 2 starts a routine | When a person starts a run |
| AI | Almost no generative AI: hard classifiers, IK and fixed policies. OWLv2 and SAM stay, because they detect and outline rather than generate. **Never calls an LLM** | The only place an LLM is called |
| Never | Decides what to test next, or plans around a failure it can't explain | Commands a joint or motor, decides a verdict, or changes how a run is judged |

**Agreed at the Nov 7 sync.** System 1 holds depth perception and the 3D map of the device. System 2 will guide exploration, saying which areas of a device to look at, and later choose how each control is manipulated. It does both through routines and their steps, never by moving joints.

The test for any new code: **would it still have to work if the model's API went down mid-routine?** If yes, it's System 1. If it needs judgment across a whole run or across past runs, it's System 2.

## Repo layout

```
docs/                 what both systems must read: this page, architecture, decisions, pitch
system-1/             its own pyproject.toml and uv.lock
  interface/          the wire contract: types and tool definitions, no heavy dependencies
  server/             the tool server System 2 talks to, plus the telemetry streams
  core/               the pipeline: perception, touch, skills, verdict rules. Runs on any rig, sim or real
  sim/                the MuJoCo rig, the film and the benchmark
  hardware/           the real arm's and cameras' drivers
  arm/                SO-101 bring-up scripts and bench tests
  subjects/           device firmware: the Pico is a sensor System 1 reads
  tests/
system-2/             its own pyproject.toml and uv.lock
  harness/            run loop, slash commands, LLM, planner, memory, reward, reports
  contracts/          run events, findings, root causes, patches, reports
  cad/                CAD patching, Onshape
  console/            web front end and its server
  subjects/           CAD and manuals for the products under test
  fixtures/
  tests/
```

**Only one dependency crosses the line:** `system-2` may import `system-1/interface`. It imports nothing else from System 1, and System 1 imports nothing from System 2. Tests enforce this: [`system-2/tests/test_repo.py`](../system-2/tests/test_repo.py) and [`system-1/tests/test_boundary.py`](../system-1/tests/test_boundary.py) do. Separate lockfiles keep torch and LeRobot out of the harness, and the Anthropic SDK off the robot.

## The interface

There are two channels, because the two kinds of traffic have nothing in common.

```
              CONTROL: sparse, typed, in the model's trace
  System 2  ◄────────────  MCP tools over HTTP  ────────────►  System 1
  harness                                                      server
  console   ◄────────────  HTTP streams, one way  ───────────
              TELEMETRY: poses, force, camera feeds. For people, never in the model's context
```

### Control: what System 2 can call

| Tool | Does | Kind |
|---|---|---|
| `system_status` | State, health, the skills on offer, active routine | Read |
| `scene_get` | The latest `SceneInventory`, and a rule-based fallback plan | Read |
| `evidence_get` | One frame or force trace, by reference, when the model asks for it | Read |
| `routine_start` | Starts `explore`, `run_plan` or `home` with a policy. Returns a handle | Write |
| `routine_wait` | Blocks until the routine's next [stop](#when-system-1-wakes-system-2), or a timeout. Returns a `Checkpoint` | Read |
| `routine_resume` | Answers a stop: continue, amend the remaining steps, skip or abort | Write |
| `routine_stop` | Stops at the next step boundary | Write |

**There is no motor, joint or jog tool, on purpose.** System 2's strongest write is a named routine with bounded parameters, and System 1 clamps those parameters to its own limits. So no prompt, bug or bad plan can drive a joint directly. The hardware E-stop stays separate from all of this.

**Slash commands belong to System 2.** They are macros over these tools plus model calls, so `/explore` isn't a System 1 concept:

| Command | System 2 does | System 1 does |
|---|---|---|
| `/explore` | Recalls similar products from memory, then turns the results into a high-level plan | The `explore` routine: survey, scan, segment, map and touch. Returns the inventory and a rule-based fallback plan |
| `/test` | Sends the approved plan and policy, then handles stops | The `run_plan` routine |
| `/diagnose`, `/patch` | Root cause and CAD patch, reading evidence on request | Nothing, until the retest |

Memory reaches System 1 only as numbers: System 2 compiles what it remembers into each step's `Step.check`, and System 1 evaluates those checks without knowing where they came from.

### Why MCP, and what we rejected

| Option | Verdict |
|---|---|
| **MCP for control** | **Chosen.** Tool schemas come from our types, it matches the `tool_call` trace we already log, and the harness can show the model a subset of the tools |
| MCP for telemetry | Rejected. Sending 60 Hz poses and video through tool calls is the wrong shape, and would invite them into the model's context |
| Plain HTTP and JSON only | The fallback. Simple, but we would hand-write what MCP gives us. Worth switching to if the SDK gets in the way, since the tools don't change |
| gRPC | Rejected. Strong typing, but no fit with model tools, and the 50 Hz loop never crosses this line, so its speed buys nothing |
| ROS 2 | Rejected. Heavy to set up at an event, and solves a many-node problem we don't have |

**Long routines use plain handles.** `routine_start` returns immediately and `routine_wait` blocks. We don't depend on MCP's Tasks feature, which the [2026-07-28 spec](https://modelcontextprotocol.io/specification/2026-07-28/changelog) moved into an optional extension. That same revision favours server-minted handles passed as tool arguments, which is this design.

**The harness is the MCP client, not the model.** The harness decides which tools the model sees, validates what comes back, and handles waiting, so the model never spends turns polling.

**Network safety.** This server can move an arm, and at the demo it may be reached from another laptop. It binds to localhost unless told otherwise, and refuses to bind anywhere else without a shared token. Telemetry needs the same care, since it shows the room.

**Tool names use underscores,** because Claude's API doesn't allow dots in tool names.

## When System 1 wakes System 2

System 1 defers only for issues that matter, however often those turn out to happen. Each crossing costs seconds of model time, tokens and context, so a routine runs until one of these stops happens. Everything else stays local. Waking System 2 for anything not listed here is a bug.

| Stop | Trigger | What the arm does |
|---|---|---|
| `done` | Routine finished | Holds at home |
| `checkpoint` | The interval set by the policy | Pauses at the step boundary |
| `escalation` | One of the codes below | Pauses at the step boundary |
| `safety_abort` | Force cap, joint limit or hardware fault | **Stops first, reports second** |

| Situation | System 1 handles it locally | Escalates when |
|---|---|---|
| Missed a contact or slipped off a part | Re-looks and retries (`affordances.py` already has `RETRY` and `REGRIP`), up to the policy's budget | `retries_exhausted`: the budget ran out |
| Small position error | Corrects with the wrist camera's last look | `pose_unstable`: corrections keep growing. *Not wired up yet* |
| Low-confidence detection | Holds and reports what it found | `perception_low_confidence`: still below the policy's floor |
| A control the plan doesn't know | Records it in the inventory | `unknown_control`: only if the policy asks. *Not wired up yet* |
| A reading changed that shouldn't have | Marks the step `wrong_behavior` | `unexpected_response`: it might change what else is safe to do |
| A clean **FAIL** | Records the verdict and pauses at the step boundary | `step_failed`: **always.** System 1 can say that a control failed, but working out what it means and what to try next takes logic. System 2 decides how much thought each failure needs |
| A part it can't test, like a knob | Records it as refused | Never. It appears in the report |

**If System 2 is unreachable at a stop,** System 1 holds at the step boundary with the arm safe, and waits. It doesn't improvise.

### What crosses, and what doesn't

| Goes up to System 2 | Stays in System 1 |
|---|---|
| A `Checkpoint`: stop type, progress counts, verdicts since the last stop | Joint angles and motor commands |
| For an escalation: code, step, target, what it tried, the numbers it measured, options it considers valid | 50 Hz force and position samples |
| References to frames and traces, fetched only on request | Image frames, point clouds, masks |
| `SceneInventory`, in millimetres | Calibration, IK solutions, servo state |

An escalation carries **the mechanism with its numbers, never just a score**: "pressed twice, peak 4.8 N, 2.1 mm travel, `BTN2` unchanged", not "step failed".

A stop reporting one step fits in 2 KB, and [a test](../system-1/tests/test_engine.py) holds it there. Stops with more steps grow with them.

| Goes down to System 1 | Never goes down |
|---|---|
| A routine name, a `Plan` of `Step`s from the closed skill list | Joint angles, waypoints, motor values |
| Numeric checks on each step | Prose for the robot to interpret |
| An escalation policy, and answers to stops | Anything that changes a verdict rule |

## Tuning how much they talk

Autonomous retrying is a core part of what we're selling, so the amount of interfacing is **a setting, not a design decision**. Each `routine_start` carries a policy, so it can be tested on the same device without code changes.

**Start with frequent deferral, then scale back.** The first runs use Tethered. We loosen a setting only when the measurements below show the result holds up, and the presets to the right are where that may lead.

| Setting | Tethered (start here) | Balanced | Autonomous |
|---|---|---|---|
| `retries_per_step` | 0 | 2 | 4 |
| `checkpoint_every` (steps) | 1 | End of a stage | End of the routine |
| `confidence_floor` | High | Medium | Low |

A clean FAIL and a safety abort cross under every preset. The preset values are starting guesses, to be replaced with measured ones. Each run should record these from the trace:

| Metric | Tells us |
|---|---|
| Crossings per run, by stop type | The headline number to drive down |
| Retries resolved locally, against those escalated | Whether autonomy is working |
| Model tokens per control covered | What each crossing costs |
| Time the arm sat waiting on System 2 | What each crossing costs on the bench |
| Reward and false findings | Whether fewer crossings made the result worse. **Crossings only count as saved if this holds** |

## Rules that don't change

- **Sensors decide.** Verdict rules live in System 1, and reward is plain code in System 2 computed from verdicts. The model can propose anything, but can't change either. Reward is recomputable from `events.jsonl` alone.
- **A person approves a plan before it runs, and a patch before it prints.** Only mocks may auto-approve.
- **Steering takes effect between steps**, never inside a motion.

## Approving an amended plan

Not every change to a plan needs a person. Each amendment gets a priority level, and the level sets who has to sign off. **Plain code in System 2 assigns the level by comparing the new plan with the approved one, so the model can't grade its own change.** System 1 still clamps every parameter to its own limits, whatever the level.

| Level | Who signs off | Example changes |
|---|---|---|
| 0 Automatic | Nobody. Logged | A retry with the same target and skill, at the same or lower force |
| 1 Notify | Nobody, but it's shown in the Console, and a person can override at the next step boundary | Reordering steps, skipping a step, adding a re-test of a control already in the plan |
| 2 Approve | A person, before the change runs | A new target or skill, or a higher force than approved |
| 3 Always a person | A person, and no setting can lower this | Resuming after a safety abort, or printing a patch |

If code can't place a change, it counts as level 2. So does anything past the fifth amendment in a run, however small, so a run can't keep retrying forever without a person.

## Where to add your code

| You're adding | It goes in |
|---|---|
| A detector, classifier or depth method | `system-1/core` |
| A new skill, or a change to how one moves | `system-1/core`, then add it to the skill list in `system-1/interface` |
| Real arm, camera or sensor drivers | `system-1/hardware` |
| A verdict rule, or a new failure label | `system-1/core`; the label goes in `system-1/interface` |
| Force caps, or anything that stops the arm | `system-1`. Never in System 2 |
| A local retry behaviour | `system-1`, with its budget read from the policy |
| A new escalation code | `system-1/interface`, and a row in [the table above](#when-system-1-wakes-system-2) saying why it can't be handled locally |
| An LLM call or prompt | `system-2/harness` |
| A slash command | `system-2/harness` |
| Memory, recall or past-run lookups | `system-2/harness` |
| Plan validation, revision or fallbacks | `system-2/harness` |
| Reward, coverage or reports | `system-2/harness` |
| CAD patching | `system-2/cad` |
| A Console screen | `system-2/console` |
| A new tool | `system-1/interface` and `system-1/server`. **It needs a reason, since the point is to keep this list short** |

**If you need a number from the other system,** add it to the contract in `system-1/interface`. Don't reach across the line, even when it's one line of code and both run on the same laptop.

## Where the old folders went

| Was | Now | Note |
|---|---|---|
| `packages/sim` | `system-1/core`, `system-1/sim`, `system-1/hardware` | Flat modules. `core/` never imports the other two |
| `packages/arm` | `system-1/arm` | |
| `packages/contracts`: `Control`, `SceneInventory`, `Step`, `Check`, `Plan`, `StepTrace`, `StepVerdict`, the vocabularies | `system-1/interface` | Plus new types in `routines.py`: `Checkpoint`, `EscalationPolicy`, `RoutineHandle` and others |
| `packages/contracts`: `TestRequest`, `Finding`, `Report`, `Coverage`, `Reward`, `RootCause`, `CADPatch`, `ConceptMatch`, the run events | `system-2/contracts` | |
| `ports.ArmBackend` | `system-1/arm` | Internal. Never crosses the line. Superseded by `rig.Arm` in `system-1/core` |
| `ports.RobotBackend` | `System1`, with `McpSystem1` in `system-2/harness` | |
| `ports.CadBackend` | `system-2/cad` | |
| `packages/harness`: loop, reward, runlog, trace, CLI | `system-2/harness` | `run_test` calls tools instead of a backend object |
| `packages/harness/adapters/sim.py` | `system-1/server` | **Moves across the line.** Its unit conversion and `map_verdict` become System 1's job |
| `packages/harness/mock.py` | `system-2/harness` | Now `FakeSystem1`, so System 2 is testable alone |
| `packages/cad` | `system-2/cad` | |
| `apps/console/web` | `system-2/console/web` | |
| `apps/console/server/live_sim.py` | `system-2/console/server` | **The one exception to the boundary, not split yet.** It runs the sim in one process with the harness's log |
| `subjects/*/firmware` | `system-1/subjects` | |
| `subjects/*/cad`, `manual` | `system-2/subjects` | |
| `fixtures` | `system-2/fixtures` | |
| `tests` | `system-1/tests`, `system-2/tests` | Split by what each one exercises |
| `pitch` | `docs/pitch` | |
| `runs/` output | `system-2/runs` | System 1 keeps its own frames and serves them by reference |

## What's left

1. **Run Tethered on the sim and the arm** as the baseline, and record the [measurements](#tuning-how-much-they-talk) before loosening anything.
2. **Add the real arm** as a `Robot` in `system-1/server`.
3. **Split `live_sim.py`.** Its streams and sim hooks go to `system-1/server`, and its run logging to System 2. Until then, the Console's Live screen only works where the sim runs, so it can't show a robot on another laptop.
4. **Add the LLM:** `/explore` with memory, then a `Responder` that revises the plan on a failure. Today's rule responder records each failure and carries on.
5. **Record tool calls in the trace.** The harness logs crossings, but not each `routine_*` call as a `tool_call` event.
