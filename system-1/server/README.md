# server

What System 2 talks to. It runs routines on a robot and reports [stops](../../docs/system-boundary.md#when-system-1-wakes-system-2).

| File | What it does |
|---|---|
| [`engine.py`](src/rav_server/engine.py) | Runs routines on one worker thread, retries locally, and decides when to stop. **Change the stop rules here** |
| [`mcp_server.py`](src/rav_server/mcp_server.py) | The seven tools |
| [`main.py`](src/rav_server/main.py) | `rav-server`: picks the robot, and requires a token off localhost |
| [`robot.py`](src/rav_server/robot.py) | The `Robot` interface the engine drives |
| [`sim_backend.py`](src/rav_server/sim_backend.py) | `PipelineRobot`: Joseph's pipeline as a `Robot` on any rig, converting units and verdict words at the boundary. `SimBackend` is it on the sim's rig |
| [`mock_robot.py`](src/rav_server/mock_robot.py) | A scripted `Robot` for tests |

**Add the real arm** as a `PipelineRobot` over `hw_rig.make_rig(...)` (`system-1/hardware`), and add it to `make_robot` in `main.py`. `--port` is already the HTTP port, so the serial port needs its own flag, such as `--arm-port`. Nothing else here should need to change.

**Escalation codes not wired up yet:** `pose_unstable` and `unknown_control` are named in the interface, but nothing raises them, because the pipeline doesn't report those situations yet.
