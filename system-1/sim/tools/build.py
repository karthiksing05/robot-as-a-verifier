"""Build every test device's generated files: STEP, meshes, collision pieces, answer key, and the registry.
Needs CadQuery, which the sim doesn't, so it runs in a throwaway environment, from the repo root:

    uv run --no-project --python 3.12 --with cadquery --with coacd --with trimesh --with shapely --with pyyaml \\
        python system-1/sim/tools/build.py                 # all devices
        python system-1/sim/tools/build.py lamp kettle     # some

Per device (appliances/<id>/, see docs/device-authoring.md):
    cad/model.py    assemblies() -> {"A": cq.Assembly, "B": cq.Assembly}; CONCAVE = [part names to split into convex pieces]
    device.yaml     the loader's file, with meshes: build/meshes_rev{rev}
writes into <id>/build/ (gitignored): revA.step, revB.step, meshes_revA/, meshes_revB/, answer_key.json.
Then appliances/registry.json (every device's id, title, split, revisions and paths) and docs/devices.md (the gallery,
from each <id>/gallery.md). `--docs` does only those two, with no CAD.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

import yaml

TOOLS = pathlib.Path(__file__).resolve().parent
REPO = TOOLS.parents[2]
DEVICES = REPO / "appliances"  # one folder per device, beside its source files


def devices(names):
    found = sorted(p.parent for p in DEVICES.glob("*/device.yaml"))
    if names:
        found = [p for p in found if p.name in names]
        missing = set(names) - {p.name for p in found}
        if missing:
            sys.exit(f"no device {sorted(missing)} under {DEVICES}")
    return found


def load_model(folder):
    spec = importlib.util.spec_from_file_location(f"device_model_{folder.name}", folder / "cad" / "model.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(folder / "cad"))  # a model may import its own helpers beside it
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(folder / "cad"))
    return mod


def meshes(folder, model):
    build = folder / "build"
    build.mkdir(exist_ok=True)
    assemblies = model.assemblies()
    if set(assemblies) != {"A", "B"}:
        sys.exit(f"{folder.name}: assemblies() must return exactly A and B, got {sorted(assemblies)}")
    for rev, assy in assemblies.items():
        step = build / f"rev{rev}.step"
        assy.save(str(step), exportType="STEP")
        out = build / f"meshes_rev{rev}"
        subprocess.run([sys.executable, str(TOOLS / "cad_to_meshes.py"), str(step), str(out)], check=True, stdout=subprocess.DEVNULL)
        concave = list(getattr(model, "CONCAVE", []))
        if concave:
            subprocess.run([sys.executable, str(TOOLS / "decompose_meshes.py"), str(out), *concave], check=True, stdout=subprocess.DEVNULL)


def choices(cfg, rev):
    return dict(i.split("=") for i in rev.split(",")) if "=" in rev else cfg["revs"][rev]


def answer_key(folder, cfg):
    """Sim truth for scoring: every fault, and per revision which faults are in it and which of those a test can see
    (a fault is masked while a fault it's masked_by is also in)."""
    faults = cfg.get("faults", {})
    key = {"device": folder.name, "name": cfg["name"], "split": cfg.get("meta", {}).get("split"), "faults": [], "revs": {}}
    for fid, f in faults.items():
        key["faults"].append({"id": fid, **{k: f.get(k) for k in ("what", "class", "piece", "property", "masked_by", "expect")}})
    for rev in cfg["revs"]:
        ch = choices(cfg, rev)
        active = [f for f in faults if ch.get(f) == "A"]
        visible = [f for f in active if not any(ch.get(m) == "A" for m in faults[f].get("masked_by") or [])]
        key["revs"][rev] = {"choices": ch, "faults": active, "observable": visible, "masked": [f for f in active if f not in visible]}
    (folder / "build" / "answer_key.json").write_text(json.dumps(key, indent=1) + "\n")


def registry():
    out = []
    for folder in devices(None):
        cfg = yaml.safe_load((folder / "device.yaml").read_text())
        meta = cfg.get("meta", {})
        rel = folder.relative_to(REPO)
        out.append({"id": folder.name, "title": meta.get("title", cfg["name"]), "split": meta.get("split"), "revs": list(cfg["revs"]),
                    "device": (rel / "device.yaml").as_posix(), "manual": (rel / "manual.md").as_posix(), "project": meta.get("project", folder.name),
                    "built": (folder / "build" / "meshes_revB" / "manifest.json").is_file()})
    (DEVICES / "registry.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


GALLERY_HEAD = """# Test devices

The simulated appliances RAAV is tested on. Each is its own CadQuery design with a manual, planted faults (Rev A) and
their fixes (Rev B), described in the vocabulary of [device-theory.md](device-theory.md). How they're built:
[device-authoring.md](device-authoring.md). This page is assembled from each device's `gallery.md` by
`system-1/sim/tools/build.py`; edit those (`appliances/<id>/gallery.md`), not this.

Splits: **dev** devices are for building and tuning, **validation** for checking that tuning generalises, and
**held-out** devices are only run for final results, so their faults are not described anywhere a model or a tuner reads.
"""
SPLITS = ("dev", "validation", "held_out")


def gallery(entries):
    """docs/devices.md from every device's gallery.md. A held-out device's faults line is replaced, whatever it says."""
    out = [GALLERY_HEAD]
    for split in SPLITS:
        rows = [d for d in entries if d["split"] == split]
        if not rows:
            continue
        out.append(f"\n## {split.replace('_', '-').capitalize()}\n")
        for d in rows:
            path = DEVICES / d["id"] / "gallery.md"
            text = path.read_text().strip() if path.is_file() else f"### {d['title']} (`{d['id']}`)\n\nNo gallery entry yet."
            if split == "held_out":
                text = "\n".join("**Faults:** held out." if line.startswith("**Faults:**") else line for line in text.splitlines())
            out.append(text + "\n")
    (REPO / "docs" / "devices.md").write_text("\n".join(out))


def main():
    args = [a for a in sys.argv[1:] if a != "--docs"]
    for folder in [] if "--docs" in sys.argv else devices(args):
        cfg = yaml.safe_load((folder / "device.yaml").read_text())
        print(f"{folder.name}: building", flush=True)
        meshes(folder, load_model(folder))
        answer_key(folder, cfg)
    entries = registry()
    gallery(entries)
    for d in entries:
        print(f"  {d['id']:20s} {d['split'] or '-':10s} revs {','.join(d['revs']):20s} {'built' if d['built'] else 'NOT BUILT'}")


if __name__ == "__main__":
    main()
