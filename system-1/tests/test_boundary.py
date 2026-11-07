"""Keep System 1 standing on its own: nothing from System 2, and no LLM. And keep the pipeline (core/) and the drivers
(hardware/) off the sim, so the real arm runs without it."""
import ast
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANNED = re.compile(r"^\s*(?:from|import)\s+(rav_contracts|rav_harness|rav_cad|anthropic|openai)\b", re.M)


def test_system_1_imports_nothing_from_system_2_and_no_llm():
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts:
            continue
        assert not BANNED.search(path.read_text(encoding="utf-8")), f"{path} crosses into System 2 or calls an LLM"


def test_the_interface_stays_light():
    deps = tomllib.loads((ROOT / "interface/pyproject.toml").read_text())["project"]["dependencies"]
    assert [d.split(">")[0] for d in deps] == ["pydantic"]


def test_flat_modules_stay_independent():
    for folder in ("core", "sim", "hardware"):
        for path in (ROOT / folder).rglob("*.py"):
            assert "rav_" not in path.read_text(encoding="utf-8"), f"{path} should not import the server or the interface"


def _imports(path, anywhere):
    """The modules a file imports at its top, or with anywhere, also inside its functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree) if anywhere else tree.body:
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_core_and_hardware_dont_need_the_sim():
    """core/ imports nothing from sim/ or hardware/, not even inside a function. hardware/ imports nothing from sim/ at
    its top (real_cameras imports vision inside a function, for the dropped iPhone)."""
    sim, hardware = ({p.stem for p in (ROOT / d).glob("*.py")} for d in ("sim", "hardware"))
    for folder, banned, anywhere in (("core", sim | hardware, True), ("hardware", sim, False)):
        for path in (ROOT / folder).glob("*.py"):
            found = _imports(path, anywhere) & banned
            assert not found, f"{folder}/{path.name} imports {found}"


def test_sim_requirements_match_the_extra():
    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["sim"]
    lines = [line.strip() for line in (ROOT / "sim/requirements.txt").read_text().splitlines() if line.strip()]
    assert sorted(extra) == sorted(lines)


def test_arm_fits_its_interface():
    from rav_arm import LeRobotArm
    from rav_arm.ports import ArmBackend
    assert isinstance(LeRobotArm("port"), ArmBackend)
