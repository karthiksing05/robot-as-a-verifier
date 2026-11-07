"""The Onshape client, offline: .env loading, request signing, units, retries, redirects, translation polling."""
import base64
import hashlib
import hmac
import json

import pytest

httpx = pytest.importorskip("httpx2")

from rav_cad.onshape import client as oc  # noqa: E402
from rav_cad.onshape.client import (DocRef, FixtureRecorder, OnshapeClient, OnshapeError,  # noqa: E402
                                    TranslationFailed, decode_fs_value, parse_document_url, replay_transport)
from rav_cad.onshape.settings import (OnshapeSettings, OnshapeSettingsError, find_repo_root,  # noqa: E402
                                      load_settings, parse_env_file)

AK, SK = "test-access-key-AAAA", "test-secret-key-BBBB"
DID, WID, VID, EID = "a" * 24, "b" * 24, "c" * 24, "d" * 24
REF = DocRef(DID, "w", WID, EID)


def settings(**kw):
    return OnshapeSettings(access_key=AK, secret_key=SK, **kw)


def make_client(handler, **kw):
    sleeps = []
    c = OnshapeClient(settings(), transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    c.sleeps = sleeps
    return c


# --- .env loading ---------------------------------------------------------------------------------------------

def write_env(tmp_path, text):
    p = tmp_path / ".env"
    p.write_text(text)
    return p


def test_env_file_values_are_read(tmp_path):
    env = write_env(tmp_path, "# comment\nONSHAPE_ACCESS_KEY=fileak\nexport ONSHAPE_SECRET_KEY='filesk'\n"
                              "ONSHAPE_BASE_URL=\nONSHAPE_DEV_DOCUMENT_URL=\"https://cad.onshape.com/documents/x\"\n")
    s = load_settings(env, environ={})
    assert (s.access_key, s.secret_key) == ("fileak", "filesk")
    assert s.base_url == "https://cad.onshape.com"
    assert s.dev_document_url == "https://cad.onshape.com/documents/x"


def test_real_env_vars_win_over_file(tmp_path):
    env = write_env(tmp_path, "ONSHAPE_ACCESS_KEY=fileak\nONSHAPE_SECRET_KEY=filesk\nONSHAPE_BASE_URL=https://f.x\n")
    s = load_settings(env, environ={"ONSHAPE_ACCESS_KEY": "envak", "ONSHAPE_BASE_URL": "https://e.x/"})
    assert s.access_key == "envak" and s.secret_key == "filesk"
    assert s.base_url == "https://e.x"


def test_empty_env_var_falls_back_to_file(tmp_path):
    env = write_env(tmp_path, "ONSHAPE_ACCESS_KEY=fileak\nONSHAPE_SECRET_KEY=filesk\n")
    assert load_settings(env, environ={"ONSHAPE_ACCESS_KEY": ""}).access_key == "fileak"


def test_missing_keys_give_a_clear_error(tmp_path):
    env = write_env(tmp_path, "ONSHAPE_ACCESS_KEY=\nONSHAPE_SECRET_KEY=\n")
    with pytest.raises(OnshapeSettingsError) as e:
        load_settings(env, environ={})
    msg = str(e.value)
    assert "ONSHAPE_ACCESS_KEY" in msg and "ONSHAPE_SECRET_KEY" in msg and ".env" in msg


def test_missing_env_file_is_an_error_not_a_crash(tmp_path):
    with pytest.raises(OnshapeSettingsError):
        load_settings(tmp_path / "nope.env", environ={})
    assert not load_settings(tmp_path / "nope.env", environ={}, require_keys=False).has_keys


def test_keys_never_appear_in_repr(tmp_path):
    env = write_env(tmp_path, f"ONSHAPE_ACCESS_KEY={AK}\nONSHAPE_SECRET_KEY={SK}\n")
    text = repr(load_settings(env, environ={}))
    assert AK not in text and SK not in text


def test_repo_root_is_found_from_the_package():
    root = find_repo_root()
    assert root is not None and (root / ".env.example").exists()


def test_parse_env_file_strips_inline_comments(tmp_path):
    env = write_env(tmp_path, "A=1 # note\nB='x # y'\nnot a pair\n")
    assert parse_env_file(env) == {"A": "1", "B": "x # y"}


# --- signing --------------------------------------------------------------------------------------------------

def test_signature_matches_onshape_recipe():
    url = httpx.URL("https://cad.onshape.com/api/v12/partstudios/d/x/w/y/e/z/features?rollbackBarIndex=-1")
    date, nonce = "Sat, 07 Nov 2026 12:00:00 GMT", "N" * 25
    h = oc.sign_headers(AK, SK, "GET", url, "application/json", nonce=nonce, date=date)
    to_sign = (f"GET\n{nonce}\n{date}\napplication/json\n/api/v12/partstudios/d/x/w/y/e/z/features\n"
               "rollbackBarIndex=-1\n").lower()
    expected = base64.b64encode(hmac.new(SK.encode(), to_sign.encode(), hashlib.sha256).digest()).decode()
    assert h["Authorization"] == f"On {AK}:HmacSHA256:{expected}"
    assert h["Date"] == date and h["On-Nonce"] == nonce and h["Content-Type"] == "application/json"


def test_requests_carry_signed_headers_and_fresh_nonces():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[])

    c = make_client(handler)
    c.list_versions(DID)
    c.list_versions(DID)
    a, b = seen
    assert a.url.path == f"/api/v12/documents/d/{DID}/versions"
    assert a.headers["authorization"].startswith(f"On {AK}:HmacSHA256:")
    assert len(a.headers["on-nonce"]) >= 16 and a.headers["on-nonce"] != b.headers["on-nonce"]
    recomputed = oc.sign_headers(AK, SK, "GET", a.url, "application/json",
                                 nonce=a.headers["on-nonce"], date=a.headers["date"])
    assert recomputed["Authorization"] == a.headers["authorization"]


