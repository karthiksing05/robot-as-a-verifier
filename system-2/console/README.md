# Console

Part of [System 2](../README.md). The front end: everything a person sees and does during a run. Owners: Karthik and Bayan.

**State:** **Live** runs Joseph's MuJoCo pipeline for real through a small bridge, and every run it records can be revisited. The sample fixtures, edits and approvals on saved runs stay in the browser. Nothing reaches a real robot or Onshape until the server below exists.

Style: the [Console Style Study](https://claude.ai/artifact/Wmmtfsv3LoUoZ2ENZ3Dup7), with tokens in [`web/src/styles/tokens.css`](web/src/styles/tokens.css).

## Run it

```bash
cd system-2/console/web
npm install
npm run dev      # http://127.0.0.1:5173
npm test         # data rules: reward recomputed from events, graph, edits, access
```

That's all you need to work on the Console. **`sample-sim` is a real recorded sim run** bundled with the fixtures: it replays in the full 3D view with no Python, MuJoCo or GPU. Open it from **Runs**, or from **Live** when the bridge is off.

To run the sim live, also start the bridge from the repo root:

```bash
cd system-2
uv sync --extra live-depth    # about 460 MB, on the D405 route. --extra live adds PyTorch for the camera route, about 970 MB
uv run python console/server/live_sim.py
```

The first start compiles for about a minute. Refresh the sample after changing what a run records: `uv run python fixtures/make_sim_sample.py runs/<id>`.

Choose **Demo** or **Prod**, then press **GO**. There's no login. To change environment, press **Exit**. The top bar sets who you're acting as: that name goes on approvals and edits, and it's a courtesy with no security behind it.

| Environment | Shows |
|---|---|
| Demo | The MuJoCo sim, its recorded runs and the sample fixtures, with a placeholder CAD model |
| Prod | Where we'll do real interfacing: the real arm and the real CAD (Onshape). Neither is connected yet, so it's empty |

Each environment is described once, in `ENVIRONMENTS` in [`session.ts`](web/src/lib/session.ts): what runs tests, which CAD it uses, whether it's connected. Screens read those properties rather than checking a name, so connecting Prod means filling in its interfaces and flipping `connected`.

Judges can steer but can't approve or enter Prod. A CAD patch has to be approved by someone other than its author.

## Projects

The Console opens on projects, with one project per appliance design. A project holds its revisions and runs, and its review is computed from the run logs. Each project is a file, `system-2/subjects/<id>/project.json`, beside that product's CAD and manual.

**Watching the model.** With `rav-agent` running, Live starts and shows the model's run: its reasoning summaries as they arrive, each tool call with its arguments and result, System 1's stops, approvals, and messages from the operator, in one timeline. Beside it are the sim, the plan and coverage, and the run's totals by layer. Opening a step shows its evidence. A saved model run replays through the same view at `#/live?replay=<run id>`, and `sample-agent` is a scripted one for building and demos: it isn't real model output. Reasoning is labelled a summary because that's what the API returns, not the model's full chain of thought.

Live talks to `rav-agent` on 8790 (macOS uses 8770 for AirDrop) and to System 1's telemetry on 8781. `VITE_AGENT_URL` and `VITE_TELEMETRY_URL` change them. Without `rav-agent`, Live falls back to the bridge below.

Every screen of a project (its story, Live, its CAD, its runs) has the same bar on top, for moving between them or changing project. Live starts and shows runs for the project selected there, and the bridge's `/health` says which project is running. A physical project can't run until the arm is connected, so its Live tab says so and points to the sim.

A run belongs to the project it names in `TestRequest.project`. Older runs are matched by their product name. Runs that match nothing are listed under All runs.

**Moving to a database:** screens use `ProjectStore` in [`lib/projects.ts`](web/src/lib/projects.ts), which only calls `/api/projects`. That API uses a `ProjectBackend` from [`server/projects.ts`](web/server/projects.ts), passed in from [`vite.config.ts`](web/vite.config.ts). A database needs another `ProjectBackend` and a copy of the files, with no screen changes. Kanban: *Move projects from repo files to a database*.

## Live and revisiting a run

[`server/live_sim.py`](server/live_sim.py) runs `system-1/sim/explore.py` unchanged and hooks it from outside. It hands the browser the compiled model and streams body poses at 30 Hz, so the main view is drawn by Three.js ([`Sim3D.tsx`](web/src/components/Sim3D.tsx)) at the display's frame rate with a camera you can orbit. The wrist and phone cameras stay as motion JPEG, since their pictures come from the sim's camera models, and events plus telemetry are server-sent events. Without WebGL the main view falls back to motion JPEG. The bridge binds to 127.0.0.1, and takes commands only from the Console's origin.

- **Planted fault:** the default device is preset C with `button_2` jammed after 0.3 mm of travel ([`faults.py`](../../system-1/sim/faults.py)). The physics changes, and the sim's usual rules fail the step as stuck. The fault is recorded in the run's `TestRequest.spec`.
- **Real effects:** plan approval holds the arm, and pause, stop, skip and test-next change the sim at the next step boundary.
- **Speed:** 1x to 8x, 4x by default, is sim seconds per second on screen, at every stage, so 1x is real time. It doesn't change the physics. A recording keeps its own fixed pace, so it comes out the same whatever speed the run was watched at.
- **Records:** each run writes `runs/<id>/` with `events.jsonl`, `report.json`, `poses.bin` and `scene/` (the 3D view, replayed by the browser), `cameras.mp4` (the other cameras) and `timeline.json` (where each stage and event falls). The dev server lists them, so revisiting needs no bridge. Older runs with a `video.mp4` still play.
- **Runs on an ordinary laptop:** on export, meshes are simplified to about a fifth of their triangles and textures compressed, so a browser downloads 1.8 MB where it took 25 MB. The server no longer renders the main view unless a browser without WebGL asks for it. [`Sim3D.tsx`](web/src/components/Sim3D.tsx) caps at 60 fps, draws only when something changed, and drops through four quality tiers until it keeps up. See [the numbers](#sim-performance).
- **Trace:** clicking a stage or step shows what happened in it, in order: each model turn (what it was told, thought and said, tokens, time) and each tool call (arguments, result, error, time). Failures are filed under the layer that caused them, and the run page's Diagnosis section lists them all. See [integration](../../docs/integration.md#the-model-trace).
- **One run, one page:** clicking a stage or a step jumps the video there and shows its numbers beside it. Bugs, patches, report, decisions, plan and the event log are further down the same page.
- **Limits:** the first team-setup run downloads the OWLv2 and SAM models, about 780 MB. Prioritize and skip work on a control's remaining steps. Adding a step and the chat dock aren't wired into a live run.

## Sim performance

Measured Nov 7 on an Apple Silicon Mac, in Chrome at 1440 × 900, on preset C with the planted fault at 4x. "No GPU" is Chrome's software renderer, standing in for a machine without a usable GPU. No other laptop has been tried yet, and neither has Windows or Linux.

| | Before | After |
|---|---|---|
| Browser download per run | 25 MB | 1.8 MB, cached between runs |
| Frame rate with no GPU | 3.2 fps | 18 to 21 fps |
| Frame rate with a GPU | 120 fps | 60 fps, the cap |
| Server CPU for a whole run | 45 to 54 s | 30 to 40 s |
| Install for a live run | About 970 MB | About 460 MB (`live-depth`) |
| Install to work on the Console | The above | `npm install` only |

## What the server has to add

| Gap | Today | Needs |
|---|---|---|
| Live runs | The sim, through the local bridge | The same for the real arm, on a real server |
| Reasons on edits | Kept in the Console's ledger | An optional `reason` on `SteerCommand` ([changing a contract](../../CONTRIBUTING.md#changing-a-contract)) |
| Retries and fine-tunes | Sent as `add_step` | Decide whether they need their own kinds, and a link from attempt to original step |
| Branches on the graph | Drawn from the flat log | The orchestrator, and an event for what it chose and why |
| Edits on bug reports | Joined in the browser | Log edits to `events.jsonl`, so the record stays whole |
| Onshape | Placeholder model | API keys on the server, glTF export for the viewer, parameter updates. Onshape blocks iframes, so the model appears in our own viewer with a link out. Updating parameters through its API isn't confirmed yet |
| Accounts | None: Go, then pick a name | Real checks on the server, before this leaves localhost |

## Screens

| Screen | Shows | Does | Kanban |
|---|---|---|---|
| Projects | One card per appliance, with its overall result | Creates a project | Console: project manager |
| Project | That appliance's story: brief, what was found and tested, faults, fixes, review | Starts a run on a sim device | Console: project manager |
| Motivation | Why this matters now, written for judges | | |
| Plan | The plan, what the manual says for each step, controls not matched | Edit, approve | Plan + patch approval |
| Live run | Camera, current step, force trace, coverage map, exploration graph | Pause, prioritize, skip, add a test | Showcase the testing process, Exploration graph |
| Chat | The harness's messages and yours | Ask, steer | Console: chat and steering |
| Bug reports | One card per `Finding`, with its evidence | Jump to the exact step and replay it | Console: bug-report traversal |
| Patch | `RootCause`, `CADPatch`, cost estimate | Approve, reject | Plan + patch approval |
| CAD bench | Parameters, 3D model, agent activity, patch diff | Edit a value, replay the agent's edit, send for approval | |
| Approvals and edit log | Every operator edit, with who and why | Approve, reject, withdraw, export | Plan + patch approval |
| Report | Coverage, reward, reward over revisions | Share | Final HTML report |

## The interface

Build against this. It's small on purpose, and it all maps to [`events.py`](../contracts/src/rav_contracts/events.py).

| Direction | Message | Meaning |
|---|---|---|
| Server to UI | `RunEvent` stream, for example over WebSocket | Everything that happens. Replaying `events.jsonl` looks identical to a live run |
| UI to server | `SteerCommand` | Pause, resume, stop, prioritize, skip, add a step, or a chat message |
| UI to server | `{kind, ref, by}` | Approve a plan or a patch |

**Jumping back to a failure:** a `Finding` has `event_seqs` and `step_ids`. Find those events in the log and show them with the trace and frames around them.

**Live force traces** can stay in Rerun for the run itself, since it's already in LeRobot's viz extra. `StepTrace.force_trace` has what the report needs.

## Starting without a robot

[`system-2/fixtures/sample_run/`](../fixtures/sample_run) holds a full Rev A and Rev B run. Regenerate it with `uv run python fixtures/make_fixture.py`. For live events, wrap `run_test` with `MockBackend`: pass `on_event` to `RunLog` to get each event, and a `Steering` object to send commands in.

TypeScript types can come from the JSON Schemas: `uv run python -m rav_contracts.export_schema`.

## Stack ([Q3](../../docs/decisions.md))

A Vite React app in `system-2/console/web`, built first. FastAPI with a WebSocket in `system-2/console/server` is the suggested next step and isn't built. Streamlit and Gradio were dropped in the Doc, and they suit chat with live steering poorly anyway.

## Motion

Seamless motion leads the design. Screens continue through view transitions, data draws itself in, and only what changed moves. Rules live in [`web/src/styles/motion.css`](web/src/styles/motion.css). Everything rests in a readable final state and turns off under reduced motion.
