"""What every CAD-tools MCP server shares: one session bound to one branch, call logging, the look-and-measure tools,
check() and submit_fix(). The Onshape server (onshape/mcp_server.py) adds feature and variable edits; the local
server (local/mcp_server.py) adds writing whole parts in CadQuery.

Every call is appended to <out>/calls.jsonl (the harness turns those into tool_call events, since the server runs
inside the analyst's own process). submit_fix writes <out>/result.json, which the harness reads back. A fix can only
be submitted when check() passed on the branch exactly as it is now.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image

from rav_contracts import CADPatch, CadEdit, Hypothesis, RootCause

from .parametric.geom import distance

__all__ = ["BaseSession", "Image", "ToolError", "add_common_tools", "make_traced"]


class BaseSession:
    """Everything one analyst run can do to its branch, whatever the backend. Subclasses supply parts()."""

    def __init__(self, backend: Any, workspace: str, out: str | pathlib.Path, target: str | None = None,
                 verify_with: list[str] | None = None):
        self.backend, self.ws, self.target = backend, workspace, target
        self.verify_with = verify_with or []
        self.out = pathlib.Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.edits: list[CadEdit] = []
        self.last_check = None

    def log(self, tool: str, args: dict, ok: bool, result: Any) -> None:
        line = {"t": time.time(), "tool": tool, "args": args, "ok": ok,
                "result": result if isinstance(result, (str, dict, list)) else str(result)}
        with (self.out / "calls.jsonl").open("a") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def write_result(self, data: dict) -> None:
        (self.out / "result.json").write_text(json.dumps(data, indent=2, default=str))

    def parts(self) -> dict:
        raise NotImplementedError

    def _part(self, name: str):
        parts = self.parts()
        if name not in parts:
            raise ToolError(f"no part {name}; parts are: {', '.join(sorted(parts))}")
        return parts[name]

    # -- the shared tools --

    def list_controls(self) -> dict:
        t = self.backend.tags
        return {"target": self.target, "fixed": list(t.fixed), "controls": {
            c.id: {"skill": c.skill, "parts": list(c.parts), "reprintable": list(c.reprintable), "moving": list(c.moving),
                   "motion": c.motion.__dict__ if c.motion else None} for c in t.controls.values()}}

    def measure_gap(self, part_a: str, part_b: str) -> dict:
        parts = self.parts()
        missing = [p for p in (part_a, part_b) if p not in parts]
        if missing:
            raise ToolError(f"no part {', '.join(missing)}; parts are: {', '.join(sorted(parts))}")
        return {"part_a": part_a, "part_b": part_b, "gap_mm": round(distance(parts[part_a], parts[part_b]), 3)}

    def part_size(self, part: str) -> dict:
        bb = self._part(part).BoundingBox()
        return {"part": part, "size_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
                "min": [round(bb.xmin, 2), round(bb.ymin, 2), round(bb.zmin, 2)],
                "max": [round(bb.xmax, 2), round(bb.ymax, 2), round(bb.zmax, 2)]}

    def check(self) -> dict:
        self.last_check = self.backend.check_branch(self.ws, quick=True)   # the full check runs before apply
        c = self.last_check
        return {"ok": not c.reasons, "reasons": c.reasons, "changed": c.changed, "control": c.target,
                "microversion": c.microversion}

    def submit_fix(self, root_cause: str, confidence: float, hypotheses: list[dict], evidence: list[str],
                   predicted: str, no_cad_fix: bool = False) -> dict:
        try:
            cause = RootCause(finding=self.target or "?", evidence=evidence, hypotheses=[Hypothesis(**h) for h in hypotheses],
                              root_cause=root_cause, confidence=float(confidence))
        except Exception as e:  # noqa: BLE001 - shown to the model
            raise ToolError(f"the diagnosis doesn't match its schema: {e}") from None
        if no_cad_fix:
            self.write_result({"cause": cause.model_dump(mode="json"), "patch": None})
            return {"submitted": True, "patch": None}
        c = self.last_check
        if c is None or c.reasons:
            raise ToolError("call check() and get it to pass before submitting a fix")
        mv = self.backend.microversion(self.ws)
        if mv != c.microversion:
            raise ToolError("the branch changed after the last check; call check() again")
        patch = CADPatch(file=self.backend.url(self.ws), revision_from="A", revision_to="B", changes=[],
                         backend=self.backend.name, verify_with=self.verify_with, source=self.backend.source(self.ws, mv),
                         edits=self.edits, constraints_checked=[r["name"] for r in c.results if r["ok"]])
        self.write_result({"cause": cause.model_dump(mode="json"), "patch": patch.model_dump(mode="json"),
                           "predicted": predicted, "changed": c.changed})
        return {"submitted": True, "changed": c.changed, "url": self.backend.url(self.ws)}


def make_traced(s: BaseSession) -> Callable:
    """Run one tool call, log it, and turn any failure into a ToolError the model can read."""
    def traced(name: str, args: dict, fn):
        try:
            result = fn()
        except ToolError as e:
            s.log(name, args, False, str(e))
            raise
        except Exception as e:  # noqa: BLE001 - backend errors go back to the model to read
            s.log(name, args, False, f"{type(e).__name__}: {e}")
            raise ToolError(f"{type(e).__name__}: {e}") from e
        s.log(name, args, True, result if not isinstance(result, (bytes, Image)) else "<image>")
        return result
    return traced


def add_common_tools(mcp: MCPServer, s: BaseSession, traced: Callable) -> None:
    @mcp.tool(description="The product's controls: which parts belong to each, which you may reprint, how they move. "
                          "`target` is the control the finding is about.")
    def list_controls() -> dict:
        return traced("list_controls", {}, s.list_controls)

    @mcp.tool(description="The smallest gap in mm between two parts on your branch, at rest (assembly positions).")
    def measure_gap(part_a: str, part_b: str) -> dict:
        return traced("measure_gap", {"part_a": part_a, "part_b": part_b}, lambda: s.measure_gap(part_a, part_b))

    @mcp.tool(description="A part's bounding box on your branch, in mm.")
    def part_size(part: str) -> dict:
        return traced("part_size", {"part": part}, lambda: s.part_size(part))

    @mcp.tool(description="Run the robot-centred checks your change can affect, on your branch against the tested "
                          "version: valid printable parts, only one control's reprintable parts changed, nothing overlaps "
                          "the changed parts, the affected controls move freely, the fingertip reaches them and can hook "
                          "a pull control. Returns the reasons it fails, or ok. The full check runs again before apply.")
    def check() -> dict:
        return traced("check", {}, s.check)

    @mcp.tool(description="Finish. Needs a passing check() on the branch as it is now, unless no_cad_fix is true (the "
                          "fault is perception, the arm, wiring or firmware). hypotheses: [{cause, p, check?, ruled_out?}].")
    def submit_fix(root_cause: str, confidence: float, hypotheses: list[dict[str, Any]], evidence: list[str],
                   predicted: str, no_cad_fix: bool = False) -> dict:
        args = {"root_cause": root_cause, "confidence": confidence, "no_cad_fix": no_cad_fix}
        return traced("submit_fix", args, lambda: s.submit_fix(root_cause, confidence, hypotheses, evidence, predicted, no_cad_fix))
