"""Runs one piece of model-written CadQuery code in its own process. Started by sandbox.py, never imported.

argv: <json job>. The job names the code file, the part's current solid (BREP), the folders of neighbour parts,
the output BREP and the import paths. Prints one JSON line: {"ok": true, ...} or {"ok": false, "error": ...}.
"""
import builtins
import json
import sys
import traceback

job = json.loads(sys.argv[1])
sys.path[:0] = job["paths"]

ALLOWED = ("cadquery", "math", "numpy", "rav_cad.parametric.geom", "OCP")
BLOCKED_BUILTINS = ("open", "exec", "eval", "compile", "input", "breakpoint", "exit", "quit", "help", "globals",
                    "vars", "memoryview", "__loader__", "__spec__")


def emit(**kw):
    sys.stdout.write("\n@@RESULT@@" + json.dumps(kw) + "\n")
    sys.stdout.flush()


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    ok = any(name == a or name.startswith(a + ".") for a in ALLOWED) or (
        name == "rav_cad.parametric" and fromlist and set(fromlist) <= {"geom"})
    if level or not ok:
        raise ImportError(f"import of {name!r} is not allowed here; use cadquery (cq), math, numpy or "
                          "rav_cad.parametric.geom")
    return real_import(name, globals, locals, fromlist, level)


try:
    import cadquery as cq  # noqa: E402  (load before the guard: cadquery itself needs files and many modules)
    import math
    import numpy as np
    from rav_cad.parametric import geom

    real_import = builtins.__import__

    def load(path):
        return cq.Shape.importBrep(path)

    class Parts(dict):
        """Neighbouring parts, loaded when first read. Read-only reference geometry."""

        def __init__(self, files):
            super().__init__()
            self._files = files

        def __missing__(self, name):
            if name not in self._files:
                raise KeyError(f"no part {name!r}; parts are: {sorted(self._files)}")
            s = self[name] = load(self._files[name])
            return s

        def keys(self):
            return self._files.keys()

        def __iter__(self):
            return iter(self._files)

        def __contains__(self, name):
            return name in self._files

        def __len__(self):
            return len(self._files)

    safe = {k: getattr(builtins, k) for k in dir(builtins) if k not in BLOCKED_BUILTINS}
    safe["__import__"] = guarded_import
    env = {"__builtins__": safe, "__name__": "part_code", "cq": cq, "math": math, "np": np, "geom": geom,
           "old": load(job["old"]) if job.get("old") else None, "parts": Parts(job["parts"]), "result": None}
    code = open(job["code"]).read()
    # no network for the model's code: sockets refuse to open
    import socket

    def _no_net(*a, **k):
        raise PermissionError("network use is not allowed in part code")
    socket.socket = _no_net
    socket.create_connection = _no_net
except Exception as e:  # setup failure is ours, not the model's
    emit(ok=False, error=f"sandbox setup failed: {e!r}")
    sys.exit(0)

try:
    exec(compile(code, "part_code.py", "exec"), env)
except BaseException as e:  # noqa: BLE001
    tb = "".join(traceback.format_exception(type(e), e, e.__traceback__.tb_next)).splitlines()
    emit(ok=False, error=f"{type(e).__name__}: {e}", traceback="\n".join(tb[-12:]))
    sys.exit(0)

r = env.get("result")
try:
    if isinstance(r, cq.Workplane):
        vals = [v for v in r.vals() if isinstance(v, cq.Shape)]
        r = vals[0] if len(vals) == 1 else (cq.Compound.makeCompound(vals) if vals else None)
    if r is None:
        raise ValueError("the code must set `result` to the new solid (a cq.Workplane or cq.Shape)")
    if not isinstance(r, cq.Shape):
        raise ValueError(f"`result` is a {type(r).__name__}, not a CadQuery shape")
    solids = r.Solids()
    if len(solids) != 1:
        raise ValueError(f"`result` must be exactly one solid (one printable part); it has {len(solids)}. "
                         "Fuse the pieces (a.fuse(b)) or make sure they touch")
    s = solids[0]
    if not s.isValid():
        raise ValueError("`result` is not a valid solid (self-intersecting or open); try .clean() or simpler ops")
    if s.Volume() <= 1e-6:
        raise ValueError("`result` has no volume")
    s = s.clean() if hasattr(s, "clean") else s
    s.exportBrep(job["out"])
    bb = s.BoundingBox()
    emit(ok=True, volume_mm3=round(s.Volume(), 2), faces=len(s.Faces()),
         box_mm=[round(v, 2) for v in (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)])
except Exception as e:  # noqa: BLE001
    emit(ok=False, error=str(e))
