# Frontier model integration plan

**For:** Karthik and Joseph. **Written:** Nov 7, 2026. **Branch:** `karthik-frontier-integration`. **State:** plan only, nothing built.

## The goal

A frontier model runs a full verification of a device it has never seen, in the sim. It works only through System 2's harness and System 1's tools. It decides what to look at, what to test and when. It recovers when the arm misbehaves, and it reports what's wrong with the device without mistaking robot errors for device faults. People can read its reasoning and steer it while it runs.

The two final appliances are the first real test of this. They are not what it gets built around.

## Where we are

Baseline on Nov 7: System 2 has 77 passed and 8 skipped, and System 1 has 48 passed with its 7 sim tests not run.

**Already sound, and staying:**
- The seven tools, routines, stops and policies
- Verdicts decided only by System 1's rules
- Approval levels
- The event log and `Tracer`
- `rig.Rig`, which makes sim and real interchangeable

**What blocks a model today:**

| Area | Gap | Where |
|---|---|---|
| Tools | Every P0 item in `HANDOFF.md` is still open. The model isn't told the allowed actions, slider and dial limits are dropped, bad steps look like real refusals, and `home` does nothing on the sim | `sim_backend.py`, `engine.py`, `routines.py` |
| Faults | The server has no `--fault`. The only planted fault is `stuck_button` on `button_2`, so a model could look good by luck | `main.py`, `faults.py` |
| Recovery | A `safety_abort` ends the run and a failed `explore` raises an exception, so the model has no way back | `loop.py:_test`, `commands.py:explore` |
| Judging retests | A control takes its worst result, and every failure becomes a finding. **A robot error followed by a clean retest still reports a broken device.** With a 5% error rate this would produce false findings regularly | `reward.py:coverage`, `loop.py:_record` |
| Evidence | A retry overwrites the earlier trace. There are no images, and `Step.check` is ignored, so the model can't verify a manual's claim such as "the LCD shows X" | `engine.py`, `sim_backend.py` |
| Leak | Live runs put the planted fault in `TestRequest.spec`. A model given the request would be handed the answer | `live_sim.py:304` |
| Processes | `live_sim.py` runs the sim and the harness in one process, with the rule planner | `console/server/live_sim.py` |
| New devices | The sim builds devices only from its own generator. Part ids double as joint names and readout channels | `sim/device.py`, `sim/world.py` |
| Perception | Fixed size bands per kind and a closed OWLv2 query list. Anything that doesn't fit is dropped, so the model never learns it exists | `perceive.py`, `rgbperceive.py`, `segmodels.py` |
| Skills | The appliance's tag file has the door as `pull`, and no such skill exists (`hook_pull` is planned). Displays have no test | `onshape.yaml`, `affordances.py` |
| Console | Chat is a regex with no model behind it. Reasoning only shows on a saved run, inside each step | `ChatDock.tsx`, `ModelTrace.tsx` |

## Principle: general, not taught to the test

These rules are enforced in code wherever possible.

1. **No device knowledge in the harness or prompts.** No control names, device names, layouts or fault types. A test scans the prompts and harness source for vocabulary from `subjects/` and `faults.py`, and fails on a match.
2. **Devices differ only by data.** A new device is a data file, never a code branch. That file describes the sim's truth and sits on System 1's side, where the model can't reach it.
3. **The model learns a device only from what a real run would give it:** the scan, images, device readings and the manual.
4. **The answer key never crosses a tool.** Planted faults and injected errors go in a file only the scorer reads. A test searches every saved model request for its contents.
5. **The model isn't told the error rate.** It gets the general truth that the robot can fail and that an inconclusive result says nothing about the device.
6. **Separate devices for tuning and for judging:**

   | Set | Devices | Use |
   |---|---|---|
   | Dev | Preset C and a few seeds | Free to look at and tune against |
   | Validation | Other seeds, with faults sampled by seed | Checks each prompt or harness change |
   | Held out | More seeds, plus the two final appliances | Run only at a milestone gate. Their prompts and results aren't used for tuning |

7. **A fix prompted by a held-out failure must name the general class of problem** and add a generated case for that class. Validation then re-runs, and the held-out results are treated as spent, so the gate needs fresh seeds.
8. **Same device, different names:** the same device is re-run with opaque control ids, shuffled order, and a mirrored layout. The findings must not change.

**One tension to be honest about.** System 1's perception has to work on the final CADs, and its size bands were fitted to the sim's generator. If a final part falls outside them, we don't move a threshold to fit it. We widen what the generator produces, fix perception on that wider set, and report anything unclassified to the model as `other` instead of dropping it.

## How it fits together

