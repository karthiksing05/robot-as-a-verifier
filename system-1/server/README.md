# server

What System 2 talks to. It runs routines on a robot and reports [stops](../../docs/system-boundary.md#when-system-1-wakes-system-2).

| File | What it does |
|---|---|
| [`engine.py`](src/rav_server/engine.py) | Runs routines on one worker thread, retries locally, and decides when to stop. **Change the stop rules here** |
| [`mcp_server.py`](src/rav_server/mcp_server.py) | The seven tools |
| [`main.py`](src/rav_server/main.py) | `rav-server`: picks the robot, and requires a token off localhost |
| [`robot.py`](src/rav_server/robot.py) | The `Robot` interface the engine drives |
| [`sim_backend.py`](src/rav_server/sim_backend.py) | `PipelineRobot`: Joseph's pipeline as a `Robot` on any rig, converting units and verdict words at the boundary. `SimBackend` is it on the sim's rig |
| [`real_backend.py`](src/rav_server/real_backend.py) | `RealBackend`: `PipelineRobot` on the real SO-101 and wrist camera (`hw_rig.make_rig`), RGB route only |
| [`mock_robot.py`](src/rav_server/mock_robot.py) | A scripted `Robot` for tests |

**The real arm:** `rav-server --robot real --arm-port COM5 --calibration <lerobot-calibrate's file>` builds the rig once at startup with torque off, then asks at the terminal before turning torque on (`--enable-torque` skips the question). The operator answers what each test step did at the same terminal. Ctrl+C stops the arm where it is, then turns torque off as the server stops. It has only run against the fake bus (`tests/test_real_backend.py`).

**Escalation codes not wired up yet:** `pose_unstable` and `unknown_control` are named in the interface, but nothing raises them, because the pipeline doesn't report those situations yet.
