# Robot as a Verifier

A verifier for autonomous hardware R&D. Give it a product, its instruction manual and (if you have one) its CAD. A robot arm with pressure and touch sensing explores the product, tests every control, and writes bug reports backed by force traces and frames. You can steer the run from a web console at any time, trace a bug back to the exact failure, and optionally send a fix to the CAD. The fix only counts if the same tests score higher on the new print.

Built by Karthik, Joseph, Max and Bayan for MakeCU 2026 (Columbia, Nov 7 to 8).

> **Status, Nov 7.** The perception-and-test pipeline works in simulation (119 of 122 tests on 16 unseen devices). The harness drives it through System 1's tool server, on the sim and over a network. The real-arm backend is built and tested against a simulated motor bus, not yet on the arm. Still to build: the LLM planner and the manual-driven plan. See [PLAN.md](PLAN.md).

## Two systems

**Read [System 1 and System 2](docs/system-boundary.md) before adding code.** It says which system your change belongs to.

| | [`system-1/`](system-1/README.md): the robot | [`system-2/`](system-2/README.md): the harness |
|---|---|---|
| Does | Perception, IK, control, skills, verdict rules, safety, local retries | LLM calls, slash commands, planning, memory, reward, reports, CAD, Console |
| AI | Almost none: classifiers, IK, fixed policies. Never calls an LLM | The only place an LLM is called |
| Starts work | Only when System 2 starts a routine | When a person starts a run |
| Demo machine | Joseph's Windows laptop | Joseph's laptop or Karthik's Mac |

They talk through [seven tools](docs/system-boundary.md#control-what-system-2-can-call) over MCP, and each has its own install. System 2 can start routines, but it has no tool that moves a joint. [`docs/`](docs/README.md) holds what both sides need to read, and the pitch.

## Appliance firmware

The current MC-6 centrifuge and MW-1 microwave board project is in [`firmware/`](firmware/README.md). Each appliance has its own **Arduino Uno R4 WiFi** and upload target: `mc6` or `mw1_r4_wifi`. Open `firmware/` as its own VS Code/PlatformIO project, or run builds from that directory. It includes the sketches, button discovery, saved calibration records, serial monitors and host tests.

The existing appliance-local firmware files remain older snapshots. Use the top-level `firmware/` project for the current physical boards; the simulation device definitions remain in `appliances/`.

## Get running

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you.

```bash
cd system-2
uv sync                    # the light install: harness, CAD params and tests
uv run rav mock            # the full demo story with a fake System 1: Rev A, 2 bugs, patch, Rev B, reward 0.60 -> 1.00
uv run pytest              # no hardware, GPU or network needed
```

To run the two systems for real, in two terminals:

```bash
cd system-1 && uv sync --extra sim && uv run rav-server --robot sim --depth    # waits for System 2
cd system-2 && uv sync && uv run rav run                                       # one full run
```

To reach System 1 on another machine, start the server with `RAV_TOKEN=<secret>` and `--host 0.0.0.0`, then run `RAV_TOKEN=<secret> uv run rav run --url http://<its address>:8780/mcp`.

Each run writes `system-2/runs/<id>/events.jsonl` and `report.json`. The Console renders those files.

Add what you work on:

| You work on | In | Install | Then |
|---|---|---|---|
| Sim, perception, skills | `system-1` | `uv sync --extra sim` | `cd sim` for Joseph's film and benchmark tools |
| Real cameras | `system-1` | `uv sync --extra sim --extra phone` | [`real_wrist.py`](system-1/hardware/real_wrist.py) for the wrist (Windows only), [`real_cameras.py`](system-1/hardware/real_cameras.py) for the run's video and the dropped iPhone |
| Real arm | `system-1` | `uv sync --extra sim --extra arm` | [`system-1/arm`](system-1/arm/README.md) |
| The tools | `system-1` | `uv sync` | [`system-1/server`](system-1/server/README.md) |
| Planner, analyst, memory | `system-2` | `uv sync --extra model` | [`system-2/harness`](system-2/harness/README.md) |
| CAD | `system-2` | `uv sync --extra cad` | [`system-2/cad`](system-2/cad/README.md) |
| Console | `system-2` | `npm install` in `console/web` | [`system-2/console`](system-2/console/README.md) |

## Which source to trust

| For | The source of truth is |
|---|---|
| Who does what, and status | [Kanban](https://claude.ai/artifact/9Dm3x26boTyvHhrqAyEpaV) |
| The split between the systems, to share | [System 1 and System 2](https://claude.ai/artifact/6d9gQhE7LqDb9xUeMPYPDa) |
| Current architecture, interfaces and decisions | This repo: [`docs/`](docs/README.md) and [`docs/decisions.md`](docs/decisions.md) |
| Research, bill of materials, reasoning and history | [Google Doc](https://docs.google.com/document/d/1fRen3rUlAyUSO0AACiKA1Zz-LrHpg4sqn350Y-rfYi0/edit) |
| What the finished product should look like | [Self-Evolving Hardware mockup](https://claude.ai/artifact/2wY8eCvh5VkNb8QSE98Sum) |
| The harness principles this draws on | [Self-Evolving Robots](https://claude.ai/artifact/VxmRPoiAXK3pCHxKmjgRv6) |
| Sim results as shown to others | [Robot Product Tester](https://claude.ai/artifact/Fia1Xqk11wDS5uwNQLh3ci) |

If two of these disagree on something current, the repo wins. Fix the other one or add a line to [`docs/decisions.md`](docs/decisions.md).
