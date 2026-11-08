"""LocalCadBackend on our parametric box: the analyst's own CadQuery code replaces a part, the generic checks judge
it, and apply writes the new revision. Offline."""
import json
import pathlib

import pytest

cq = pytest.importorskip("cadquery")
yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.cad

from rav_cad.generic import bench  # noqa: E402
from rav_cad.local import LocalCadBackend, faces_of  # noqa: E402
from rav_cad.local.backend import parametric_sources  # noqa: E402
from rav_cad.parametric.build import build  # noqa: E402
from rav_cad.parametric.render import render_parts  # noqa: E402
from rav_cad.parametric.spec import Spec  # noqa: E402
from rav_contracts import CADPatch  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Widen both of button_2's bores by 0.25 mm over their own length (Rev A has 0.15 mm, the rules need 0.3).
WIDEN = '''
ax = cq.Vector(0, 0.7071068, -0.7071068)
o = cq.Vector(80.0, 24.95, 155.05)
result = old
for f in old.Faces():
    if f.geomType() != "CYLINDER":
        continue
    r = f._geomAdaptor().Cylinder().Radius()
    if min(abs(r - 5.15), abs(r - 3.15)) > 0.01:
        continue
    ts = [(v.Center() - o).dot(ax) for v in f.Vertices()]
    result = result.cut(cq.Solid.makeCylinder(r + 0.25, max(ts) - min(ts) + 0.02, o + ax * (min(ts) - 0.01), ax))
'''


@pytest.fixture(scope="module")
def built():
    return build(Spec.load(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml"))


@pytest.fixture
def backend(built, tmp_path):
    tags = tmp_path / "tags.yaml"
    tags.write_text(yaml.safe_dump(bench.tags_dict(built)))
    return LocalCadBackend(tags, bench.parts(built), out_dir=tmp_path / "out", product="appliance",
                           sources=parametric_sources(built))


def patch_for(backend, ws, **kw):
    return CADPatch(file=backend.url(ws), revision_from="A", revision_to="B", changes=[], backend="local",
                    source=backend.source(ws, backend.microversion(ws)), **kw)


def test_a_new_bore_passes_and_applies_as_rev_b(backend):
    ws = backend.open_branch("fix button_2")
    assert backend.check_branch(ws).reasons == ["fix changes something: no part differs from the tested revision"]
    backend.branch(ws).write_part("button_2 insert", WIDEN)
    quick = backend.check_branch(ws, quick=True)
    assert quick.changed == ["button_2 insert"] and quick.target == "button_2" and quick.reasons == []
    patch = patch_for(backend, ws)
    assert patch.source.document_id == "local:appliance" and backend.check(patch) == []
    with pytest.raises(ValueError, match="approves"):
        backend.apply(patch)
    out = pathlib.Path(backend.apply(patch.model_copy(update={"approved_by": "bayan"})))
    assert {p.name for p in out.iterdir()} == {"assembly.step", "button_2 insert.stl", "button_2 insert.py",
                                              "edits.jsonl", "patch_result.json"}
    result = json.loads((out / "patch_result.json").read_text())
    assert result["changed"] == ["button_2 insert"] and result["state"] == patch.source.microversion_id


def test_an_edit_after_the_check_is_refused(backend):
    ws = backend.open_branch("fix button_2")
    backend.branch(ws).write_part("button_2 insert", WIDEN)
    patch = patch_for(backend, ws, approved_by="bayan")
    backend.branch(ws).write_part("button_2 insert", "result = old.translate((0, 0, 0.01))")
    assert backend.check(patch) == ["the workspace has changed since this patch was made; check it again and resubmit"]


@pytest.mark.parametrize("part, code, reason", [
    ("button_2 insert", "result = old.translate((40, 0, 0))", "parts don't overlap at rest: button_2 insert / button_3"),
    ("shell", "result = old.translate((0, 0, 0.5))", "fix leaves the body alone"),
])
def test_bad_geometry_fails_the_checks(backend, part, code, reason):
    ws = backend.open_branch("bad")
    backend.branch(ws).write_part(part, code)
    assert any(r.startswith(reason) for r in backend.check_branch(ws, quick=True).reasons)


def test_describe_faces_sources_and_render(backend, tmp_path):
    text = backend.describe("button_2")
    assert "may reprint button_2 insert" in text and '"radius": 5.15' in text and "0.150 mm" in text
    faces = faces_of(backend.before()["button_2 insert"])
    assert faces[0]["id"] == "f1" and {"plane", "cylinder"} <= {f["kind"] for f in faces}
    assert "def build" in backend.sources["button_2 insert"]
    png = render_parts(backend.before(), tmp_path / "r.png", highlight={"button_2 insert"}, fixed={"shell", "base"})
    assert png.read_bytes()[:4] == b"\x89PNG"
