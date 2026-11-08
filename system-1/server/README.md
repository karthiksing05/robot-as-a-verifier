# server

What System 2 talks to. It runs routines on a robot and reports [stops](../../docs/system-boundary.md#when-system-1-wakes-system-2).

| File | What it does |
|---|---|
| [`engine.py`](src/rav_server/engine.py) | Runs routines on one worker thread, retries locally, and decides when to stop. **Change the stop rules here** |
| [`mcp_server.py`](src/rav_server/mcp_server.py) | The seven tools. `tests/test_readiness.py` is what a caller who knows only them has to be able to do |
| [`main.py`](src/rav_server/main.py) | `rav-server`: picks the robot, and requires a token off localhost |
| [`robot.py`](src/rav_server/robot.py) | The `Robot` interface the engine drives |
| [`sim_backend.py`](src/rav_server/sim_backend.py) | `PipelineRobot`: Joseph's pipeline as a `Robot` on any rig, converting units and verdict words at the boundary. `SimBackend` is it on the sim's rig |
| [`telemetry.py`](src/rav_server/telemetry.py) | What people watch, on its own port: the scene, poses, cameras, force and stage. It also paces a run with `--speed`, and records it with `--record-dir` |
| [`actions.py`](src/rav_server/actions.py) | The skills on offer, as `system_status` publishes them. `tests/test_actions.py` holds the table to the pipeline |
| [`unreliable.py`](src/rav_server/unreliable.py) | Sim only: the arm and world misbehaving at random, to test a caller's recovery |
| [`real_backend.py`](src/rav_server/real_backend.py) | `RealBackend`: `PipelineRobot` on the real SO-101 and wrist camera (`hw_rig.make_rig`), RGB route only |
| [`mock_robot.py`](src/rav_server/mock_robot.py) | A scripted `Robot` for tests |

**The real arm:** `rav-server --robot real --arm-port COM5 --calibration <lerobot-calibrate's file>` builds the rig once at startup with torque off, then asks at the terminal before turning torque on (`--enable-torque` skips the question). The operator answers what each test step did at the same terminal. Ctrl+C stops the arm where it is, then turns torque off as the server stops. It has only run against the fake bus (`tests/test_real_backend.py`).

For the private hotspot setup, `--device-host <System 1 hotspot IP>` serves the appliances on port 8782 and keeps MCP on loopback. See the [Vultr setup](../../deploy/vultr/README.md#system-1).

Before a real arm is useful it needs:

- The appliance's firmware. `--readout serial --readout-port COM7` reads its Pico over USB (`hardware/pico_readout.py`), and `--readout http --readout-device mw1` takes the same snapshots POSTed over WiFi to `/readout/mw1` with `RAV_DEVICE_KEY` (`hardware/http_readout.py`, [`device_api.py`](src/rav_server/device_api.py); the format is in [the firmware README](../subjects/appliance/firmware/README.md#over-wifi)). `affordances` reads either during a slide or turn, but both have only run against stand-ins. Without `--readout`, `RealBackend` uses `OperatorReadout`, which asks the operator once a step ends.
- A hand-eye calibration, the camera's mount offset on the gripper. Every part the scan finds is shifted by it. The last look before a step re-places buttons and doors, but toggles, sliders and dials are tested where the scan put them. The plane sweep doesn't need it: an offset shared by every photo cancels out, and the bundle adjustment corrects each photo's own error from the joints.
- The bench numbers on [the real-arm page](../sim/docs/real-arm.md): servo stiffness and bus timing.

**Escalation code not wired up yet:** `unknown_control` is named in the interface, but nothing raises it, because the pipeline doesn't report parts it couldn't classify.

## Testing a caller on the sim

These flags are for `--robot sim` only, and the server refuses them otherwise.

| Flag | Does |
|---|---|
| `--device PATH`, `--rev R`, `--mount ROOT=clamped\|free` | A device file (`appliances/<id>/device.yaml`) at a revision, in place of a generated device |
| `--effector stock\|probe` | `stock` (the default) is the SO-101's own gripper, the real arm's only effector, sensing by servo current. `probe` is the fingertip probe and pad, kept in the sim as a reference; a real arm refuses it |
| `--seed N`, `--placement random` | A generated device, moved on the desk |
| `--fault NAME[:PART]`, `--fault random`, `--fault-seed N` | A real problem in the physics or wiring, on any part of its kind. Names are in [`faults.py`](../sim/faults.py). Repeatable |
| `--error-rate 0.05`, `--error-seed N` | The chance per action (each step attempt, each explore stage) that something goes wrong |
| `--error-schedule WHEN:KIND,...` | Forces errors, so a test doesn't wait on chance. `WHEN` is an action number, or a control id for its first attempt |
| `--answer-key PATH` | Writes the device's truth, its faults and every error to a file for scoring. No tool can read it |

Errors change the world, and the verdict rules run untouched on whatever then happens. A caller sees what the real fault would show: `missed_aim` lands off the part, `false_alarm` fires a real safety stop, `stale_readout` freezes the readings for one step, `pipeline_fault` raises from a driver mid-step, `dropped_frame` loses one camera frame during a scan (the scan asks again, within a budget), a `pipeline_fault` during a scan (about a third of explore errors) stops it as a `pipeline_error`, `weak_perception` lowers a confidence, shifts a pose or loses a part, `slow_arm` takes longer, and `device_moved` moves the device and marks the scene stale. `device_moved_silent` moves it with nothing said, so only the trend of corrections shows it. It and `camera_dead`, a wrist camera that stops for the rest of a scan and so ends it as a `pipeline_error`, are only ever forced by a schedule.

A jammed dial (`stuck_dial`) comes back `inconclusive` and not `failed`: both pushes stall, and the verdict rule can't tell a jam from a pad on the fin's edge. `dead_dial` is the dial fault that fails cleanly.

`reposition` is a normal step on the control called `device`, with ranges from the device's data. On the sim's generated devices it simply places the device at the new pose. Any move marks the scene stale, so `run_plan` refuses to start until `explore` has run again.

## Watching a run

```bash
uv run rav-server --robot sim --depth --speed 1 --record-dir ../system-2/runs/my-run
```

| Route, on `127.0.0.1:8781` | Gives |
|---|---|
| `GET /health` | Run id, stages, cameras, speed, whether the scene is ready, and the recording's clock |
| `GET /scene.json`, `/scene/<path>` | The compiled model, for the 3D view. `{"run_id": null}` until the first routine builds the robot |
| `GET /poses` | Server-sent events at 30 Hz: seven floats per moving body |
| `GET /telemetry` | Server-sent events named `telemetry`: stage, status, force samples, step, LCD text, probe force |
| `GET /feed/<camera>` | Motion JPEG. `wrist`, and `phone` on the depth route |
| `POST /speed` `{"rate": n}` | Sim seconds per second: 0, 1, 2, 4 or 8. 0 means as fast as the sim goes. Only the Console's origins may call it |

Pacing only waits, so a watched run takes the same physics steps as an unwatched one. Previews don't touch the cameras' noise generators, and a camera renders only while someone is watching it or a recording needs it.

`--record-dir` writes `poses.bin`, `scene/`, `cameras.mp4` and `timeline.json`. One server is one device and one run, so give each run its own folder. System 2 owns the event log, so `timeline.json`'s `events` start empty: fill them from its `anchors`, which pair wall-clock seconds with seconds into the recording.

It binds to `127.0.0.1` only, whatever `--host` says. A Console on another laptop needs a tunnel for now.