```
 Console (browser)
   │  run events + live reasoning (SSE); steer and approve (POST)
   ▼
 rav-agent  ── System 2 service ──────────► model API (Gemini first)
   │  harness: agent loop, tool belt, guards,
   │  approvals, reward, reports, run log
   │  MCP tools (control)
   ▼
 rav-server ── System 1 service
   │  routines, verdict rules, telemetry streams ──► Console (poses, cameras: never the model)
   ▼
 PipelineRobot on a Rig: sim today, real arm later
   └ sim only: error injector, fault planter, answer key file ──► scorer (offline)
```

One command starts both services for local work, and each can also run alone on its own machine. This completes "split `live_sim.py`" from the boundary doc.

### The agent loop

**The model decides the order, and code enforces the limits.** There's no fixed script of stages. The harness offers tools, checks each call, and returns clear errors the model can act on. The existing `run_test` stays as the rule-based fallback, and as the baseline the model has to beat.

| Model-facing tool | Backed by | Guard |
|---|---|---|
| `look_at_device` | `explore` routine, returns at its next stop | Refused while a routine is active |
| `get_scene`, `get_status` | `scene_get`, `system_status` | None |
| `get_evidence` | `evidence_get`, including images | Unknown refs come back as errors |
| `read_manual` | Harness: search and fetch by section | Only the current project's files |
| `propose_plan` | Full validation, then the approval level | Lists every bad step. Nothing moves |
| `run_plan` | `routine_start` plus waiting for the next stop | Needs an approved plan |
| `answer_stop` | `routine_resume`, through `classify` | Level 2 and above wait for sign-off |
| `recover` | `home`, then a re-look or restart | Safety aborts stay level 3: a person, or a recorded sim-only auto-approval |
| `ask_operator` | Console | Waits for an answer, with the arm holding |
| `finish_run` | Writes the model's claims, then the report | Refused while controls are unaccounted for, unless it gives a reason for each |

The model never polls, and never gets a joint, waypoint or force command. `routine_wait` stays with the harness. Reward and verdicts stay in plain code.

Other parts of the loop:

- **Model client:** a small provider-neutral interface, with Gemini first. It must store each response's raw parts unchanged, because Gemini returned HTTP 400 when a tool-call turn came back without its thought signature.
- **Limits:** turns, tokens, cost and time per run; detecting the same rejected call repeated; backoff on 429 and 503, then a fallback model. When the budget or API runs out, it holds the arm safely, or falls back to the rule plan with that labelled on the run.
- **Context:** a short system prompt covering role, boundaries and evidence rules. Stops stay small, evidence is fetched by reference, and older turns get summarised.
- **Steering:** an operator message enters as a user turn at the next model turn. Commands apply at step boundaries, never inside a motion.

### Judging retests

Retests need a rule in plain code, not the model's opinion. Proposal, for Joseph and Karthik to confirm:

- Every attempt stays on record.
- A control counts as **failed** when failures repeat with no pass between them.
- A failure followed by passes is reported as **intermittent**, with all attempts shown. It's neither hidden nor called a clean pass.
- An inconclusive result never counts as a failure.
- The model can ask for more attempts, but can't change the result.

`reward.py` still computes from verdicts, and can still be recomputed from the log.

## The 5% error model

An `UnreliableRobot` wraps the `Robot` in `system-1/server`. It's sim only, and the server refuses it on a real arm. It takes `--error-rate 0.05 --error-seed N`, plus a schedule option so tests can force a specific error at a specific step.

Each action (each step attempt and each explore stage) has a 5% chance of an error. Over 10 actions that means at least one error in 40% of runs, and over 20 actions, 64%.

**It changes the world, not the verdict.** Verdict rules run untouched, so the sensors still decide:

| Error | How it's caused | What the model sees |
|---|---|---|
| Missed aim | The part's pose is off by several mm for one attempt | Usually `inconclusive`, sometimes a plausible failure |
| False alarm | The force reading spikes, so a real `SafetyStop` fires | `safety_abort` on a healthy arm and device |
| Stale reading | The device readout freezes for one step | A false `no_actuation` on a working control |
| Pipeline fault | A driver or perception call raises | A new `pipeline_error` stop (HANDOFF item 7) |
| Weak perception | Lower confidence, a shifted pose or a missing part in `explore` | `perception_low_confidence`, or a wrong inventory |
| Slow arm | A routine takes much longer than usual | `routine_wait` timeouts, which the harness absorbs |

Every error goes in the answer key. A separate generic fault catalogue (stuck, weak, wrong channel, inverted, no feedback, display mismatch) is sampled by seed across any control, which replaces the single `button_2` case.

## What we need from System 1

This is `HANDOFF.md` P0, items 1 to 8, unchanged. Four P1 items move up, because this goal can't work without them:

