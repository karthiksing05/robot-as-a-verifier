# Integration

How the sim, the harness, the real arm, the CAD step and the Console connect. Contract types are in [`system-2/contracts`](../system-2/contracts/src/rav_contracts).

## Joseph's sim and the server

The sim keeps its own flat modules. [`sim_backend.py`](../system-1/server/src/rav_server/sim_backend.py) calls the same functions `explore.py` does, without the film, and converts the results. The server's engine drives it, so the harness reaches the sim only through [the tools](system-boundary.md). Nothing in `system-1/sim` imports the server.

| Harness tool (mockup and Doc) | Sim function | State |
|---|---|---|
| `locate_device` | `rgbperceive.survey_wrist`, inside `perceive_rgb` | Works in sim, with the wrist camera only |
| `detect_candidates` | `segmodels` (OWLv2, SAM 2.1 tiny), inside `perceive_rgb` | Works in sim |
| `wrist_scan` | `rgbperceive` scan, bundle adjustment and plane sweep | Works in sim |
| `classify_part` | `rgbperceive.analyse`: rules, no model | Works in sim. Part of a single `perceive_rgb` call |
| `probe` | `touch.touch_plane`, `touch.touch_parts` | Works in sim |
| `register_cad` | Not in the new pipeline. `demo.py` is the older CAD-and-tag route | Missing |
| `build_actions`, test plan | `affordances.plan_tests` | Works, rule-based. Use as the fallback planner |
| Execute a step | `affordances.run_step`, `touch.make_refine` | Works in sim |
| Verifier | `affordances._judge`: the device's readout decides | Works in sim. Needs a real readout |

**The main gap.** The harness design has the model choosing each setup step. Today `perceive_rgb` runs scan through classification as one call, so System 2 can choose only between whole runs. Plan: ship the one coarse `perceive` tool first, since it works. Split it into separate tools only if the demo needs the model to visibly choose among them. `on_stage` is already a hook for reporting progress to the Console meanwhile.

**Steering** needs no sim changes: `run_step` is one step, and the engine holds between steps at each stop, where the harness applies commands.

**Displays have no test yet.** `plan_tests` doesn't test a display, so it counts as skipped and lowers the reward: preset C passes 10 of 10 steps, but scores 0.88 because 7 of its 8 controls are covered. The planner should add an `observe` step, which needs camera reading or the Pico.

**Tested so far (Nov 6, Apple Silicon):** the D405 route, through the harness, on preset C. The RGB route has not yet run through the adapter. On a Mac, NumPy prints `RuntimeWarning`s from `matmul` during this run, and the results are still correct.

### Units and vocabulary

The adapter converts metres to millimetres at the boundary, and `Part` to `Control`. Verdicts map like this ([D9](decisions.md)):

| Sim | Status | Label | Counts as |
|---|---|---|---|
| PASS | `passed` | | Covered and passed |
| FAIL | `failed` | `stuck`, `no_actuation` or `wrong_behavior` | A bug report |
| MISSED | `inconclusive` | `inconclusive` | Not covered: it's about the robot, not the device |
| REFUSED | `skipped` | `accessibility` if it needs a pinch | Not covered, reason shown |
| ABORTED | `inconclusive` | `unsafe` | The run stops |

## The real arm

Joseph's skills call a small interface, written up as `rig.Arm` in `system-1/core/rig.py`. [`RealArm`](../system-1/hardware/real_arm.py) implements it over LeRobot 0.7's motor bus, and replaces the [`LeRobotArm`](../system-1/arm/src/rav_arm/lerobot_arm.py) skeleton. It lives in `system-1/hardware`, and shares the IK, joint limits and force estimate with the sim through `rig.py`. It has been tested only against a simulated motor bus. How to run it on the arm, and what isn't built, is on [the real-arm page](../system-1/sim/docs/real-arm.md).

