# harness

Runs a test through [System 1's tools](../../docs/system-boundary.md#control-what-system-2-can-call): explores, plans, gets approval, handles each stop, applies steering, computes the reward, writes the log and report, and runs the fix loop. It decides nothing about verdicts.

| File | What it does | State |
|---|---|---|
| [`loop.py`](src/rav_harness/loop.py) | `run_test`, `fix_and_retest`, steering, answering stops | Works |
| [`commands.py`](src/rav_harness/commands.py) | Slash commands, starting with `/explore`, and `rule_responder`, which the model replaces | Works, with rules standing in for the model |
| [`client.py`](src/rav_harness/client.py) | `McpSystem1`: the tools over HTTP, with a token | Works |
| [`amendments.py`](src/rav_harness/amendments.py) | Assigns each amended plan its [approval level](../../docs/system-boundary.md#approving-an-amended-plan) | Works |
| [`reward.py`](src/rav_harness/reward.py) | Coverage and reward from verdicts | Works |
| [`runlog.py`](src/rav_harness/runlog.py) | `events.jsonl`, `report.json` | Works |
| [`trace.py`](src/rav_harness/trace.py) | Model turns and tool calls, with each failure's layer | Works; no real model calls it yet |
| [`mock.py`](src/rav_harness/mock.py) | `FakeSystem1`, the planted-fault demo, and a scripted model for the trace | Works |

## Add these here

Each has one seam already, so it can be built and tested alone:

| Add | File | Plugs in as | Kanban |
|---|---|---|---|
| **Responding to stops with the model** | `respond.py` | A `Responder` passed to `run_test`. This is what fails and escalations are waiting for | Harness primed for exploration |
| **`/explore` with memory** | `commands.py` | Recall similar products, then write the high-level plan | Harness primed for exploration |
| Manual parser | `manual.py` | Input to the planner | Parse the manual |
| Planner | `planner.py` | A `Planner` function passed to `run_test` | Seed the test plan |
| Plan validator | `validate.py` | Between the plan and approval | |
| Concept memory | `memory/` | Compiles into `Step.check`, which System 1 evaluates | Cobweb concept memory |
| Analyst | [`analyst.py`](src/rav_harness/analyst.py) | An `Analyst` passed to `fix_and_retest`: takes an `AnalystContext` (finding, `read_params()`, every step's measurements, `cad.check`, the backend's rules, a tracer) and returns a root cause and one patch, or `None` when no CAD change fixes it. `rule_analyst` knows the planted faults; `cli_analyst` asks the model through `claude -p` on the Claude Code login (no API key), checks each answer and asks again with the reasons; `model_analyst` does the same through the API, testing changes with `check_patch`. Both fall back to the rules offline. `make_onshape_analyst` lets the model edit the real Onshape model on its own branch through the `rav-cad` MCP tools, and the patch points at that branch ([cad README](../cad/README.md#onshape)). `make_local_analyst` does the same offline: the model writes CadQuery for new parts in a local workspace through the `rav-cad-local` tools ([cad README](../cad/README.md#local-cad-new-geometry-offline)). Both are `make_cad_analyst` with a different tool server. `rav mock --analyst cli`, `--analyst model`, `--analyst onshape` or `--analyst local`; `rav analyze` runs the CAD step alone on a recorded run | Root cause |
| Report page | `report_html.py` | Reads `report.json` | Final HTML report |

## Running

```bash
uv run rav mock                     # a fake System 1, no hardware
uv run rav run                      # against rav-server: see system-1
uv run rav --policy balanced run    # tethered (default), balanced or autonomous
```

When using Claude, take model IDs and API usage from the current docs rather than from memory.
