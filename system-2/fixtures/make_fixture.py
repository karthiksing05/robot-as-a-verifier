"""Regenerate system-2/fixtures/sample_run from the mock backend: uv run python system-2/fixtures/make_fixture.py"""
import pathlib
import shutil
import tempfile

from rav_cad import ParamsBackend
from rav_contracts import TestRequest
from rav_harness.loop import fix_and_retest
from rav_harness.mock import mock_analyst, mock_model_run, mock_system_1

ROOT = pathlib.Path(__file__).resolve().parent
PARAMS = ROOT.parent / "subjects/appliance/cad/params.rev_a.json"


def main() -> None:
    out = ROOT / "sample_run"
    for generated in ("sample-revA", "sample-revB", "sample-trace"):  # sample-sim is a real recording: make_sim_sample.py
        shutil.rmtree(out / generated, ignore_errors=True)
    with tempfile.TemporaryDirectory() as tmp:
        request = TestRequest(request_id="sample", product="Test box (mock)", revision="A")
        fix_and_retest(mock_system_1, request, mock_analyst, ParamsBackend(shutil.copy(PARAMS, tmp)), log_root=str(out))
    mock_model_run("sample-trace", str(out))
    print(sorted(str(p.relative_to(ROOT)) for p in out.rglob("*") if p.is_file()))


if __name__ == "__main__":
    main()
