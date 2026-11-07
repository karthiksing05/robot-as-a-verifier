"""How fast LeRobot can read all six positions, and how much each position flickers while held still.

    python bus_jitter.py COM10

Holds every motor where it already is (goal = present position, then torque on), reads all six positions with one
sync_read as fast as it can for 10 s, then repeats for 5 s with torque off to separate the sensor's own noise from
the servo hunting. Nothing should move. The sim assumes 100 reads/s and 0.4 counts (1 sigma) of jitter.
"""
import statistics
import sys
import time

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
bus = SerialMotorsBus(port=sys.argv[1], motors={n: Motor(i + 1, "sts3215", MotorNormMode.RANGE_M100_100)
                                                for i, n in enumerate(NAMES)})
bus.connect(handshake=False)


def sample(seconds):
    t_end, times, pos = time.perf_counter() + seconds, [], {n: [] for n in NAMES}
    while time.perf_counter() < t_end:
        t0 = time.perf_counter()
        p = bus.sync_read("Present_Position", normalize=False)
        times.append(time.perf_counter() - t0)
        for n in NAMES:
            pos[n].append(p[n])
    return times, pos


def report(label, times, pos):
    ms = sorted(t * 1000 for t in times)
    print(f"\n{label}: {len(times)} reads of all six in {sum(times):.1f} s = {len(times) / sum(times):.0f} reads/s, "
          f"median {ms[len(ms) // 2]:.1f} ms, slowest 1% {ms[int(len(ms) * 0.99)]:.1f} ms")
    for n in NAMES:
        v = pos[n]
        print(f"  {n:14s} mean {statistics.mean(v):7.1f}  std {statistics.pstdev(v):4.2f} counts  "
              f"range {max(v) - min(v)} counts")


try:
    start = bus.sync_read("Present_Position", normalize=False)
    bus.sync_write("Goal_Position", start, normalize=False)
    bus.enable_torque()
    time.sleep(0.5)
    report("Torque on, holding", *sample(10))
    bus.disable_torque()
    time.sleep(0.5)
    report("Torque off", *sample(5))
finally:
    try:
        bus.disable_torque()
    except Exception:
        pass
    bus.disconnect(disable_torque=False)
