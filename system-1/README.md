# System 1: the robot

Carries out routines, measures them and judges them. **It starts nothing on its own:** it waits for System 2, runs a largely autonomous routine, and reports back only at [a defined stop](../docs/system-boundary.md#when-system-1-wakes-system-2).

**Before adding anything, ask: would this still have to work if the model's API went down mid-routine?** If not, it probably belongs in [System 2](../system-2/README.md). [The full split](../docs/system-boundary.md).

**Rules:**

- No LLM calls, and no imports from System 2. `tests/test_boundary.py` checks both.
- Hard classifiers, IK and fixed policies only. Pretrained detectors like OWLv2 and SAM are fine.
- Handle what you can locally. Defer only for what needs judgment, with the numbers that show why.
- Low-level control never crosses to System 2. No tool moves a joint or motor, and none should.

| Folder | What it is | Owner |
|---|---|---|
| [`interface/`](interface/README.md) | The wire contract with System 2: types and tool names. The only thing System 2 may import from here | Karthik, changed by anyone ([rules](../CONTRIBUTING.md#changing-a-contract)) |
| [`server/`](server/README.md) | The tool server, and the engine that decides when to stop | Karthik, Joseph |
| [`core/`](sim/docs/code-map.md#the-rig) | The pipeline: perception, touch, skills, verdict rules. Runs on any rig, sim or real | Joseph |
| [`sim/`](sim/README.md) | The MuJoCo rig, the film (`explore.py`) and the benchmark | Joseph |
| [`hardware/`](sim/docs/real-arm.md) | The real arm's and cameras' drivers, and `hw_rig.py` | Joseph |
| [`arm/`](arm/README.md) | SO-101 bring-up and bench tests | Joseph, Max |
| [`subjects/`](subjects/appliance/firmware) | Device firmware: the ground-truth Pico is a sensor this system reads | Max |

```bash
uv sync                         # interface, server and tests, with no sim
uv run rav-server --robot mock  # the server with a scripted robot
uv run pytest                   # sim tests skip without --extra sim

uv sync --extra sim             # add the sim
uv run rav-server --robot sim --depth        # D405 route: no model downloads
uv run rav-server --robot sim --seed 1650    # the team's setup: downloads OWLv2 and SAM, about 780 MB
```