def test_redirects_are_re_signed_for_the_new_url():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "cad.onshape.com":
            return httpx.Response(307, headers={"location": "https://files.onshape.com/dl/abc?sig=1"})
        return httpx.Response(200, content=b"solid stl")

    c = make_client(handler)
    assert c.export_stl(REF, part_id="JHD") == b"solid stl"
    first, second = seen
    assert dict(first.url.params)["units"] == "millimeter" and dict(first.url.params)["partIds"] == "JHD"
    expected = oc.sign_headers(AK, SK, "GET", second.url, "application/json",
                               nonce=second.headers["on-nonce"], date=second.headers["date"])
    assert second.headers["authorization"] == expected["Authorization"]
    assert second.headers["authorization"] != first.headers["authorization"]


# --- retries and errors ---------------------------------------------------------------------------------------

def test_429_and_5xx_are_retried_with_backoff():
    statuses = iter([429, 503, 200])

    def handler(request):
        s = next(statuses)
        return httpx.Response(s, headers={"retry-after": "3"} if s == 429 else {}, json={"ok": s})

    c = make_client(handler, backoff=0.5)
    assert c.get_features(REF) == {"ok": 200}
    assert c.sleeps == [3.0, 1.0]  # Retry-After honoured, then 0.5 * 2**1


def test_retries_give_up_and_raise():
    c = make_client(lambda r: httpx.Response(502, text="bad gateway"), max_retries=2)
    with pytest.raises(OnshapeError) as e:
        c.list_parts(REF)
    assert e.value.status == 502 and len(c.sleeps) == 2


def test_client_errors_are_not_retried():
    calls = []
    c = make_client(lambda r: calls.append(r) or httpx.Response(404, json={"message": "nope"}))
    with pytest.raises(OnshapeError):
        c.list_parts(REF)
    assert len(calls) == 1 and c.sleeps == []


def test_writes_need_a_workspace():
    c = make_client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        c.add_feature(DocRef(DID, "v", VID, EID), {"btType": "BTMFeature-134"})


# --- units ----------------------------------------------------------------------------------------------------

def test_metres_and_mm():
    assert oc.m_to_mm(0.0125) == pytest.approx(12.5)
    assert oc.mm_to_m(12.5) == pytest.approx(0.0125)
    assert oc.mm_expr(0.4) == "0.4 mm"


def test_featurescript_values_come_back_in_mm():
    result = {"btType": "BTFSValueMap-1076", "value": [
        {"key": {"btType": "BTFSValueString-1422", "value": "distance"},
         "value": {"btType": "BTFSValueWithUnits-1817", "value": 0.0004,
                   "unitToPower": [{"key": "METER", "value": 1}]}},
        {"key": {"btType": "BTFSValueString-1422", "value": "area"},
         "value": {"btType": "BTFSValueWithUnits-1817", "value": 2e-6,
                   "unitToPower": [{"key": "METER", "value": 2}]}},
        {"key": {"btType": "BTFSValueString-1422", "value": "angle"},
         "value": {"btType": "BTFSValueWithUnits-1817", "value": 1.5,
                   "unitToPower": [{"key": "RADIAN", "value": 1}]}},
        {"key": {"btType": "BTFSValueString-1422", "value": "bodies"},
         "value": {"btType": "BTFSValueNumber-772", "value": 3}},
        {"key": {"btType": "BTFSValueString-1422", "value": "none"},
         "value": {"btType": "BTFSValueUndefined-2003"}},
    ]}
    v = decode_fs_value(result)
    assert v["distance"] == pytest.approx(0.4)
    assert v["area"] == pytest.approx(2.0)
    assert v["angle"] == {"value": 1.5, "units": {"RADIAN": 1}}
    assert v["bodies"] == 3 and v["none"] is None


def test_shaded_view_pixel_size_is_sent_in_metres():
    png = b"\x89PNG\r\n\x1a\nfake"
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"images": [base64.b64encode(png).decode()]})

    assert make_client(handler).shaded_view(REF, pixel_size_mm=2.0) == png
    assert float(dict(seen[0].url.params)["pixelSize"]) == pytest.approx(0.002)


def test_parse_document_url():
    ref = parse_document_url(f"https://cad.onshape.com/documents/{DID}/w/{WID}/e/{EID}?renderMode=0")
    assert ref == REF and ref.path == f"d/{DID}/w/{WID}/e/{EID}"
    with pytest.raises(ValueError):
        parse_document_url("https://example.com/nothing")


