"""A rehearsal of `rav-server --robot real` with no hardware: the same server, arg checks, torque gate, robot name and
RealBackend, but the rig is the sim's preset C behind RealArm on the simulated motor bus
(sim_rig.make_rig(driver="real")). The cameras and the device's readout are the sim's, so no question is asked after a test motion. System 2 then runs
against it as against the real arm (system-1/docs/real-s1-s2-test-plan.md).

    uv run --extra sim --extra arm python server/sim_bus_server.py --port 8785 --telemetry-port 0
    uv run --extra sim --extra arm python server/sim_bus_server.py --sim-device ../appliances/centrifuge/device.yaml
    cd ../system-2 && uv run rav explore --url http://127.0.0.1:8785/mcp
"""
import sys
import threading

from rav_server import main, real_backend
from rav_server.sim_backend import CORE_DIR, SIM_DIR, PipelineRobot, on_path


class SimBusBackend(real_backend.RealBackend):
    device = None  # a device file (--sim-device) in place of preset C, at revision A

    def __init__(self, arm_port, calibration, refine=True, **_):
        on_path(CORE_DIR, SIM_DIR)
        import glfw
        import sim_rig

        rig = sim_rig.make_rig(None, slop=True, sensing="current", driver="real", device=self.device, rev="A")
        PipelineRobot.__init__(self, rig, refine=refine, plan_id="rules-real")
        self.rest, self.closing = None, threading.Lock()
        # built on the main thread, as the real backend is, but routines run on the engine's worker, and the sim's
        # cameras render with an OpenGL context bound to one thread: let the worker take it (the real camera has none)
        glfw.make_context_current(None)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--sim-device" in args:
        k = args.index("--sim-device")
        SimBusBackend.device, args = args[k + 1], args[:k] + args[k + 2:]
    real_backend.RealBackend = SimBusBackend
    main.main(["--robot", "real", "--arm-port", "SIM", "--calibration", "SIM", "--enable-torque", *args])
