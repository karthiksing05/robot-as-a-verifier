# Architecture

```
                     ┌───────────────────────────────┐
   person  ───────►  │  system-2/console             │  chat, steering, approvals,
                     │  renders run events           │  bug-report traversal
                     └───▲───────────────────┬───────┘
          RunEvent (log) │                   │ SteerCommand, approvals
                     ┌───┴───────────────────▼───────┐
   manual, spec ───► │  system-2/harness             │  LLM calls live here, between steps
   CAD (optional)    │  planner · steering · reward  │
                     │  report · analyst · memory    │
                     └───┬───────────────────┬───────┘
                         │                   │ CadBackend
   ══════════════════════╪═══ the boundary   ▼
          seven MCP tools│               system-2/cad
                         │               params · CadQuery · Onshape
                         ▼                   │
                 system-1/server             ▼
              routines · stops · retries  new revision, same tests
                         │ Robot
                 ┌───────┴───────┐
                 ▼               ▼
            MockRobot      SimBackend, then a real-arm Robot
                                 │
                                 ▼
                           system-1/core: perception, skills, verdicts
                                 │ rig.Arm
                         ┌───────┴───────┐
                         ▼               ▼
                      SimArm      real_arm.RealArm
```

What crosses the boundary is a type from [`system-1/interface`](../system-1/interface/README.md). These interfaces let each side be swapped:

| Interface | Between | Implementations |
|---|---|---|
| `System1` | Harness and whatever answers the tools | `McpSystem1`, `FakeSystem1` |
| `Robot` | System 1's engine and what executes tests | `SimBackend` (a `PipelineRobot` on the sim's rig), `MockRobot`; a `PipelineRobot` on the real arm's rig next |
| `rig.Arm` | The pipeline and an arm | `robot.SimArm`, `real_arm.RealArm` |
| `CadBackend` | Harness and CAD | `ParamsBackend`, `CadQueryBackend`; Onshape to be added |

## One run

1. **Input.** A `TestRequest`: product, manual, optional CAD and spec.
2. **Perceive.** Find the test surface: a `SceneInventory`, the denominator of coverage. Joseph's eight stages cover survey, scan, segment, map and touch.
3. **Plan.** The manual becomes a starting list of controls, which exploration confirms, corrects or extends. Output: a `Plan` of skill calls. A rule-based plan is the fallback.
4. **Approve.** Code validates the plan. A person approves before it runs.
5. **Test.** System 1 runs the plan: for each `Step`, the skill runs with guarded contact and produces a `StepTrace` and a `StepVerdict`. It retries locally, and stops for System 2 on a failure or at a checkpoint. Steering applies at those stops.
6. **Report.** Coverage and reward are computed from verdicts alone. Each failure becomes a `Finding` with links to its events.
7. **Fix (optional).** A `RootCause` and `CADPatch` per finding. A person approves, it prints, and the same tests run. The patch stays only if the reward rises.

Every stage appends to `system-2/runs/<id>/events.jsonl`. The log is the record: the Console, the reward and the audit all read it.

## System 1 and System 2

[System 1 and System 2](system-boundary.md) has the full split, the interface and where code goes. In short:

| | System 1 | System 2 |
|---|---|---|
| What | The robot: perception, IK, skills, guarded contact, verdict rules, local retries | The harness: the frontier model (Claude), planner, memory, reward, reports, CAD, Console |
| When | About 50 Hz, in the control loop. Runs only when System 2 starts a routine | Between steps, never inside a motion |
| Outputs | Motion and measurements | Typed proposals: routines, plans, root causes, patches |
| Never | Decides what to test next | Commands a joint or motor, decides a verdict, or changes how it's judged |

Hard rules run first. Then the Cobweb concept memory flags what rules miss. The model judges only what neither can read, like screen text.

## Principles from the harness work

From [Self-Evolving Robots](https://claude.ai/artifact/VxmRPoiAXK3pCHxKmjgRv6). That work runs in simulation on different tasks, and its numbers don't carry over. These do:

- **The ruler is not the robot.** Whatever proposes a design can't affect how it's judged.
- **Failures come back as mechanisms with numbers**, never as a score alone.
- **A ratchet.** A change stays only if it gains something and loses nothing.
- **A full record.** Every prompt, answer, trial and refusal is on disk.
- **Test the test.** A test must fail on a known-bad case and pass on a known-good one. Otherwise a failure may be the test's fault.
- **Cheapest fix first:** re-tune, then recompose skills, then a tool, then a CAD patch.

## Words we use

| Word | Means here |
|---|---|
| Harness | `system-2/harness`: what runs a test. The Self-Evolving Robots doc uses the same word for its own design loop |
| Control / part | A button, dial and so on. `Control` in contracts, `features.Part` in `system-1/core` |
| Finding / bug report | The same thing: one reported fault |
| Verdict | One step's result. The sim's PASS, FAIL and so on map to contract statuses in [D9](decisions.md) |
| Reward | Control coverage × pass rate on covered controls |
| Rev A, Rev B | Printed revisions of a test subject |
| Coverage Console, Console | `system-2/console` |