# --- translations ---------------------------------------------------------------------------------------------

def translation_handler(states, result=b"ISO-10303-21;\n..."):
    states = iter(states)
    seen = []

    def handler(request):
        seen.append(request)
        p = request.url.path
        if request.method == "POST" and p.endswith("/translations"):
            return httpx.Response(200, json={"id": "T1", "requestState": "ACTIVE"})
        if p.endswith("/translations/T1"):
            state = next(states)
            body = {"id": "T1", "requestState": state, "documentId": DID}
            if state == "DONE":
                body["resultExternalDataIds"] = ["F1"]
            if state == "FAILED":
                body["failureReason"] = "bad geometry"
            return httpx.Response(200, json=body)
        if p.endswith(f"/documents/d/{DID}/externaldata/F1"):
            return httpx.Response(200, content=result, headers={"content-type": "application/octet-stream"})
        return httpx.Response(404)

    return handler, seen


def test_step_export_starts_polls_and_downloads():
    handler, seen = translation_handler(["ACTIVE", "ACTIVE", "DONE"])
    c = make_client(handler)
    assert c.export_step(REF, interval=1.5).startswith(b"ISO-10303-21")
    start = seen[0]
    assert start.url.path == f"/api/v12/partstudios/{REF.path}/translations"
    assert json.loads(start.content) == {"formatName": "STEP", "storeInDocument": False}
    assert c.sleeps == [1.5, 1.5]
    assert seen[-1].headers["accept"] == "application/octet-stream"


def test_assembly_step_export_uses_the_assembly_endpoint():
    handler, seen = translation_handler(["DONE"])
    make_client(handler).export_step(REF, kind="assembly")
    assert seen[0].url.path == f"/api/v12/assemblies/{REF.path}/translations"


def test_failed_translation_raises_with_reason():
    handler, _ = translation_handler(["ACTIVE", "FAILED"])
    with pytest.raises(TranslationFailed, match="bad geometry"):
        make_client(handler).export_step(REF)


def test_translation_times_out():
    handler, _ = translation_handler(["ACTIVE"] * 100)
    now = [0.0]
    c = OnshapeClient(settings(), transport=httpx.MockTransport(handler),
                      sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    with pytest.raises(TranslationFailed, match="still ACTIVE"):
        c.export_step(REF, timeout=10, interval=2)


# --- features -------------------------------------------------------------------------------------------------

def test_update_feature_sends_ids_and_microversion():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"feature": {"featureId": "F9"}, "featureState": {"featureStatus": "OK"}})

    c = make_client(handler)
    c.update_feature(REF, "F9", {"btType": "BTMFeature-134", "featureType": "extrude", "name": "Lid"},
                     serialization_version="1.2.3", source_microversion="MV1")
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith(f"/partstudios/{REF.path}/features/featureid/F9")
    assert body["btType"] == "BTFeatureDefinitionCall-1406"
    assert body["feature"]["featureId"] == "F9" and body["feature"]["name"] == "Lid"
    assert body["serializationVersion"] == "1.2.3" and body["sourceMicroversion"] == "MV1"


# --- recording ------------------------------------------------------------------------------------------------

def test_recorder_strips_auth_and_replays(tmp_path):
    rec = FixtureRecorder(tmp_path, redact=[AK, SK])

    def handler(request):
        # a hostile echo of the key must still not reach the fixture
        return httpx.Response(200, json={"versions": [], "echo": AK},
                              headers={"set-cookie": "s=1", "content-type": "application/json"})

    c = OnshapeClient(settings(), transport=httpx.MockTransport(handler), recorder=rec)
    c.list_versions(DID)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and "list_versions" in files[0].name
    text = files[0].read_text()
    assert AK not in text and SK not in text and "HmacSHA256" not in text and "set-cookie" not in text.lower()
    assert "On-Nonce".lower() not in text.lower()

    replayed = OnshapeClient(settings(), transport=replay_transport(tmp_path))
    assert replayed.list_versions(DID) == {"versions": [], "echo": "<redacted>"}


def test_decode_fs_value_reads_the_live_apis_qualified_type_names():
    """Recorded from the R5 spike on Nov 7: the live API qualifies every BTFSValue type with its Java package."""
    q = "com.belmonttech.serialize.fsvalue."
    live = {"btType": q + "BTFSValueMap", "typeTag": "", "value": [
        {"btType": "BTFSValueMapEntry-2077",
         "key": {"btType": q + "BTFSValueString", "typeTag": "", "value": "bodies"},
         "value": {"btType": q + "BTFSValueNumber", "typeTag": "", "value": 2.0}},
        {"btType": "BTFSValueMapEntry-2077",
         "key": {"btType": q + "BTFSValueString", "typeTag": "", "value": "distance"},
         "value": {"btType": q + "BTFSValueWithUnits", "typeTag": "", "value": 0.009999999999999997,
                   "unitToPower": {"METER": 1}}}]}
    assert decode_fs_value(live) == {"bodies": 2.0, "distance": pytest.approx(10.0)}
