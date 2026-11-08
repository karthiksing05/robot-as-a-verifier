"""An authored sim appliance (appliances/<id>/) as a product the CAD loop can fix, and a fix as a device the sim can run.

    tags = tags_dict("appliances/interval-timer")              # the tag file the CAD checks and the analyst need
    path = patched_device("appliances/interval-timer", "A", {"bezel_min": solid}, out)   # a device file for the sim

The device file is the sim's truth, so nothing here reads its faults to decide anything: the tags come from its bodies,
controls and Rev A geometry, and a patched device is the tested revision with new solids swapped in.

**Fit model.** A printed sliding fit tighter than the printer's tolerance binds. A sliding body whose parts come within
BIND_CLEARANCE_MM of the parts around it travels only BIND_TRAVEL_MM, and otherwise its control's full travel. The sim
needs that as a number (a joint range), so a patched device derives it from its geometry instead of keeping the
revision's. It reproduces every authored travel: each Rev A fit that binds is under 0.3 mm, every other fit is 0.4 mm or
more (tests/test_appliance_cad.py checks the interval timer, label printer and wall thermostat, Rev A and B).
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
from typing import Any

import cadquery as cq
import yaml

from .generic import load_step

BIND_CLEARANCE_MM = 0.3   # per side; below this a printed slide binds (the same number as the tags' min_clearance)
BIND_TRAVEL_MM = 0.1      # how far a binding slide goes before it sticks
NEAR_MM = 1.0             # a static part this close to a control's moving parts is part of that control (its bezel)
STL_TOL, STL_ANGULAR = 0.05, 0.25   # as system-1/sim/tools/cad_to_meshes.py


def _cfg(device_dir: pathlib.Path) -> dict:
    return yaml.safe_load((device_dir / "device.yaml").read_text())


def _choices(cfg: dict, rev: str) -> dict:
    return dict(i.split("=") for i in rev.split(",")) if "=" in rev else cfg["revs"][rev]


def _subs(cfg: dict, rev: str) -> dict[str, str]:
    """$part -> the part name this revision uses."""
    ch, out = _choices(cfg, rev), {}
    for fault, opts in (cfg.get("faults") or {}).items():
        out.update(opts[ch[fault]].get("parts") or {})
    return out


def _name(p: str, subs: dict) -> str:
    return subs.get(p[1:], p) if p.startswith("$") else p


def suffixes(cfg: dict) -> list[str]:
    """Revision tags in part names ('_revA'): the tag file names parts without them, so a fix applies to any revision."""
    out = set()
    for opts in (cfg.get("faults") or {}).values():
        for rev, opt in opts.items():
            for name in (opt.get("parts") or {}).values() if isinstance(opt, dict) else ():
                m = re.search(r"_rev[A-Za-z0-9]+$", name)
                if m:
                    out.add(m.group(0))
    return sorted(out)


def _strip(name: str, sfx: list[str]) -> str:
    for s in sfx:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def _unit(v) -> list[float]:
    n = sum(c * c for c in v) ** 0.5
    return [round(c / n, 6) for c in v]


def _collidable(cfg: dict, root: str, subs: dict) -> list[str]:
    r = cfg["roots"][root]
    return [_name(p, subs) for p in r["parts"]]


def _slides(cfg: dict, subs: dict) -> list[dict]:
    """Bodies that slide and are made of CAD parts (a button's cap), with their part names for this revision."""
    out = []
    for b in cfg.get("bodies") or []:
        j = b.get("joint") or {}
        if j.get("type") == "slide" and b.get("parts"):
            out.append({**b, "parts": [_name(p, subs) for p in b["parts"]]})
    return out


def _clearance(parts: dict[str, cq.Shape], moving: list[str], around: list[str]) -> tuple[float, str | None]:
    best, who = float("inf"), None
    for m in moving:
        for s in around:
            if s in parts and m in parts and s not in moving:
                d = parts[m].distance(parts[s])
                if d < best:
                    best, who = d, s
    return best, who


def fit_travel(clearance_mm: float, design_travel_mm: float) -> float:
    return BIND_TRAVEL_MM if clearance_mm < BIND_CLEARANCE_MM else design_travel_mm


def tags_dict(device_dir: str | pathlib.Path, rev: str = "A", step: str | pathlib.Path | None = None) -> dict:
    """The CAD tag file for an authored appliance: one press control per sliding button made of CAD parts. Its parts are
    the moving cap and the static parts within NEAR_MM of it (the bezel); the biggest part of each root (the housing) is
    fixed. Toggles, handles and wells aren't covered yet."""
    device_dir = pathlib.Path(device_dir)
    cfg = _cfg(device_dir)
    subs = _subs(cfg, rev)
    sfx = suffixes(cfg)
    parts = cad_parts(device_dir, rev, step)
    fixed = set()
    for root in cfg["roots"]:
        named = [p for p in _collidable(cfg, root, subs) if p in parts]
        if named:
            fixed.add(max(named, key=lambda p: parts[p].Volume()))
    by_body = {b["name"]: b for b in _slides(cfg, subs)}
    controls = {}
    for c in cfg.get("controls") or []:
        b = by_body.get(c.get("body"))
        if b is None:
            continue
        around = [p for p in _collidable(cfg, b["root"], subs) if p in parts]
        near = sorted({s for s in around for m in b["parts"] if m in parts and parts[m].distance(parts[s]) < NEAR_MM})
        own = [*b["parts"], *near]
        axis = _unit(b["joint"]["axis"])
        travel = float(c.get("travel", b["joint"]["range"][1] if not isinstance(b["joint"]["range"][1], str) else 0.3))
        reprintable = [p for p in own if p not in fixed]
        gap, fit_with = _clearance(parts, b["parts"], [p for p in near if p in reprintable])
        entry: dict[str, Any] = {
            "skill": "press",
            "parts": [_strip(p, sfx) for p in own],
            "reprintable": [_strip(p, sfx) for p in reprintable],
            "moving": [_strip(p, sfx) for p in b["parts"]],
            "motion": {"type": "slide", "axis": axis, "travel": travel},
            "contact": [float(v) for v in c["top"]],
            "approach": axis,
        }
        if fit_with:
            entry["fit"] = [_strip(b["parts"][0], sfx), _strip(fit_with, sfx)]
        controls[c["id"]] = entry
    return {
        "controls": controls,
        "fixed": sorted(_strip(p, sfx) for p in fixed),
        "ignore_suffixes": sfx,
        "min_clearance": BIND_CLEARANCE_MM,
        "source": {"document": f"appliance:{device_dir.name}", "tested_version": rev, "device": str(device_dir.resolve())},
    }


def cad_parts(device_dir: str | pathlib.Path, rev: str = "A", step: str | pathlib.Path | None = None) -> dict[str, cq.Shape]:
    """The revision's parts that the sim collides: every root's parts and every body's, without the visual-only ones
    (labels, reference electronics), which overlap the case on purpose."""
    device_dir = pathlib.Path(device_dir)
    cfg = _cfg(device_dir)
    subs = _subs(cfg, rev)
    parts = load_step(pathlib.Path(step) if step else device_dir / "build" / f"rev{rev}.step")
    keep = {p for root in cfg["roots"] for p in _collidable(cfg, root, subs)}
    keep |= {p for b in cfg.get("bodies") or [] for p in (_name(q, subs) for q in b.get("parts") or [])}
    return {n: s for n, s in parts.items() if n in keep}


class _NoAliases(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def write_tags(device_dir: str | pathlib.Path, path: str | pathlib.Path, rev: str = "A") -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# generated by rav_cad.appliance.tags_dict from the device file and its build; don't edit\n"
                    + yaml.dump(tags_dict(device_dir, rev), Dumper=_NoAliases, sort_keys=False))
    return path


def derived_params(cfg: dict, rev: str, parts: dict[str, cq.Shape]) -> dict[str, dict]:
    """For every sliding body whose travel is a $param: the travel its geometry gives, with the clearance behind it."""
    subs = _subs(cfg, rev)
    travel_of = {c.get("body"): c.get("travel") for c in cfg.get("controls") or []}
    out = {}
    for b in _slides(cfg, subs):
        hi = b["joint"]["range"][1]
        if not (isinstance(hi, str) and hi.startswith("$")):
            continue
        gap, who = _clearance(parts, b["parts"], _collidable(cfg, b["root"], subs))
        design = float(travel_of.get(b["name"]) or 0.3)
        out[hi[1:]] = {"value": fit_travel(gap, design), "body": b["name"], "clearance_mm": round(gap, 3), "against": who}
    return out


def patched_device(device_dir: str | pathlib.Path, rev: str, new_parts: dict[str, cq.Shape], out: str | pathlib.Path) -> dict:
    """A copy of the device at `rev` with `new_parts` (named as the tag file names them, without revision tags) swapped
    in: their meshes rebuilt, and every geometry-derived travel recomputed by the fit model. Returns the new device
    file's path, the revision to run, and what changed. The original folder isn't touched."""
    device_dir, out = pathlib.Path(device_dir).resolve(), pathlib.Path(out).resolve()
    cfg = _cfg(device_dir)
    subs, sfx = _subs(cfg, rev), suffixes(cfg)
    base = load_step(device_dir / "build" / f"rev{rev}.step")
    actual = {_strip(n, sfx): n for n in base}
    unknown = sorted(set(new_parts) - set(actual))
    if unknown:
        raise ValueError(f"the device has no part {', '.join(unknown)}")
    parts = dict(base)
    for name, solid in new_parts.items():
        parts[actual[name]] = solid
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for f in device_dir.iterdir():   # the manual, verify checks and wiring: what a run and the scorer read beside the device
        if f.is_file() and f.name != "device.yaml":
            shutil.copy(f, out / f.name)
    build_src, build = device_dir / "build", out / "build"
    build.mkdir()
    pattern = cfg["meshes"]   # e.g. build/meshes_rev{rev}
    revs_needed = set(_choices(cfg, rev).values()) | {"A", "B"}
    warnings = []
    for r in sorted(revs_needed):
        src = device_dir / pattern.format(rev=r)
        dst = out / pattern.format(rev=r)
        dst.parent.mkdir(parents=True, exist_ok=True)
        touched = [actual[n] for n in new_parts if (src / "manifest.json").is_file() and actual[n] in json.loads((src / "manifest.json").read_text())]
        if not touched:
            dst.symlink_to(src, target_is_directory=True)
            continue
        shutil.copytree(src, dst)
        manifest = json.loads((dst / "manifest.json").read_text())
        for name in touched:
            solid = parts[name]
            solid.exportStl(str(dst / f"{name}.stl"), tolerance=STL_TOL, angularTolerance=STL_ANGULAR)
            box = solid.BoundingBox()
            entry = manifest[name]
            if entry.pop("collision", None):
                warnings.append(f"{name} had convex collision pieces; the patched part collides as its hull")
            entry.update(file=f"{name}.stl", min=[box.xmin, box.ymin, box.zmin], max=[box.xmax, box.ymax, box.zmax], volume=solid.Volume())
        (dst / "manifest.json").write_text(json.dumps(manifest, indent=1))
    derived = derived_params(cfg, rev, parts)
    before = derived_params(cfg, rev, base)
    new_cfg = dict(cfg)
    new_cfg["params"] = {**(cfg.get("params") or {}), **{k: v["value"] for k, v in derived.items()}}
    new_cfg["meta"] = {**(cfg.get("meta") or {}), "patched_from": f"{device_dir.name} rev {rev}", "patched_parts": sorted(new_parts)}
    path = out / "device.yaml"
    path.write_text(f"# {device_dir.name} rev {rev} with {', '.join(sorted(new_parts))} replaced by a CAD fix (rav_cad.appliance.patched_device)\n"
                    + yaml.safe_dump(new_cfg, sort_keys=False))
    changed = {k: {"from": before[k]["value"], "to": v["value"], "clearance_from": before[k]["clearance_mm"], "clearance_to": v["clearance_mm"]}
               for k, v in derived.items() if before.get(k, {}).get("value") != v["value"] or before.get(k, {}).get("clearance_mm") != v["clearance_mm"]}
    return {"device": str(path), "rev": rev, "parts": {n: actual[n] for n in new_parts}, "travel": changed, "warnings": warnings}
