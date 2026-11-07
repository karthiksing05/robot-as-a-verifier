# Plan

Task-level status lives on the [Kanban](https://claude.ai/artifact/9Dm3x26boTyvHhrqAyEpaV). This page is the order things come together in, and what each step proves.

## Integration order

Each milestone runs on `main` with a single command. Work on a milestone in your own folder, against the contracts and the mocks, then join it up.

| # | Milestone | Proves | Owner | Depends on | State |
|---|---|---|---|---|---|
| 0 | `uv run rav mock`: the demo story on mock data | Contracts, event log, reward, fix loop | Karthik | | Done |
| 1 | `uv run rav run` against `rav-server --robot sim`: Joseph's pipeline through the tools | The sim fits the contracts, and the systems can be separate | Joseph, Karthik | 0 | D405 route tested through the server Nov 7: 10 of 10 steps on preset C. The RGB route (the team's setup) still needs its first run through the harness, on a machine with the model downloads |
| 2 | Console replays a run from `system-2/fixtures/` | The UI works with no robot | Karthik, Bayan | 0 | Done on `karthik-frontend`: one page per run, with video for recorded runs |
| 3 | Console drives a live mock run: approve, steer, chat | Steering and approvals work end to end | Karthik, Bayan | 2 | Working against the MuJoCo sim through `system-2/console/server/live_sim.py`: approve, pause, stop, skip, test next. Chat isn't wired in |
| 4 | Manual goes in, the plan comes out | Manual scaffolds the test, and each step quotes its line | Karthik, Max (manual) | 0 | Not started |
| 5 | Root cause and patch from real logs, through `CadBackend` | The analyst and Bayan's CAD edits plug in | Karthik, Bayan | 0 | `model_analyst` in `system-2/harness/src/rav_harness/analyst.py`: tested with a scripted client and on mock runs. Not yet run on real logs |
| 6 | **Hello world:** real arm connects, homes, makes one guarded press with a force reading | The hardware is alive | Max, Joseph | Arm built | Not started |
| 7 | `LeRobotArm` passes the sim's skills on the real arm | The sim's code runs on the real arm | Joseph | 6 | Not started |
| 8 | Real survey and scan on the printed appliance | Perception holds up on real plastic | Joseph, Bayan | 7, [open risk R1](docs/decisions.md#open-risks) | Not started |
| 9 | Rev A live: both faults found, on the Console | **The demo's core claim** | Everyone | 3, 7, 8, appliance | Not started. The sim version works: a planted fault fails live on the Console |
| 10 | Rev B printed from the live patch and retested, reward rises | The full loop | Everyone | 5, 9 | Not started |

Below milestone 9, the fallback is real. The sim and mock runs drive the same Console, so a broken arm costs the live part of the demo and not the whole of it.

## Event timeline

Hours are from the start of hacking. Check them against the real schedule when it's posted.

| Hours | Focus | Cut line |
|---|---|---|
| 0 to 3 | Build and calibrate the arm, start the appliance shell print, run the bench tests in [sim vs real](system-1/sim/docs/sim-vs-real.md) | |
| 3 to 7 | Milestones 6 and 7. Design the appliance. Console replay | |
| 7 to 12 | Milestones 3, 4, 8 | **Hour 12:** whatever isn't working goes to its fallback |
| 12 to 16 | Milestones 5, 9. First full real run | |
| 16 to 20 | Milestone 10. Rev B print takes about 40 minutes | |
| 20 to 24 | Freeze, record the backup film, rehearse | **No new code in the last 3 hours** |

## Fallbacks

| If this fails | Do this |
|---|---|
| Real perception | Touch off 2 locating features and use CAD poses, or taught poses |
| Force pad | Load cell (`--sensing loadcell`), then servo estimate with wider pass bands |
| Frontier model or Wi-Fi | Cached plans and templated report text |
| Rev B print | Logged Rev B results from rehearsal |
| The arm | Sim run on the Console, plus [the films](docs/pitch/films) |

## Before the event starts

Bring these to the team: the [open questions](docs/decisions.md#needs-a-team-decision). The first one affects the real survey.
