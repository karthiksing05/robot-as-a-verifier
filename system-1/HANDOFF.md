# Handoff: what System 2 needs from System 1

**For:** Joseph, and anyone else changing `system-1/`. **From:** Karthik. **Written:** Nov 7, 2026.

## Changed since: the core, sim and hardware split (Joseph, Nov 7)

System 1's code is now three folders of flat modules. `core/` is the pipeline: perception, touch, skills and verdict rules. `sim/` is the MuJoCo rig, the film and the benchmark, and `hardware/` has the real arm's and wrist camera's drivers. A rig (`rig.Rig` in `core/rig.py`) is an arm and its cameras, and it is the only thing that changes between the sim and the real arm. `sim_rig.make_rig` builds the sim's and `hw_rig.make_rig` the real one. `rig.Arm` is now the arm interface, and `rav_arm.ports.ArmBackend` is superseded. In the server, `SimBackend` is `PipelineRobot` on the sim's rig. Its signature and the tools haven't changed.

The server now shares two of explore.py's rules. Each touch falls back on its own, so a failed part touch keeps a good touched plane. A last look that raises leaves the part as scanned and the step goes on, where before the routine stopped with a `safety_abort`.

A `--robot real` backend would be `PipelineRobot` over `hw_rig.make_rig`, with its own flag for the serial port, such as `--arm-port` (`--port` is the HTTP port). Before it's useful it needs:

- A streaming device readout instead of `OperatorReadout`. That one asks the operator once a step ends, but `affordances` reads `arm.app.readings` during a slide or turn.
- A hand-eye calibration, the camera's mount offset on the gripper. Every part the scan finds is shifted by it, so presses land off centre. The plane sweep doesn't need it: an offset shared by every photo cancels out, and the bundle adjustment corrects each photo's own error from the joints.
- The bench numbers on [the real-arm page](sim/docs/real-arm.md): servo stiffness and bus timing.

A later `explore` can take an area of the panel from System 2 and scan only that. It would be built from `perceive.plan_views` and `rgbperceive.scan`, as `perceive_rgb` already does for the extra views of parts too few photos saw, and would go in `core/pipeline.py` with a `PipelineRobot` method.

## The goal

We're about to get access to a frontier model. We want the whole test process in the sim to run through it: the model looks at what System 1 found on a device, reasons about what to test, starts routines, reads the results, and changes the plan when something goes wrong. It should do this on devices it hasn't seen, not just preset C.

System 1 stays as it is in principle. It never calls a model, it has no joint or motor tool, and its rules decide every verdict. The model works only through routines and the closed skill list, as [the boundary doc](../docs/system-boundary.md) sets out.

The gap is that today's tools were built for a rule-based caller. The rule planner reads the sim's parts directly and always sends valid steps, so nothing had to explain the device or the allowed actions to an outside caller. A model only knows what the tools tell it.

## What a run will look like

1. The harness starts `explore` and waits for it to finish.
2. The model reads `system_status` and `scene_get`, then reasons about the device and writes a plan.
3. The harness checks and approves the plan, then starts `run_plan`.
4. At each stop, the model reads the numbers, fetches evidence if it needs more, and continues, amends, skips or aborts.
5. The harness computes the reward from System 1's verdicts and writes the report.

## What already works

These don't need changes:

- The seven tools over HTTP, and holding at a stop for as long as System 2 takes
- The stops, local retries, policies and force clamp
- `--seed` for generated devices, and both the RGB and depth routes
- Verdicts that come only from System 1's rules

On Nov 7, after #10, both routes scored 7 of 8 controls through the server on preset C, one run each.

## Needed before the first model run (P0)

| # | What we need | Why | Where it stands today |
|---|---|---|---|
| 1 | **Publish the allowed actions:** which skill each control kind takes, each skill's required params, their ranges and the default force | The model can't guess these, and the wrong skill gets refused | `_check` enforces them, but no tool reports them. `Skill` also lists `press_hold`, `hook_pull`, `observe` and `none`, while the engine offers only five skills |
| 2 | **Give each control the details needed to plan a step:** dial range in degrees, slider position and travel, and a printed label if the pipeline can read one | A valid `slide` or `turn` depends on these. Today the model could only copy numbers from the fallback plan, not reason about them | `part_to_control` drops `range`, `state` and `meta`, and `label` is always empty |
| 3 | **Reject bad requests before anything moves.** `routine_start` should return a tool error listing every bad step. An amended plan at `routine_resume` should get the same, and the routine should keep holding | A model's typo shouldn't count as a test result | An unknown target, wrong skill or bad param comes back as a refused step, which maps to `skipped`. That looks the same as a real refusal such as a pinch-only part |
| 4 | **Make the force limits agree** | A model asking for 20 N should get a clear answer | The engine clamps to 15 N, then `_check` refuses anything above 14 N, so the clamp can turn a request into a refusal |
| 5 | **Make `home` and a repeat `explore` work on the sim** | The model needs to be able to take another look at a device | `SimBackend` has no `home`, so the routine reports success without moving. `at_home` is never cleared, and `known` carries over |
| 6 | **Choose the device and fault at startup:** add `--fault` and `--placement` to `rav-server` | We can't test the model's reasoning about failures without failures | `explore.py` has `--placement`, but the server doesn't. `faults.plant` exists, but nothing in the server calls it |
| 7 | **Report a pipeline failure as something other than a safety abort** | A survey that can't find a plain panel isn't dangerous, and the model could respond to it. A `safety_abort` needs a person to resume | The engine's catch-all turns every exception into `safety_abort` |
| 8 | **Pass through the measurements the sim already has:** `contact_offset_mm`, `refined`, `refine_shift_mm`, `regrip_mm`, `landing_n`, `collisions` and `lcd` | These are what separate "the part is broken" from "the robot missed". Keep them small, or put the larger ones in the trace only | `run_step` returns them, and `map_verdict` drops them. A stop reporting one step must stay under 2 KB, as `test_engine.py` checks |

