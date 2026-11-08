"""Run model-written CadQuery code for one part in a separate process and keep the solid it makes.

What the code sees: `cq` (CadQuery), `math`, `np` (numpy), `geom` (rav_cad.parametric.geom helpers), `old` (the
part's current solid) and `parts` (the other parts by name, read-only reference). It must set `result` to one valid
solid. Imports outside that list, `open`/`exec`/`eval`, and sockets are refused, and the process is killed after
`timeout_s`. Errors come back as text the model can act on.

This guards against mistakes, not attacks: it is fine for our own model on our own machine, but it is not a security
boundary (CadQuery itself can still reach the file system). Never run untrusted people's code with it.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

RUNNER = pathlib.Path(__file__).with_name("_runner.py")
TIMEOUT_S = 60.0
MARK = "@@RESULT@@"


class SandboxError(Exception):
    """The part code failed; the message is meant for the model."""


def _paths() -> list[str]:
    """Where our packages live, passed explicitly (the child runs isolated, without PYTHONPATH)."""
    import importlib.util
    out = []
    for mod in ("rav_cad", "rav_contracts", "rav_interface"):
        spec = importlib.util.find_spec(mod)
        if spec and spec.origin:
            out.append(str(pathlib.Path(spec.origin).resolve().parents[1]))
    return list(dict.fromkeys(out))


def run_part_code(code_file: pathlib.Path, old: pathlib.Path | None, parts: dict[str, pathlib.Path],
                  out: pathlib.Path, timeout_s: float = TIMEOUT_S) -> dict:
    """Run the code; on success the solid is at `out` and the summary (volume, faces, box) is returned."""
    job = {"code": str(code_file), "old": str(old) if old else None, "out": str(out),
           "parts": {k: str(v) for k, v in parts.items()}, "paths": _paths()}
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy") and k not in ("PYTHONPATH",)}
    env.update({"http_proxy": "http://0.0.0.0:9", "https_proxy": "http://0.0.0.0:9", "no_proxy": ""})
    try:
        p = subprocess.run([sys.executable, "-I", str(RUNNER), json.dumps(job)], capture_output=True, text=True,
                           timeout=timeout_s, env=env, cwd=str(out.parent))
    except subprocess.TimeoutExpired:
        raise SandboxError(f"the code ran longer than {timeout_s:.0f} s and was stopped; simplify it (fewer "
                           "booleans, no loops over many faces)") from None
    line = next((ln[len(MARK):] for ln in reversed(p.stdout.splitlines()) if ln.startswith(MARK)), None)
    if line is None:
        tail = (p.stderr or p.stdout).strip().splitlines()[-8:]
        raise SandboxError("the code crashed the CAD kernel" + (": " + " | ".join(tail) if tail else ""))
    res = json.loads(line)
    if not res.pop("ok"):
        msg = res["error"] + (("\n" + res["traceback"]) if res.get("traceback") else "")
        raise SandboxError(msg)
    if p.stdout.split(MARK)[0].strip():
        res["printed"] = p.stdout.split(MARK)[0].strip()[-2000:]
    return res
