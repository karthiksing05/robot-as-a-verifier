"""Bundle a recorded Live run as fixtures/sample_run/sample-sim, so the Console can replay a real sim run with no Python.

    uv run python fixtures/make_sim_sample.py runs/live-preset-C-fault-123456
"""
import json
import pathlib
import shutil
import sys

FILES = ["events.jsonl", "report.json", "timeline.json", "poses.bin", "cameras.mp4"]
SAMPLE_ID = "sample-sim"


def main(source: str) -> None:
    src, out = pathlib.Path(source), pathlib.Path(__file__).resolve().parent / "sample_run" / SAMPLE_ID
    run_id = src.name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for name in FILES:
        shutil.copy(src / name, out / name)
    shutil.copytree(src / "scene", out / "scene")
    for name in ("events.jsonl", "report.json", "timeline.json", "scene/scene.json"):
        path = out / name
        path.write_text(path.read_text().replace(run_id, SAMPLE_ID))
    print(json.dumps({"files": sum(1 for p in out.rglob("*") if p.is_file()), "mb": round(sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6, 1)}))


if __name__ == "__main__":
    main(sys.argv[1])
