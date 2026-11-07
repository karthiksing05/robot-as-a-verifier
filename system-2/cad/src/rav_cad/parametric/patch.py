"""Apply a CAD patch: a small diff of named parameters (stand-in for Karthik's CADPatch contract).

  {"edits": [{"param": "features.button_2.clearance", "old": 0.15, "new": 0.40}],
   "reason": "...", "predicted_effect": "..."}

A single edit can also be given flat: {"param": ..., "old": ..., "new": ..., "reason": ...}.
Refused unless: every `old` matches the current spec, the posture allows the size of the change, and the new
revision passes every kernel check. On success, only the parts whose geometry changed are listed for printing,
with a rough cost for the teammate who approves it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import checks
from .build import Built, build, export, signatures
from .spec import Spec, next_rev


@dataclass
class PatchResult:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    old_rev: str = ""
    new_rev: str = ""
    edits: list[dict] = field(default_factory=list)
    changed_parts: list[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    new_spec: Spec | None = None
    built: Built | None = None

    def summary(self) -> str:
        head = f"{'ACCEPTED' if self.accepted else 'REFUSED'}  rev {self.old_rev} -> {self.new_rev or '-'}"
        lines = [head] + [f"  {e['param']}: {e['old']} -> {e['new']}" for e in self.edits]
        lines += [f"  refused: {r}" for r in self.reasons]
        if self.accepted:
            lines.append(f"  reprint: {', '.join(self.changed_parts) or 'nothing'}")
            if "shell" in self.changed_parts:
                lines.append("  WARNING: this reprints the SHELL (hours). Prefer a patch that changes only inserts.")
            lines.append(f"  cost: about {self.cost['minutes']:.0f} min, {self.cost['grams']:.1f} g "
                         f"(rough estimate from volume, not from the slicer)")
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("new_spec", "built")}


def _edits(patch: dict) -> list[dict]:
    if "edits" in patch:
        return list(patch["edits"])
    return [{k: patch[k] for k in ("param", "old", "new")}]


def _max_step(spec: Spec, path: str) -> float:
    steps = spec.posture.max_step
    return steps.get(path.split(".")[-1], steps.get("default", float("inf")))


def cost(spec: Spec, b: Built, parts: list[str]) -> dict:
    pieces = b.pieces()
    vol = sum(pieces[p].Volume() for p in parts)                  # mm^3
    pr = spec.printer
    grams = vol / 1000 * pr.density * pr.fill
    minutes = (pr.overhead_min + grams / pr.g_per_min) if parts else 0.0
    return {"grams": round(grams, 1), "minutes": round(minutes, 1), "volume_mm3": round(vol, 1)}


def apply(spec: Spec, patch: dict, interference: bool = True, new_rev: str | None = None) -> PatchResult:
    edits = _edits(patch)
    r = PatchResult(False, old_rev=spec.rev, edits=edits)
    if len(edits) > spec.posture.max_params:
        r.reasons.append(f"{len(edits)} parameters changed; the posture allows {spec.posture.max_params} per patch")
    for e in edits:
        try:
            cur = spec.get(e["param"])
        except KeyError as err:
            r.reasons.append(str(err).strip("'\""))
            continue
        if isinstance(cur, (int, float)) and not isinstance(cur, bool):
            if abs(float(cur) - float(e["old"])) > 1e-9:
                r.reasons.append(f"{e['param']} is {cur} in rev {spec.rev}, not {e['old']}; patch is stale")
            step, limit = abs(float(e["new"]) - float(e["old"])), _max_step(spec, e["param"])
            if step > limit + 1e-9:
                r.reasons.append(f"{e['param']} changes by {step:g} mm; the posture allows {limit:g}")
        elif cur != e["old"]:
            r.reasons.append(f"{e['param']} is {cur!r} in rev {spec.rev}, not {e['old']!r}; patch is stale")
    if r.reasons:
        return r

    new = spec.with_edits({e["param"]: e["new"] for e in edits})
    new = new.model_copy(update={"rev": new_rev or next_rev(spec.rev)})
    r.new_rev = new.rev
    nb = build(new)
    rows = checks.run(nb, interference=interference)
    r.checks = checks.as_json(rows)
    failed = [f"{c.name}: {c.detail}" for c in rows if not c.ok]
    if failed:
        r.reasons += [f"check failed on rev {new.rev}: {f}" for f in failed]
        return r

    before, after = signatures(build(spec)), signatures(nb)
    r.changed_parts = sorted(n for n in after if before.get(n) != after[n])
    r.cost = cost(new, nb, r.changed_parts)
    r.accepted, r.new_spec, r.built = True, new, nb
    return r


def apply_files(spec_path: str | Path, patch_path: str | Path, out_dir: str | Path) -> PatchResult:
    spec = Spec.load(spec_path)
    patch = json.loads(Path(patch_path).read_text())
    r = apply(spec, patch)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if r.accepted:
        export(r.built, out, only=set(r.changed_parts))
    (out / "patch_result.json").write_text(json.dumps({**r.to_json(), "patch": patch}, indent=2))
    return r
