"""CAD patching behind contracts.CadBackend: ParamsBackend (a JSON file) and CadQueryBackend (the model). See
system-2/cad/README.md."""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from rav_contracts import CADPatch

_INDEXED = re.compile(r"^(\w+)\[(\d+)\]$")


class ParamsBackend:
    """The default: a patch is a small diff of a JSON parameter file. Works with no CAD kernel.

    A CadQuery backend adds the model rebuild and kernel checks on top of this; an MCP backend sends the same
    patch to a CAD app. `limits` maps a parameter name to (min, max), the spec's bounds."""

    name = "params"

    def __init__(self, path: str | pathlib.Path, limits: dict[str, tuple[float, float]] | None = None):
        self.path, self.limits = pathlib.Path(path), limits or {}

    def read_params(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def _get(self, params: dict, name: str) -> Any:
        m = _INDEXED.match(name)
        if m:
            return params[m[1]][int(m[2])]
        return params[name]

    def check(self, patch: CADPatch) -> list[str]:
        problems, params = [], self.read_params()
        for c in patch.changes:
            try:
                current = self._get(params, c.param)
            except (KeyError, IndexError, TypeError):
                problems.append(f"{c.param}: no such parameter")
                continue
            if current != c.from_value:
                problems.append(f"{c.param}: the patch expects {c.from_value}, the file has {current}")
            bounds = self.limits.get(_INDEXED.sub(r"\1", c.param))
            if bounds and isinstance(c.to_value, (int, float)) and not bounds[0] <= c.to_value <= bounds[1]:
                problems.append(f"{c.param}: {c.to_value} is outside {bounds}")
        return problems

    def apply(self, patch: CADPatch) -> str:
        problems = self.check(patch)
        if problems:
            raise ValueError("; ".join(problems))
        params = self.read_params()
        for c in patch.changes:
            m = _INDEXED.match(c.param)
            if m:
                params[m[1]][int(m[2])] = c.to_value
            else:
                params[c.param] = c.to_value
        self.path.write_text(json.dumps(params, indent=2) + "\n")
        return str(self.path)


class CadQueryBackend:
    """Rebuilds the appliance in CadQuery from a YAML spec and runs kernel checks before anything prints.

    A patch names parameters by dotted path (`features.button_2.clearance`). The names used by
    params.rev_a.json also work: `button_clearance[1]` means the second button's clearance, `handle_style` the
    door handle's style. `check` previews the patch on a rebuilt model (posture, stale values, every kernel
    check). `apply` needs `approved_by` set, then writes the new revision's spec next to the old one and exports
    only the parts whose geometry changed. Needs the `cad` extra; see system-2/cad/README.md."""

    name = "cadquery"
    ALIASES: list[tuple[re.Pattern, Any]] = [
        (re.compile(r"^button_clearance\[(\d+)\]$"), lambda m: f"features.button_{int(m[1]) + 1}.clearance"),
        (re.compile(r"^handle_style$"), lambda m: "features.door.handle_style"),
    ]

    def __init__(self, spec_path: str | pathlib.Path, out_dir: str | pathlib.Path | None = None,
                 interference: bool = True, require_approval: bool = True):
        # require_approval: refuse a patch with no approved_by. The harness gates approval itself (approve() and
        # an "approved" event) without filling approved_by yet, so pass False when the harness drives this.
        self.require_approval = require_approval
        self.spec_path = pathlib.Path(spec_path)
        self.out_dir = pathlib.Path(out_dir) if out_dir else self.spec_path.parent / "out"
        self.interference = interference

    def _spec(self):
        from .parametric.spec import Spec
        return Spec.load(self.spec_path)

    def resolve(self, name: str) -> str:
        for pattern, to in self.ALIASES:
            m = pattern.match(name)
            if m:
                return to(m)
        return name

    # Values the feature code accepts for the text parameters an analyst is likely to patch (features/fixed.py, door.py)
    CHOICES = {"handle_style": "tab (needs a pinch), bar (a fingertip hooks behind it and pulls), "
                               "push_latch (a flat push releases a bought push-to-open latch)",
               "hinge": "left or right"}

    def rules(self) -> str:
        """The limits a patch must meet, as text for an analyst. check() enforces them; this says them up front."""
        spec = self._spec()
        lim, post = spec.limits, spec.posture
        steps = ", ".join(f"{k} {v:g}" for k, v in post.max_step.items())
        lines = [f"A patch changes at most {post.max_params} parameter(s), from the value the spec has now.",
                 f"Largest change per patch, by parameter name (mm or the parameter's unit): {steps}.",
                 f"Clearances stay within {lim.clearance_range[0]:g} to {lim.clearance_range[1]:g} mm; walls at least {lim.min_wall:g} mm.",
                 f"The robot presses with a round {lim.fingertip_d:g} mm fingertip or a flat pad. It can't pinch or grip, "
                 f"so a control that needs a pinch fails by design.",
                 *(f"{name}: {values}." for name, values in self.CHOICES.items()),
                 "The patched model is rebuilt and checked (walls, spacing, fingertip room, measured clearance, "
                 "interference, door swing) before anyone approves it."]
        return "\n".join(lines)

    def read_params(self) -> dict[str, Any]:
        """Every patchable parameter by dotted path, with its current value."""
        from .parametric.features import effective_params
        spec = self._spec()
        out: dict[str, Any] = {"rev": spec.rev}
        for f in spec.features:
            for k, v in {"u": f.u, "v": f.v, **effective_params(f)}.items():
                out[f"features.{f.id}.{k}"] = v
        for k, v in spec.shell.model_dump().items():
            if not isinstance(v, dict) and v is not None:
                out[f"shell.{k}"] = v
        return out

    def _run(self, patch: CADPatch):
        from .parametric import patch as patcher
        spec = self._spec()
        edits = [{"param": self.resolve(c.param), "old": c.from_value, "new": c.to_value} for c in patch.changes]
        result = patcher.apply(spec, {"edits": edits}, interference=self.interference, new_rev=patch.revision_to)
        batching = spec.rev == patch.revision_to          # another approved patch going into the same print
        if patch.revision_from != spec.rev and not batching:
            result.accepted = False
            result.reasons.insert(0, f"the patch starts from rev {patch.revision_from}, the spec is rev {spec.rev}")
        return result

    def check(self, patch: CADPatch) -> list[str]:
        return self._run(patch).reasons

    def apply(self, patch: CADPatch) -> str:
        if self.require_approval and not patch.approved_by:
            raise ValueError("a teammate approves a patch before it is applied and printed (set approved_by)")
        result = self._run(patch)
        if not result.accepted:
            raise ValueError("; ".join(result.reasons))
        from .parametric.build import export
        out = self.out_dir / f"rev_{result.new_rev}"
        out.mkdir(parents=True, exist_ok=True)
        export(result.built, out, only=set(result.changed_parts))
        log = out / "patches.json"                      # every patch in this revision, in the order applied
        done = json.loads(log.read_text()) if log.exists() else []
        log.write_text(json.dumps(done + [{**result.to_json(), "approved_by": patch.approved_by or "harness approval (see the run log)"}], indent=2))
        stem = re.sub(r"\.rev_\w+$", "", self.spec_path.stem)
        new_spec = self.spec_path.with_name(f"{stem}.rev_{result.new_rev.lower()}.yaml")
        result.new_spec.save(new_spec)
        self.spec_path = new_spec
        return str(out)