- **Item 9, images:** matching "the power button" in a manual to `button_1` needs a picture.
- **Item 10, `Step.check`:** checking a manual's claims needs it. As HANDOFF suggests, System 1 reports the result beside the verdict without changing it.
- **Item 13, answer key:** nothing can be scored without it.
- **Item 14, a trace per attempt:** retests destroy evidence without it.

Also needed: telemetry streams behind `rav-server`, and sim-only flags for the error model and faults.

Joseph's calls stand. `HANDOFF.md`'s suggestions stay suggestions until Joseph answers them. Contract changes go in `interface/` with every use fixed in the same commit, and PR #1 lands first because it touches `pipeline.py` and `models.py`.

## Final appliances: CAD and manual

**Device loader (System 1, sim).** It takes a CAD export plus one data file, and builds the sim device:
- Meshes, moving parts and their joints
- Which reading each part drives, and what the display does
- Spring and detent values

`onshape.yaml` already holds part of this. No per-device code. It also needs a check that the device is within reach, and a way to plant faults in it from the catalogue.

**Manual loader (System 2).** It takes PDF or text, and the model reads it through `read_manual`. Plans quote the line each step comes from. Controls that don't match go in `unmatched_manual_controls`. A manual that disagrees with what the device does becomes a finding.

**What the model sees.** Default: the manual and the scan when planning, and CAD only when diagnosing a finding. That's the honest black-box test, and it keeps the existing fix loop.

**What arrival of the CADs will tell us:** which skills are missing (`hook_pull` is likely), whether the parts fall inside perception's bands, and how much of the panel-on-one-plane assumption holds.

## The Console

Live becomes the place to watch the model work. **The same components show a live run and a replay**, so a recorded run reads the same way.

| Area | Shows |
|---|---|
| Timeline (main) | Reasoning as it streams, tool calls with arguments and results, stops, approvals and steering, in order. A state line: thinking, waiting on the arm, waiting on you, or finished |
| Sim view | `Sim3D` and the cameras, as today |
| Plan and coverage | Each control's status, the plan as the model changes it, and why each change was made |
| Evidence | The force trace, frames and readings behind any step, opened from the timeline |
| Composer | Message the model, pause, stop or skip, and approve inline. Replaces the regex in `ChatDock` |
| Run totals | Turns, tokens, cost, crossings and time the arm spent waiting, plus the layer split: model, pipeline, robot or device |

New events: `model_delta` (streamed, not stored; the finished turn is stored as `model_turn`) and `agent_state`.

**Label reasoning accurately.** Gemini returned reasoning text in the probe, but Google documents this as thought summaries, not the raw chain of thought. The screen will say "reasoning summary".

The Console is built against recorded runs, so it doesn't wait on the model work or use up API quota.

## Integration tests

| Tier | Runs | Proves | Key needed? | Runs when |
|---|---|---|---|---|
| 0 Contract | Validation, retest rule, guards, approval levels, vocabulary and answer-key scans | The limits hold | No | Every commit |
| 1 Agent | Agent loop, fake System 1, scripted model | Each error kind: bad arguments, unknown tool, a repeated call, truncation, 429/503, thought signatures kept, budgets, steering | No | Every commit |
| 2 Boundary | Two real processes, `--robot mock`, recorded model | Everything works across the network. Kill either process and it fails safely | No | Every commit |
| 3 System 1 readiness | `HANDOFF.md`'s script against the sim, with no model and no `sim/` imports | System 1 is enough for an outside caller | No | Before merging System 1 changes |
| 4 Forced errors | Each error kind forced at each kind of moment, recorded model | Every recovery path runs. This can't be left to a 5% chance | No | Nightly, or on demand |
| 5 Live model | Real model, sim, validation devices at 5%, repeated runs | It actually works | Yes | On demand. Results are saved |
| 6 Gate | Held-out seeds and the final appliances | It generalises | Yes | Milestone gates only |
| Console | Browser run on recorded fixtures, at desktop and phone width, in both themes | The timeline, steering and replay work | No | Before merging Console changes |

### Measuring "works"

`rav eval` runs the matrix and scores it from the answer key. These targets are my starting proposal, on held-out devices at 5% error:

| Metric | Target |
|---|---|
| Planted faults found | At least 90% |
| False findings from robot errors | Zero on 95% of runs |
| Controls covered, excluding those no skill can touch | At least 90% |
| Recovery: runs that end with a report, not a crash or a hang | 100% |
| Boundary violations (joint control, changed verdict, answer leak) | Zero, always |
| Same device, different names: same findings | At least 90% |
| Better than the rule-based baseline on faults found, with no more false findings | Yes |