Still to do: read the SensX pad for axial force (`RealArm` takes a `pad` object, with no driver yet), and read the device state from the Pico (`RealArm` asks the operator for now). Run the [bench tests](../system-1/sim/docs/sim-vs-real.md#first-things-to-measure-on-the-real-arm) first, then feed the measured numbers back into `robot.py` and `real_arm.py`.

A real-arm `Robot` is the server's `PipelineRobot` over `hw_rig.make_rig`, and goes in [`system-1/server`](../system-1/server/README.md). Its camera is a drop-in equivalent of the sim's: [`real_wrist.WristCamera`](../system-1/hardware/real_wrist.py), which is Windows only. [`real_cameras.RunVideo`](../system-1/hardware/real_cameras.py) saves the run's video:

```python
wrist = real_wrist.WristCamera(arm)                                    # arm/camera/camera_test.py calib
video = real_cameras.RunVideo(run_dir)
scene = rgbperceive.perceive_rgb(arm, None, wrist, on_frame=video.on_frame)  # None: survey with the wrist
refine = touch.make_refine(wrist, plane_T)
trace.frames.append(video.still(wrist.capture(), step.id))             # StepTrace.frames: paths in the run folder
```

The wrist driver has run on saved photos, not yet on the live camera, and the wrist survey hasn't run on the real arm. The team dropped the iPhone, so `real_cameras.PhoneCamera` is unused outside `hardware/tools/cam_check.py` and its test.

## The planner

`rule_planner` in [`loop.py`](../system-2/harness/src/rav_harness/loop.py) is one function with the signature `(request, scene, fallback) -> Plan`. The manual-driven planner replaces it without changing anything else. It must:

- Parse the manual into controls, actions and expected feedback, keeping each source quote.
- Match those controls to `scene.controls`. Add a test for any control the manual misses, and list in `unmatched_manual_controls` anything the robot can't find.
- Output skills from the closed list only. Implemented today: `press`, `flip`, `slide`, `turn`, `push_latch`.
- Fall back to the cached plan, then to the `fallback` plan from `/explore`, if the network fails.

## The CAD step

Implement `CadBackend` ([`ParamsBackend`](../system-2/cad/src/rav_cad/__init__.py) is a working example). The harness passes a `CADPatch` and expects `check` to report problems and `apply` to produce a new revision. Bayan's CAD edits and any MCP server plug in here.

The analyst ([`analyst.py`](../system-2/harness/src/rav_harness/analyst.py)) gets an `AnalystContext`: the finding, `read_params()`, every step's measurements, `cad.check` and the backend's `rules()` text. The patch names a parameter the backend lists (`features.button_2.clearance` for CadQuery); code fills in its current value, so a patch can't be stale. Those names are the contract between the analyst and the backend; the old `params.rev_a.json` names still resolve, for `ParamsBackend` and old patches.

`model_analyst` compares the failing control with similar ones when the run tested any, and judges a lone control from its own parameters and the rules, with lower confidence. It tests changes with `check_patch` before submitting, may answer "no CAD fix" (perception, arm, firmware), records every turn for the Console, and falls back to `rule_analyst` when the API can't be reached. `cli_analyst` is the same diagnosis through the `claude` CLI on a Claude Code login, for machines without an API key: it gets JSON back through `--json-schema` and our code runs `cad.check` between attempts. The demo machine needs `claude` installed and logged in for it.

With Onshape ([D29](decisions.md)), `OnshapeBackend` is the `CadBackend` and `make_onshape_analyst` is the analyst: the model edits the real model on a branch of its own through the `rav-cad` MCP tools, and the patch carries `source` (the branch and its checked microversion) and `edits` (what it did). `check` re-exports the branch and runs the generic checks; `apply` makes the new Onshape version. The tool calls the model made inside its CAD session appear in the run log as `tool_call` events named `cad.*`.

## The model trace

The frontier model will operate the robot through tool calls, so a run has to show whether a failure came from the model or from our code. Two event types record this, in `events.jsonl` with everything else: `model_turn` and `tool_call` ([contract](../system-2/contracts/src/rav_contracts/events.py)). [`Tracer`](../system-2/harness/src/rav_harness/trace.py) writes them:

```python
tracer = Tracer(log)
tracer.stage, tracer.step = "TEST", "s2"
turn = tracer.turn("the model's id", input="what's new this turn", thinking=..., text=..., stop_reason=...,
                   tokens_in=..., tokens_out=..., latency_ms=..., claims={"s2": "passed"}, raw={"request": ..., "response": ...})
tracer.call("robot.run_step", args, lambda: run_it(args), turn=turn)
```

`raw` saves the whole request and response to `runs/<id>/model/turn-N.json`, so a bad decision can be replayed against its exact context. The Console diagnoses from these events ([`trace.ts`](../system-2/console/web/src/lib/trace.ts)):

| Layer | What gets it filed there |
|---|---|
| Model | A call rejected for what it asked (`raise ToolRejected("bad_args" or "unknown_target", ...)`), the same rejected call sent again, a reply cut off or malformed, or a `claims` entry that disagrees with the sensors' verdict |
| Pipeline | A tool timing out (`TimeoutError`) or raising anything else, or the model's API failing (`api_error`) |
| Robot | A verdict of `inconclusive`: the arm couldn't carry out the test, which says nothing about the device |
| Device | A verdict of `failed`. This is the finding we want, shown here so it isn't mistaken for the others |

A tool has to raise `ToolRejected` for the model to be blamed. Anything else counts as ours, so an unclassified error points at the pipeline first.

The live sim logs its real calls this way with `caller: "rules"`, since no model runs yet. `system-2/fixtures/sample_run/sample-trace` is a scripted model that fails in every way above, for building against. It isn't real model output.

## The Console

The Console reads `RunEvent`s and sends `SteerCommand`s and approvals. Full interface: [`system-2/console`](../system-2/console/README.md). Build against `system-2/fixtures/sample_run`, which needs no robot.
