"""OnshapeBackend against a fake Onshape whose geometry is our CadQuery appliance. No network, no keys."""
import pathlib

import pytest

pytest.importorskip("cadquery")
yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.cad

from onshape_fake import DID, VID, WID, FakeOnshape, write_tags  # noqa: E402
from rav_cad.onshape.backend import OnshapeBackend  # noqa: E402
from rav_contracts import CADPatch, CadSource  # noqa: E402


@pytest.fixture(scope="module")
def tag_file(tmp_path_factory):
    return write_tags(tmp_path_factory.mktemp("tags") / "onshape.yaml", variables=False)


@pytest.fixture
def onshape(tag_file, tmp_path):
    fake = FakeOnshape()
    return fake, OnshapeBackend(tag_file, client=fake, out_dir=tmp_path / "out")


def patch_for(backend, ws, **kw):
    return CADPatch(file="onshape", revision_from="A", revision_to="B", changes=[], backend="onshape",
                    source=backend.source(ws, backend.microversion(ws)), **kw)


def test_a_bar_handle_on_a_branch_passes_and_becomes_rev_b(onshape):
    fake, backend = onshape
    ws = backend.open_branch("fix door")
    fake.edit(ws, {"features.door.handle_style": "bar"})
    patch = patch_for(backend, ws, approved_by="bayan")
    assert backend.check(patch) == []
    out = pathlib.Path(backend.apply(patch))
    assert ("create_version", "Rev B") in fake.calls
    assert sorted(p.name for p in out.glob("*.stl")) == ["door insert.stl"]       # only the handle reprints
    assert fake.versions[VID] == {}                                                # the tested version is untouched


def test_the_tested_version_is_exported_once_and_reused(onshape):
    fake, backend = onshape
    for _ in range(2):
        ws = backend.open_branch("try")
        fake.edit(ws, {"features.button_2.clearance": 0.40})
        assert backend.check(patch_for(backend, ws)) == []
    assert sum(1 for c in fake.calls if c[:2] == ("export_step", "v")) == 1


def test_bad_branches_are_refused_with_reasons(onshape):
    fake, backend = onshape
    ws = backend.open_branch("latch")
    fake.edit(ws, {"features.door.handle_style": "push_latch"})
    assert any("hooked fingertip" in r for r in backend.check(patch_for(backend, ws)))
    ws = backend.open_branch("shell")
    fake.edit(ws, {"shell.wall": 4.0})
    assert any("leaves the body alone" in r for r in backend.check(patch_for(backend, ws)))


def test_a_branch_edited_after_its_check_is_refused(onshape):
    fake, backend = onshape
    ws = backend.open_branch("fix")
    fake.edit(ws, {"features.button_2.clearance": 0.40})
    patch = patch_for(backend, ws, approved_by="bayan")
    fake.edit(ws, {"features.button_2.clearance": 0.30})          # someone keeps editing after it was checked
    assert any("changed since this patch was made" in r for r in backend.check(patch))
    with pytest.raises(ValueError, match="changed since"):
        backend.apply(patch)


def test_apply_needs_an_approver_and_a_branch(onshape):
    fake, backend = onshape
    ws = backend.open_branch("fix")
    fake.edit(ws, {"features.button_2.clearance": 0.40})
    with pytest.raises(ValueError, match="approves"):
        backend.apply(patch_for(backend, ws))
    plain = CADPatch(file="x", revision_from="A", revision_to="B", changes=[])
    assert "points at its branch" in backend.check(plain)[0]
    assert not any(c[0] == "create_version" for c in fake.calls)


def test_rules_and_params_describe_the_product(onshape):
    _, backend = onshape
    assert "12 mm fingertip" in backend.rules() and "hook" in backend.rules()
    params = backend.read_params()
    assert params["backend"] == "onshape" and params["controls.door"]["skill"] == "pull"


def test_a_tag_file_without_its_document_is_rejected(tmp_path):
    p = tmp_path / "onshape.yaml"
    p.write_text(yaml.safe_dump({"controls": {}, "source": {"document": "<paste the link>"}}))
    with pytest.raises(ValueError, match="source.document"):
        OnshapeBackend(p, client=FakeOnshape())


def test_cad_source_round_trips():
    s = CadSource(document_id=DID, workspace_id=WID, microversion_id="m1", base_version_id=VID)
    assert CADPatch(file="x", revision_from="A", revision_to="B", changes=[], source=s).source.microversion_id == "m1"
