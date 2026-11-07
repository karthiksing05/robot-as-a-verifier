# System 2: the harness

Decides what to do, and changes the plan when it's wrong: the LLM, slash commands, planning, memory, reward, reports, the CAD fix loop and the Console. It reaches the robot only through [System 1's tools](../docs/system-boundary.md#control-what-system-2-can-call), so the two can run on different machines.

**Before adding anything, ask: does this need judgment across a whole run, or across past runs?** If it has to keep working with no network, it belongs in [System 1](../system-1/README.md). [The full split](../docs/system-boundary.md).

**Rules:**

- Import only `rav_interface` from System 1. `tests/test_repo.py` checks this. One file has a temporary exception, below.
- Keep crossings few and meaningful, and count them. Every stop costs model time and tokens.
- The model proposes. It never decides a verdict or the reward, and it can't grade its own plan changes.
- Don't ask System 1 for raw data. Fetch evidence by reference, only when the summary isn't enough.

| Folder | What it is | Owner |
|---|---|---|
| [`harness/`](harness/README.md) | Run loop, slash commands, approval levels, reward, reports, fix loop. The LLM goes here | Karthik, Joseph |
| [`contracts/`](contracts/README.md) | Run events, findings, fixes and reports. Re-exports the wire types | Karthik, changed by anyone ([rules](../CONTRIBUTING.md#changing-a-contract)) |
| [`cad/`](cad/README.md) | Applies and checks CAD patches | Bayan |
| [`console/`](console/README.md) | Web front end, including the [How it works page](console/web/src/screens/Wiki.tsx) | Karthik, Bayan |
| [`subjects/`](subjects/README.md) | The products under test: CAD and manuals | Max |
| [`fixtures/`](fixtures) | Sample runs the Console builds against | Karthik |

```bash
uv sync
uv run rav mock                 # the whole story with a fake System 1
uv run pytest
uv run rav run                  # against rav-server on this machine
uv run rav explore              # /explore: find the controls, and print them
uv run rav --policy balanced run    # how much System 1 does before it defers: tethered, balanced, autonomous
```

**The exception:** [`console/server/live_sim.py`](console/server/live_sim.py) still runs the sim in the same process, for the Live screen's video and poses, and needs `uv sync --extra live`. It works as long as this machine runs the sim. Those streams have to move behind System 1's server before Live can show a robot on another machine.