## Needed soon after (P1)

| # | What we need | Why | Where it stands today |
|---|---|---|---|
| 9 | **Images by reference:** a survey view of the device, plus before and after frames for a step, fetched through `evidence_get` | This is the biggest step up for reasoning about new objects. Sending them only on request keeps them out of every model turn | `StepTrace.frames` is always empty, and `evidence_get` returns only a trace, though the boundary doc says it can return a frame |
| 10 | **Evaluate `Step.check`,** or reject steps that include one | Memory is meant to reach System 1 through these checks. Today they're silently ignored | Nothing in the server or `affordances.py` reads `check` |
| 11 | **Give displays a test:** an `observe` step that reads the display | A display is never tested, so preset C can't score above 0.88 on today's rule plan | `plan_tests` doesn't test displays, and `observe` isn't implemented |
| 12 | **More planted faults,** covering other kinds of control | With one fault, the model could look good by luck | `FAULTS` holds only `stuck_button`, on `button_2` |
| 13 | **A separate answer key:** the device's true parts and planted faults, written to a file for scoring | We need to measure what the model missed. It must never reach the model or cross through a tool | Doesn't exist |
| 14 | **Keep a trace per attempt** | Evidence for an earlier attempt shouldn't disappear | The ref is `trace:<routine>:<step>`, so a retry or a reused step ID overwrites the earlier trace |
| 15 | **Check that long holds are safe:** hold at a stop for 10 minutes with the server connected, then resume | Model turns can be slow, and the sim's hold hasn't been tested at that length | Holding is built, but untested at that length |

## Later (P2)

- A focused look at one control, as a parameter on `explore`, so the model doesn't have to rescan everything
- The two unwired escalations, `pose_unstable` and `unknown_control`
- The planned `press_hold` and `hook_pull` skills

## What we're not asking for

- **No joint, motor or jog tool**, and no waypoints or raw force commands
- **No model calls in System 1**, including vision models beyond OWLv2 and SAM
- **No model influence on verdict rules**
- **No new tools if we can avoid them.** Items 1 to 9 can fit in the existing seven: new fields on `SystemStatus` and `Control`, validation inside `routine_start` and `routine_resume`, and frames through `evidence_get`
- **No real-arm work for this.** It's sim only for now, and the same contract should carry over later

## Decisions that are yours

Where you've made a call, it wins. These are my suggestions:

| Question | My suggestion |
|---|---|
| Restart the server for each new device, or add a reset? | Restart for now. It needs no new contract, and the test script can handle it |
| Where should validation live, given that `_check` can plan a sideways push and the sim's renderers belong to one thread? | Run the checks on the worker thread if that's safest, as long as a bad plan fails before the arm moves |
| Can a failed `Step.check` fail a step? | Report the result beside the verdict first, without changing it, because the boundary doc says verdict rules don't go down from System 2 |
| Which devices do we use for testing? | Preset C, plus the six generated devices from #10's end-to-end run |

## How we'll know it's ready

No model is needed to check this. A short script should be able to do all of the following using only tool results, without importing anything from `sim/`:

1. Start `rav-server --robot sim --seed <n> --fault <fault>`.
2. Run `explore`, then build a plan from `system_status` and `scene_get`, without using `fallback_plan`.
3. Send a plan with a wrong skill and an unknown target. It should be rejected with both problems named, and the arm shouldn't move.
4. Run a valid plan, and see the planted fault as a failure with enough numbers to explain it.
5. Answer that stop with an amended plan, and see the amendment run.
6. Run `home`, then `explore` again, and get a sensible inventory.

## Working together

- Contract changes go in `interface/`, with every use fixed in the same commit, as `CONTRIBUTING.md` describes. Tell Karthik when one lands, because the harness has to match.
- Items can land one at a time. The harness will start on P0 as it stands, using the fallback plan's numbers until items 1 and 2 arrive.
- If an item is wrong or too expensive, say so here or on the PR. This list is what we think we need, and you know the pipeline better.
