"""rav-cad-local: the CAD tools the analyst uses to fix the product offline, by writing CadQuery code for new parts.

    python -m rav_cad.local.mcp_server --tags subjects/centrifuge/onshape.yaml --workspace <folder> --out <dir> \
        [--target lid] [--verify s4] [--sources sources.json]

The tested revision is the workspace's own base parts (made by LocalCadBackend.open_branch).

The server can only write to the workspace it was started on; the tested revision (the base) is never touched.
write_part runs the model's code in a separate process (see sandbox.py) and keeps the solid only if it is one valid
solid. Every write is kept as a CadEdit for the patch; logging, check() and submit_fix() are shared with the Onshape
server (cadtools.py).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import tempfile

from mcp.server.mcpserver import MCPServer
from rav_contracts import CadEdit

from ..cadtools import BaseSession, Image, ToolError, add_common_tools, make_traced
from .backend import LocalCadBackend, faces_of
from .sandbox import SandboxError
from .workspace import Workspace

__all__ = ["LocalSession", "ToolError", "build_server", "main"]

MAX_FACES = 80
MAX_SOURCE = 8000
CODE_HELP = (
    "Python run in a fresh process with: cq (CadQuery), math, np (numpy), geom (rav_cad.parametric.geom: prism, "
    "block, cyl, fuse, ...), old (this part's current solid, a cq.Shape in the assembly frame, mm) and parts (the "
    "other parts by name, read-only). Set `result` to the new part: one valid solid (cq.Workplane or cq.Shape), in "
    "the same assembly frame. Start from `old` and change only what the fix needs: old.cut(...), old.fuse(...), or "
    "a new solid built from old's faces and box. No file, network or other imports. 60 s limit.")


def _box(s) -> list[float]:
    bb = s.BoundingBox()
    return [round(v, 2) for v in (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)]


class LocalSession(BaseSession):
    """Everything one analyst run can do to its local workspace."""

    backend: LocalCadBackend

    @property
    def workspace(self):
        return self.backend.branch(self.ws)

    def parts(self) -> dict:
        return self.workspace.parts()

    def _reprintable(self, part: str) -> None:
        t = self.backend.tags
        if part not in self.parts():
            raise ToolError(f"no part {part}; parts are: {', '.join(sorted(self.parts()))}")
        if part in t.fixed or not any(part in c.reprintable for c in t.controls.values()):
            allowed = sorted({p for c in t.controls.values() for p in c.reprintable})
            raise ToolError(f"{part} isn't reprintable; you may write: {', '.join(allowed)}")

    def get_part(self, part: str) -> dict:
        s = self._part(part)
        faces = faces_of(s)
        out = {"part": part, "box_mm": _box(s), "volume_mm3": round(s.Volume(), 1), "faces": len(faces),
               "face_list": faces[:30], "your_code": self.workspace.code(part),
               "reprintable": any(part in c.reprintable for c in self.backend.tags.controls.values())}
        src = self.backend.sources.get(part)
        if src:
            out["reference_source"] = src[:MAX_SOURCE]
            out["reference_note"] = ("the CadQuery that builds this kind of part in the product's own parametric "
                                     "model; a reference only: your code works on `old`")
        return out

    def write_part(self, part: str, code: str) -> dict:
        self._reprintable(part)
        before = self.parts()[part]
        try:
            res = self.workspace.write_part(part, code)
        except SandboxError as e:
            raise ToolError(f"the code failed, nothing changed: {e}") from None
        after = self.parts()[part]
        self.edits.append(CadEdit(op="write_part", target=part, summary=(
            f"{part}: new solid from CadQuery ({len(code.splitlines())} lines); volume {before.Volume():.0f} -> "
            f"{after.Volume():.0f} mm3")))
        return {"part": part, **res, "volume_before_mm3": round(before.Volume(), 1), "box_before_mm": _box(before),
                "next": "check() to judge it, render() or measure_gap to look"}

    def reset_part(self, part: str) -> dict:
        if not self.workspace.reset_part(part):
            return {"part": part, "reset": False, "note": "it was already the tested part"}
        self.edits.append(CadEdit(op="reset_part", target=part, summary=f"{part}: back to the tested part"))
        return {"part": part, "reset": True}

    def list_faces(self, part: str) -> dict:
        faces = faces_of(self._part(part))
        return {"part": part, "faces": len(faces), "list": faces[:MAX_FACES]}

    def render(self, highlight: list[str] | None = None) -> bytes:
        from ..parametric.render import render_parts
        parts = self.parts()
        changed = set(self.workspace.overridden()) | set(highlight or [])
        with tempfile.TemporaryDirectory() as tmp:
            path = render_parts(parts, pathlib.Path(tmp) / "r.png", highlight=changed, fixed=set(self.backend.tags.fixed),
                                title=f"{self.backend.product} (changed in red)")
            return path.read_bytes()


def build_server(s: LocalSession) -> MCPServer:
    mcp = MCPServer("rav-cad-local", instructions=(
        "CAD tools for fixing the product by writing CadQuery code. You work in your own workspace; the revision the "
        "robot tested is never changed. Look (list_controls, get_part, list_faces, measure_gap, render), write a new "
        "solid for a reprintable part (write_part), then check(). Repeat until check() passes, then submit_fix(). If "
        "no CAD change can fix the finding, submit_fix with no_cad_fix=true."))
    traced = make_traced(s)
    add_common_tools(mcp, s, traced)

    @mcp.tool(description="One part in your workspace: box, volume, faces (id, kind, area, plane or cylinder, box), "
                          "the code you wrote for it if any, and for parts of our own parametric model the CadQuery "
                          "that builds it, as a reference.")
    def get_part(part: str) -> dict:
        return traced("get_part", {"part": part}, lambda: s.get_part(part))

    @mcp.tool(description="Replace a reprintable part with the solid your CadQuery code makes. " + CODE_HELP +
                          " Returns the new box, volume and face count; errors come back with the traceback and "
                          "nothing changes.")
    def write_part(part: str, code: str) -> dict:
        return traced("write_part", {"part": part, "code": code}, lambda: s.write_part(part, code))

    @mcp.tool(description="Put a part back as it was in the tested revision.")
    def reset_part(part: str) -> dict:
        return traced("reset_part", {"part": part}, lambda: s.reset_part(part))

    @mcp.tool(description="One part's faces in your workspace, largest first: id, kind (plane, cylinder, ...), area, "
                          "the plane's normal and centre or the cylinder's radius, axis and origin, and the face's box, "
                          "in mm. Ids are stable until the part changes.")
    def list_faces(part: str) -> dict:
        return traced("list_faces", {"part": part}, lambda: s.list_faces(part))

    @mcp.tool(description="Iso, front and top pictures of the whole product in your workspace: the body grey, parts "
                          "you changed (and any you name in highlight) red, the rest blue.")
    def render(highlight: list[str] | None = None) -> Image:
        return traced("render", {"highlight": highlight}, lambda: Image(data=s.render(highlight), format="png"))

    return mcp


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="rav-cad-local-mcp", description=__doc__.splitlines()[0])
    ap.add_argument("--tags", required=True, help="the product's tag file")
    ap.add_argument("--workspace", required=True, help="the workspace folder to edit")
    ap.add_argument("--out", required=True, help="where calls.jsonl and result.json go")
    ap.add_argument("--target", default=None, help="the control the finding is about")
    ap.add_argument("--verify", nargs="*", default=[], help="step ids to rerun on the new revision")
    ap.add_argument("--sources", default=None, help="JSON {part: CadQuery source} shown as references")
    args = ap.parse_args(argv)
    ws = Workspace(args.workspace)
    sources = json.loads(pathlib.Path(args.sources).read_text()) if args.sources else None
    backend = LocalCadBackend(args.tags, ws.base_parts(), product=ws.meta.get("name"), sources=sources)
    session = LocalSession(backend, args.workspace, args.out, args.target, args.verify)
    build_server(session).run("stdio")


if __name__ == "__main__":
    main()
