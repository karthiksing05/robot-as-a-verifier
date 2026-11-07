"""End-to-end benchmark: explore.py headless, no film, one device x one arm setup, one JSON line per run.

    python tools/bench.py OUT.jsonl SETUP SEED|C [extra explore.py args]
    python tools/bench.py runs/bench.jsonl slop18 1650 --sensing tactile

SETUP is one of the keys of SETUPS. SEED is a generated device (placed at random on the desk) or C for the preset
demo device. Each line has the setup, the device, every step's verdict and reason, the status and the wall time.
Set PYTHONUTF8=1 on Windows: explore.py prints symbols the console codepage can't."""
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

SETUPS = {"ideal": ["--ideal"], "realistic": [], "slop": ["--slop"], "slop18": ["--slop", "--stiffness", "18"],
          "miscalibrated": ["--offsets", "2"], "slopmis": ["--slop", "--stiffness", "18", "--offsets", "2"]}


def main():
    out, setup, seed, extra = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:]
    os.chdir(REPO)
    import explore
    argv = SETUPS[setup] + ([] if seed == "C" else ["--seed", seed, "--placement", "random"]) + extra + ["--headless"]
    t0 = time.time()
    rec = dict(cond=setup, seed=seed, extra=extra)
    try:
        show = explore.main(argv)
        rec.update(status=show.dash.status, n_parts=len(show.scene.parts) if show.scene else 0,
                   steps=[dict(step=f"{st['skill']} {st['target']}", verdict=r["verdict"], reason=r.get("reason", ""))
                          for st, r in zip(show.steps, show.results)])
    except Exception as e:
        rec.update(error=repr(e), tb=traceback.format_exc()[-2000:])
    rec["wall_s"] = round(time.time() - t0)
    with open(out, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps({k: rec.get(k) for k in ("cond", "seed", "status", "error", "wall_s")}))


if __name__ == "__main__":
    main()
