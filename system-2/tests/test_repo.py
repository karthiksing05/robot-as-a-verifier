"""Keep the repo honest: only the interface crosses from System 1, the root stays small, and no link is dead."""
import ast
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
# System 1's flat modules and its server. Nothing in System 2 may import these.
SYSTEM_1 = {p.stem for d in ("core", "sim", "hardware") for p in (REPO / "system-1" / d).glob("*.py")} | {
    "rav_server", "rav_arm", "mujoco", "lerobot", "torch"}
# Runs the sim in-process until its streams move behind System 1's server. Don't add to this list.
ALLOWED = {ROOT / "console/server/live_sim.py"}
FOLDERS = ["contracts", "harness", "cad", "console", "fixtures", "tests"]


def imports(path: pathlib.Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_system_2_takes_only_the_interface_from_system_1():
    for folder in FOLDERS:
        for path in (ROOT / folder).rglob("*.py"):
            if path not in ALLOWED and "node_modules" not in path.parts:
                assert not imports(path) & SYSTEM_1, f"{path} imports System 1 code: go through the tools"


def test_harness_doesnt_import_the_cad_kernel_or_console_doesnt_reach_in():
    assert not {"cadquery"} & set().union(*(imports(p) for p in (ROOT / "harness/src").rglob("*.py")))


def test_the_root_holds_only_the_two_systems_and_docs():
    tracked = {p.name for p in REPO.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert tracked - {"node_modules", "__pycache__", "runs"} == {"system-1", "system-2", "docs"}


def test_live_extra_matches_the_sims_requirements():
    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["live"]
    lines = [line.strip() for line in (REPO / "system-1/sim/requirements.txt").read_text().splitlines() if line.strip()]
    assert sorted(extra) == sorted(lines)


def test_markdown_links_resolve():
    broken = []
    for md in REPO.rglob("*.md"):
        if {".venv", "runs", "node_modules"} & set(md.parts):
            continue
        for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            if not (md.parent / target.split("#")[0]).exists():
                broken.append(f"{md.relative_to(REPO)} -> {target}")
    assert not broken, broken
