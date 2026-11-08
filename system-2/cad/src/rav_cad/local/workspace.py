"""A local CAD workspace: the product's base parts plus the analyst's replacement parts, in one folder.

    <root>/meta.json        product name, part names -> file stems
    <root>/base/<stem>.brep each base part, in the assembly frame
    <root>/overrides/       <stem>.py (the model's code) and <stem>.brep (the solid it made)
    <root>/edits.jsonl      every write and reset, in order

`state()` is a hash of the overrides: it plays the role of Onshape's microversion, so what was checked is what gets
approved. One workspace per finding, like one Onshape branch per finding.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import tempfile

import cadquery as cq

from .sandbox import TIMEOUT_S, SandboxError, run_part_code


def _stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:40] + "_" + hashlib.sha1(name.encode()).hexdigest()[:6]


class Workspace:
    def __init__(self, root: str | pathlib.Path):
        self.root = pathlib.Path(root)
        self.meta = json.loads((self.root / "meta.json").read_text())
        self.stems: dict[str, str] = self.meta["parts"]
        self._base: dict[str, cq.Shape] = {}
        self._cache: tuple[str, dict[str, cq.Shape]] | None = None

    @classmethod
    def create(cls, root: str | pathlib.Path, base: dict[str, cq.Shape], name: str = "product") -> "Workspace":
        root = pathlib.Path(root)
        (root / "base").mkdir(parents=True, exist_ok=True)
        (root / "overrides").mkdir(exist_ok=True)
        stems = {p: _stem(p) for p in base}
        for p, s in base.items():
            s.exportBrep(str(root / "base" / f"{stems[p]}.brep"))
        (root / "meta.json").write_text(json.dumps({"name": name, "parts": stems}, indent=1))
        (root / "edits.jsonl").touch()
        ws = cls(root)
        ws._base = dict(base)
        return ws

    # -- reading -------------------------------------------------------------------------------------------------
    def _file(self, part: str, kind: str) -> pathlib.Path:
        return self.root / ("base" if kind == "base" else "overrides") / f"{self.stems[part]}.{'py' if kind == 'code' else 'brep'}"

    def _need(self, part: str) -> None:
        if part not in self.stems:
            raise KeyError(f"no part {part!r}; parts are: {sorted(self.stems)}")

    def base_parts(self) -> dict[str, cq.Shape]:
        for p in self.stems:
            if p not in self._base:
                self._base[p] = cq.Shape.importBrep(str(self._file(p, "base")))
        return dict(self._base)

    def overridden(self) -> list[str]:
        return [p for p in self.stems if self._file(p, "override").exists()]

    def code(self, part: str) -> str | None:
        self._need(part)
        f = self._file(part, "code")
        return f.read_text() if f.exists() and self._file(part, "override").exists() else None

    def state(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.overridden()):
            h.update(p.encode() + b"\0" + self._file(p, "override").read_bytes())
        return h.hexdigest()[:16]

    def parts(self) -> dict[str, cq.Shape]:
        """The product as it stands: base parts with each override in place (cached per state)."""
        st = self.state()
        if self._cache and self._cache[0] == st:
            return dict(self._cache[1])
        out = self.base_parts()
        for p in self.overridden():
            out[p] = cq.Shape.importBrep(str(self._file(p, "override")))
        self._cache = (st, out)
        return dict(out)

    def part_file(self, part: str) -> pathlib.Path:
        self._need(part)
        f = self._file(part, "override")
        return f if f.exists() else self._file(part, "base")

    # -- writing -------------------------------------------------------------------------------------------------
    def _log(self, **row) -> None:
        row["at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with open(self.root / "edits.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def write_part(self, part: str, code: str, timeout_s: float = TIMEOUT_S) -> dict:
        """Run `code` to make a new solid for `part`. On failure nothing changes and SandboxError says why."""
        self._need(part)
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            tmp = pathlib.Path(tmp)
            code_file = tmp / "part_code.py"
            code_file.write_text(code)
            out = tmp / "result.brep"
            others = {p: self.part_file(p) for p in self.stems if p != part}
            try:
                res = run_part_code(code_file, self.part_file(part), others, out, timeout_s=timeout_s)
            except SandboxError as e:
                self._log(op="write_part", part=part, ok=False, error=str(e)[:500])
                raise
            shutil.move(str(code_file), self._file(part, "code"))
            shutil.move(str(out), self._file(part, "override"))
        self._log(op="write_part", part=part, ok=True, **{k: res[k] for k in ("volume_mm3", "faces", "box_mm")})
        return res

    def reset_part(self, part: str) -> bool:
        self._need(part)
        had = self._file(part, "override").exists()
        for kind in ("override", "code"):
            self._file(part, kind).unlink(missing_ok=True)
        self._log(op="reset_part", part=part, ok=True)
        return had