We also track tokens, cost, crossings and time the arm waits, but those aren't pass or fail yet. A model can't be judged on the reward alone, because a skipped control and a found fault score the same.

## Vetting models

A small probe on Nov 7 used one generic scenario. Each model ran once, so **this says what's reachable, not which is best:**

| Model | Result |
|---|---|
| `gemini-3.5-flash` | Worked: 4 to 5 s a turn, with a sensible sequence (read the evidence, then retry) |
| `gemini-robotics-er-2-preview` | Worked: 2.5 to 5 s a turn. It retried without reading the evidence, then asked to re-explore |
| `gemini-3.8-flash` | First turn took 85 s, and the second got a 503 for high demand |
| `gemini-3.1-pro-preview`, `gemini-4-argon` | 429 on free-tier quota, with a retry delay of about 12 hours. **Not testable on this key today** |
| `gemini-2.5-pro` | 404: no longer offered to new users |

All three that responded returned reasoning text and thought signatures. A full comparison of 3 models on 6 devices with 3 repeats is 54 runs, each many turns, so it needs a paid tier.

The comparison runs in stages: flash-class models on dev devices while the harness is rough, then pro-class on validation, then a mixed setup if it helps (a stronger model for planning, a faster one for routine stops). The choice is a config value, never code. Prompts stay shared across models, so nothing gets tuned to one.

## Milestones

Each one ends with something that runs. Sizes are relative: S, M or L.

| # | Milestone | Done when | Size | Needs |
|---|---|---|---|---|
| 0 | **Ground clear:** PR #1 merged, uncommitted Console work resolved, eval sets chosen | The branch has both | S | Decisions below |
| 1 | **System 1 ready for an outside caller:** the HANDOFF items above | Tier 3 passes | L | 0, Joseph's review |
| 2 | **Honest test world:** error injector, fault catalogue, answer key, scorer | A forced-error run reproduces from its seed, and scoring works with the rule baseline | M | 1 |
| 3 | **Agent core:** model client, tool belt, guards, limits, retest rule, recorded-model replay | Tiers 0 to 2 pass with no API key | L | Can start beside 1 against the mock |
| 4 | **Two services, first real run:** `rav-agent`, telemetry moved, `live_sim.py` retired | The model completes a run on preset C, then on generated seeds, with no error injection | M | 1, 3 |
| 5 | **Co-evolve:** turn on 5%, run validation, fix the harness and prompts by general class, pick models | Tier 4 passes, and tier 5 meets the targets on validation | L | 2, 4, quota |
| 6 | **Console overhaul:** timeline, composer, evidence, replay | Works on recorded and live runs, and a steering message visibly changes what the model does | L | Can start after 3, using recorded runs |
| 7 | **Final appliances:** device loader, manual loader, any missing skills | Both appliances run in the sim with the harness and prompts unchanged since the last gate | L | CADs and manuals, 5 |
| 8 | **Gate and demo hardening:** held-out run, a long hold, API-down fallback | Tier 6 meets the targets, and the demo survives losing the API | M | 5, 6, 7 |

**Biggest risks:**
- Getting arbitrary CAD into a working sim, with perception to match. That's the least-known part until the CADs arrive.
- API capacity. The probe has already hit 429, 503 and an 85 s turn, so the demo can't depend on one model being available.
- Real-arm differences stay out of scope here, but every contract added has to work with a real arm. `HANDOFF.md` lists what `--robot real` still needs.

## Decisions needed

| # | Question | Default if nobody objects |
|---|---|---|
| 1 | Does the 5% mean a chance per action, as above, including false alarms that don't reflect a real problem? | Yes |
| 2 | Can we use a paid Gemini key? Pro-class models aren't reachable on this one | Build on flash until there is |
| 3 | The uncommitted Console work (project bar, `liveProject`, 16 files) came along to this branch | Its own commit and PR first, so it stays apart from this work |
| 4 | Does System 2 add the System 1 items, with Joseph reviewing, or does Joseph add them? | Added here, Joseph reviews each contract change |
| 5 | May sim runs auto-approve plans during evals? The boundary doc allows this only for mocks today | Yes for sim evals, recorded on the run and refused on a real arm. Needs a doc change |
| 6 | Is the retest rule above right, including "intermittent" as its own result? | Yes |
| 7 | Should the model see the CAD when planning? | No: manual and scan to plan, CAD to diagnose |
| 8 | What's the hard deadline? | None assumed. It decides how much of 6 and 7 gets built before the demo |

**With the CADs, please include:**
- The file format (STEP, Onshape link or other)
- Which parts move and how
- What each control is meant to do
- Any faults you've planted, kept apart from the rest so they can stay in the answer key
