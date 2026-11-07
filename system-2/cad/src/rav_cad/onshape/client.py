"""A thin Onshape REST client: HMAC API-key auth, retries, metres<->mm at the edges, optional fixture recording.

Endpoint shapes follow Onshape's OpenAPI spec (https://cad.onshape.com/api/openapi, Nov 2026) and the guides at
onshape-public.github.io/docs. Onshape works in metres; this module takes and returns millimetres where it
converts (FeatureScript values, shaded-view pixel size, STL units). Feature expressions stay strings such as
"12 mm", which Onshape parses with their own units.
"""
from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import json
import pathlib
import re
import secrets
import string
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

try:  # the repo pins httpx2 (pulled in by mcp 2.x); plain httpx has the same API
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx  # type: ignore[no-redef]

from .settings import OnshapeSettings, load_settings

API_VERSION = "v12"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MM_PER_M = 1000.0
# Onshape names only top/bottom/front/back/left/right; this is its documented approximate isometric matrix.
ISOMETRIC = "0.612,0.612,0,0,-0.354,0.354,0.707,0,0.707,-0.707,0.707,0"
_NONCE_CHARS = string.ascii_letters + string.digits


# --- units --------------------------------------------------------------------------------------------------

def m_to_mm(value: float) -> float:
    return value * MM_PER_M


def mm_to_m(value: float) -> float:
    return value / MM_PER_M


def mm_expr(value_mm: float) -> str:
    """A feature-parameter expression for a length in mm, e.g. 12.5 -> "12.5 mm"."""
    return f"{value_mm:g} mm"


def decode_fs_value(v: Any) -> Any:
    """Turn a FeatureScript eval value (BTFSValue*) into plain Python; lengths come back in mm.

    A ValueWithUnits with unitToPower {METER: p} is multiplied by 1000**p (so areas are mm^2, volumes mm^3).
    Other units (radians, kilograms) are returned as {"value": ..., "units": {...}}.
    """
    if not isinstance(v, dict):
        return v
    # the live API sends fully qualified names ("com.belmonttech.serialize.fsvalue.BTFSValueString"); keep the class
    bt = (v.get("btType", "") or v.get("typeTag", "")).rsplit(".", 1)[-1]
    val = v.get("value")
    if "BTFSValueMap" in bt:
        return {decode_fs_value(e.get("key")): decode_fs_value(e.get("value")) for e in val or []}
    if "BTFSValueArray" in bt:
        return [decode_fs_value(e) for e in val or []]
    if "BTFSValueWithUnits" in bt:
        raw = v.get("unitToPower") or {}
        # the live API sends a map ({"METER": 1}); older docs show a list of {key, value}
        units = dict(raw) if isinstance(raw, dict) else {u["key"]: u["value"] for u in raw}
        if set(units) == {"METER"}:
            return val * MM_PER_M ** units["METER"]
        return {"value": val, "units": units}
    if "BTFSValueUndefined" in bt:
        return None
    if bt.startswith("BTFSValue"):
        return val
    if "result" in v and "btType" not in v:
        return decode_fs_value(v["result"])
    return v


# --- document references ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DocRef:
    """A document, a workspace/version/microversion of it and (optionally) an element."""
    did: str
    wvm: str  # "w", "v" or "m"
    wvmid: str
    eid: str | None = None

    def with_element(self, eid: str) -> "DocRef":
        return replace(self, eid=eid)

    def with_workspace(self, wid: str) -> "DocRef":
        return replace(self, wvm="w", wvmid=wid)

    @property
    def path(self) -> str:
        p = f"d/{self.did}/{self.wvm}/{self.wvmid}"
        return f"{p}/e/{self.eid}" if self.eid else p

    def need_element(self) -> str:
        if not self.eid:
            raise ValueError(f"{self} has no element id")
        return self.eid

    def need_workspace(self) -> str:
        if self.wvm != "w":
            raise ValueError(f"writes need a workspace, got {self.wvm}/{self.wvmid}")
        return self.wvmid


_URL_RE = re.compile(r"/documents/([0-9a-f]{24})/([wvm])/([0-9a-f]{24})(?:/e/([0-9a-f]{24}))?")


def parse_document_url(url: str) -> DocRef:
    """https://cad.onshape.com/documents/<did>/w/<wid>/e/<eid> -> DocRef."""
    m = _URL_RE.search(url)
    if not m:
        raise ValueError(f"not an Onshape document URL: {url!r}")
    return DocRef(m.group(1), m.group(2), m.group(3), m.group(4))


# --- errors, signing, recording -----------------------------------------------------------------------------

class OnshapeError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status, self.body = status, body


class TranslationFailed(OnshapeError):
    pass


def make_nonce(n: int = 25) -> str:
    return "".join(secrets.choice(_NONCE_CHARS) for _ in range(n))


def http_date(ts: float | None = None) -> str:
    return email.utils.formatdate(ts, usegmt=True)


def sign_headers(access_key: str, secret_key: str, method: str, url: httpx.URL, content_type: str,
                 nonce: str | None = None, date: str | None = None) -> dict[str, str]:
    """Onshape API-key headers: HMAC-SHA256 of method/nonce/date/content-type/path/query, lower-cased."""
    nonce = nonce or make_nonce()
    date = date or http_date()
    query = url.query.decode() if isinstance(url.query, bytes) else str(url.query)
    to_sign = f"{method}\n{nonce}\n{date}\n{content_type}\n{url.path}\n{query}\n".lower()
    digest = hmac.new(secret_key.encode(), to_sign.encode(), hashlib.sha256).digest()
    return {
        "Date": date,
        "On-Nonce": nonce,
        "Content-Type": content_type,
        "Authorization": f"On {access_key}:HmacSHA256:{base64.b64encode(digest).decode()}",
    }


_SECRET_HEADERS = {"authorization", "on-nonce", "cookie", "set-cookie", "date", "x-amz-security-token"}
_KEEP_RESPONSE_HEADERS = {"content-type", "content-length", "location", "retry-after"}
MAX_INLINE_BYTES = 64 * 1024


class FixtureRecorder:
    """Writes each request/response pair to `<dir>/<NNN>_<method>_<slug>.json`, without auth headers.

    Any string in `redact` (pass the key values) is replaced everywhere before writing, as a second guard.
    Binary bodies over MAX_INLINE_BYTES are stored as size + sha256 only.
    """

    def __init__(self, directory: pathlib.Path | str, redact: Iterable[str] = (), prefix: str = ""):
        self.dir = pathlib.Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._redact = [s for s in redact if s]
        self.prefix = prefix
        self.count = 0

    def _scrub(self, text: str) -> str:
        for s in self._redact:
            text = text.replace(s, "<redacted>")
        return text

    @staticmethod
    def _body(content: bytes, content_type: str) -> dict[str, Any]:
        if not content:
            return {}
        if "json" in content_type and "gltf" not in content_type:
            try:
                return {"json": json.loads(content)}
            except ValueError:
                pass
        if content_type.startswith("text/"):
            return {"text": content.decode(errors="replace")}
        out: dict[str, Any] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        if len(content) <= MAX_INLINE_BYTES:
            out["base64"] = base64.b64encode(content).decode()
        return out

    def record(self, request: httpx.Request, response: httpx.Response, label: str = "") -> pathlib.Path:
        self.count += 1
        url = request.url
        req_ct = request.headers.get("content-type", "")
        entry = {
            "label": label,
            "request": {
                "method": request.method,
                "path": url.path,
                "query": url.query.decode() if isinstance(url.query, bytes) else str(url.query),
                "headers": {k: v for k, v in request.headers.items()
                            if k.lower() in {"content-type", "accept"}},
                **self._body(request.content, req_ct),
            },
            "response": {
                "status": response.status_code,
                "headers": {k: v for k, v in response.headers.items()
                            if k.lower() in _KEEP_RESPONSE_HEADERS and k.lower() not in _SECRET_HEADERS},
                **self._body(response.content, response.headers.get("content-type", "")),
            },
        }
        slug = re.sub(r"[^a-z0-9]+", "_", (label or url.path.split("/api/")[-1]).lower()).strip("_")[:60]
        path = self.dir / f"{self.prefix}{self.count:03d}_{request.method.lower()}_{slug}.json"
        path.write_text(self._scrub(json.dumps(entry, indent=1, sort_keys=False)) + "\n")
        return path


def replay_transport(directory: pathlib.Path | str) -> httpx.MockTransport:
    """A transport answering from recorded fixtures, matched by method + path + query (first unused match)."""
    entries = [json.loads(p.read_text()) for p in sorted(pathlib.Path(directory).glob("*.json"))]
    used: set[int] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)
        for i, e in enumerate(entries):
            r = e["request"]
            if i not in used and r["method"] == request.method and r["path"] == request.url.path and r["query"] == q:
                used.add(i)
                resp = e["response"]
                if "json" in resp:
                    content = json.dumps(resp["json"]).encode()
                elif "base64" in resp:
                    content = base64.b64decode(resp["base64"])
                else:
                    content = resp.get("text", "").encode()
                return httpx.Response(resp["status"], headers=resp.get("headers", {}), content=content)
        return httpx.Response(404, json={"message": f"no fixture for {request.method} {request.url.path}?{q}"})

    return httpx.MockTransport(handler)


# --- the client ---------------------------------------------------------------------------------------------

MATE_FEATURE_TYPES = {"mate", "mateGroup", "mateConnector", "gearRelation", "rackAndPinionRelation",
                      "screwRelation", "linearRelation"}


class OnshapeClient:
    def __init__(self, settings: OnshapeSettings | None = None, *, transport: httpx.BaseTransport | None = None,
                 recorder: FixtureRecorder | None = None, api_version: str = API_VERSION, max_retries: int = 4,
                 backoff: float = 1.0, timeout: float = 60.0, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.settings = settings or load_settings()
        self.api_base = f"{self.settings.base_url}/api/{api_version}"
        self.recorder = recorder
        self.max_retries, self.backoff = max_retries, backoff
        self._sleep, self._clock = sleep, clock
        self._http = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OnshapeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport --

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any = None,
                accept: str = "application/json", label: str = "", max_redirects: int = 5) -> httpx.Response:
        """Sign, send, retry 429/5xx with backoff, follow redirects re-signing each hop; raise on >= 400."""
        url = httpx.URL(path if path.startswith("http") else f"{self.api_base}/{path.lstrip('/')}")
        if params:
            url = url.copy_merge_params({k: _qv(v) for k, v in params.items() if v is not None})
        content = json.dumps(json_body).encode() if json_body is not None else b""
        content_type = "application/json"
        for _hop in range(max_redirects + 1):
            response = self._send_with_retry(method, url, content, content_type, accept, label)
            if response.status_code in REDIRECT_STATUSES and "location" in response.headers:
                url = url.join(response.headers["location"])
                if response.status_code == 303:
                    method, content = "GET", b""
                continue
            if response.status_code >= 400:
                raise OnshapeError(f"{method} {url.path} -> {response.status_code}: {response.text[:500]}",
                                   status=response.status_code, body=response.text)
            return response
        raise OnshapeError(f"too many redirects for {method} {path}")

    def _send_with_retry(self, method: str, url: httpx.URL, content: bytes, content_type: str, accept: str,
                         label: str) -> httpx.Response:
        attempt = 0
        while True:
            headers = sign_headers(self.settings.access_key, self.settings.secret_key, method, url, content_type)
            headers["Accept"] = accept
            request = self._http.build_request(method, url, content=content or None, headers=headers)
            try:
                response = self._http.send(request)
            except httpx.TransportError:
                if attempt >= self.max_retries:
                    raise
                self._sleep(self.backoff * 2 ** attempt)
                attempt += 1
                continue
            response.read()
            if self.recorder:
                self.recorder.record(request, response, label)
            if response.status_code not in RETRY_STATUSES or attempt >= self.max_retries:
                return response
            self._sleep(_retry_after(response) or self.backoff * 2 ** attempt)
            attempt += 1

    def get_json(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw).json()

    def post_json(self, path: str, body: Any, **kw: Any) -> Any:
        r = self.request("POST", path, json_body=body, **kw)
        return r.json() if r.content else None

    # -- documents --

    def list_versions(self, did: str) -> list[dict]:
        return self.get_json(f"documents/d/{did}/versions", label="list_versions")

    def create_version(self, did: str, workspace_id: str, name: str, description: str = "") -> dict:
        return self.post_json(f"documents/d/{did}/versions",
                              {"documentId": did, "workspaceId": workspace_id, "name": name,
                               "description": description}, label="create_version")

    def list_workspaces(self, did: str) -> list[dict]:
        return self.get_json(f"documents/d/{did}/workspaces", label="list_workspaces")

    def create_branch(self, did: str, version_id: str, name: str, description: str = "") -> dict:
        """A new workspace (branch) starting at `version_id`. Returns the workspace info (its `id`)."""
        return self.post_json(f"documents/d/{did}/workspaces",
                              {"name": name, "description": description, "versionId": version_id},
                              label="create_branch")

    def list_elements(self, ref: DocRef, element_type: str | None = None) -> list[dict]:
        """Tabs of a document; element_type e.g. PARTSTUDIO, ASSEMBLY, VARIABLESTUDIO."""
        return self.get_json(f"documents/d/{ref.did}/{ref.wvm}/{ref.wvmid}/elements",
                             params={"elementType": element_type}, label="list_elements")

    # -- Part Studio --

    def get_features(self, ref: DocRef, **params: Any) -> dict:
        """The feature tree: `features`, `featureStates`, `serializationVersion`, `sourceMicroversion`, ..."""
        ref.need_element()
        return self.get_json(f"partstudios/{ref.path}/features", params=params or None, label="get_features")

    def _feature_call(self, feature: dict, serialization_version: str | None,
                      source_microversion: str | None) -> dict:
        body: dict[str, Any] = {"btType": "BTFeatureDefinitionCall-1406", "feature": feature}
        if serialization_version:
            body["serializationVersion"] = serialization_version
        if source_microversion:
            body["sourceMicroversion"] = source_microversion
        return body

    def add_feature(self, ref: DocRef, feature: dict, serialization_version: str | None = None,
                    source_microversion: str | None = None) -> dict:
        ref.need_workspace(), ref.need_element()
        return self.post_json(f"partstudios/{ref.path}/features",
                              self._feature_call(feature, serialization_version, source_microversion),
                              label="add_feature")

    def update_feature(self, ref: DocRef, feature_id: str, feature: dict,
                       serialization_version: str | None = None, source_microversion: str | None = None) -> dict:
        """Send the whole feature (featureType and name too, or Onshape may blank them)."""
        ref.need_workspace(), ref.need_element()
        feature = {**feature, "featureId": feature_id}
        return self.post_json(f"partstudios/{ref.path}/features/featureid/{feature_id}",
                              self._feature_call(feature, serialization_version, source_microversion),
                              label="update_feature")

    def delete_feature(self, ref: DocRef, feature_id: str) -> dict | None:
        ref.need_workspace(), ref.need_element()
        r = self.request("DELETE", f"partstudios/{ref.path}/features/featureid/{feature_id}",
                         label="delete_feature")
        return r.json() if r.content else None

    def eval_featurescript(self, ref: DocRef, script: str, queries: dict | None = None) -> dict:
        """Run a read-only FeatureScript function; `decode_fs_value(resp["result"])` gives Python in mm."""
        ref.need_element()
        body: dict[str, Any] = {"script": script}
        if queries:
            body["queries"] = queries
        return self.post_json(f"partstudios/{ref.path}/featurescript", body, label="eval_featurescript")

    def list_parts(self, ref: DocRef) -> list[dict]:
        ref.need_element()
        return self.get_json(f"parts/{ref.path}", label="list_parts")

    def shaded_view(self, ref: DocRef, view_matrix: str = ISOMETRIC, width: int = 800, height: int = 600,
                    pixel_size_mm: float = 0.0, edges: bool = True) -> bytes:
        """A PNG of the Part Studio. pixel_size_mm=0 lets Onshape fit the model to the image."""
        ref.need_element()
        info = self.get_json(f"partstudios/{ref.path}/shadedviews", label="shaded_view", params={
            "viewMatrix": view_matrix, "outputWidth": width, "outputHeight": height,
            "pixelSize": mm_to_m(pixel_size_mm), "edges": "show" if edges else "hide"})
        images = info.get("images") or []
        if not images:
            raise OnshapeError("shaded view returned no image")
        return base64.b64decode(images[0])

    # -- Variable Studio --

    def get_variables(self, ref: DocRef) -> list[dict]:
        ref.need_element()
        return self.get_json(f"variables/{ref.path}/variables", label="get_variables")

    def set_variables(self, ref: DocRef, variables: list[dict]) -> Any:
        """Each item: {"name", "type" (LENGTH/ANGLE/NUMBER/ANY), "expression", "description"?}."""
        ref.need_workspace(), ref.need_element()
        return self.post_json(f"variables/{ref.path}/variables", variables, label="set_variables")

    # -- Assembly --

    def assembly_definition(self, ref: DocRef, include_mate_features: bool = True,
                            include_mate_connectors: bool = False) -> dict:
        ref.need_element()
        return self.get_json(f"assemblies/{ref.path}", label="assembly_definition", params={
            "includeMateFeatures": include_mate_features, "includeMateConnectors": include_mate_connectors})

    def assembly_features(self, ref: DocRef) -> dict:
        ref.need_element()
        return self.get_json(f"assemblies/{ref.path}/features", label="assembly_features")

    def mate_features(self, ref: DocRef) -> list[dict]:
        """Mates and relations from the Assembly's feature list (each still holds its limit parameters)."""
        feats = self.assembly_features(ref).get("features", [])
        return [f for f in feats if f.get("featureType") in MATE_FEATURE_TYPES or "Mate" in f.get("btType", "")]

    # -- export --

    def start_translation(self, ref: DocRef, format_name: str = "STEP", kind: str = "partstudio",
                          **options: Any) -> dict:
        """Start an async translation of a Part Studio or Assembly; returns the request info (its `id`)."""
        if ref.wvm == "m":
            raise ValueError("translations need a workspace or version, not a microversion")
        prefix = {"partstudio": "partstudios", "assembly": "assemblies"}[kind]
        body = {"formatName": format_name, "storeInDocument": False, **options}
        return self.post_json(f"{prefix}/{ref.path}/translations", body, label=f"start_{format_name.lower()}")

    def get_translation(self, translation_id: str) -> dict:
        return self.get_json(f"translations/{translation_id}", label="get_translation")

    def wait_translation(self, translation_id: str, timeout: float = 300.0, interval: float = 2.0) -> dict:
        deadline = self._clock() + timeout
        while True:
            info = self.get_translation(translation_id)
            state = info.get("requestState")
            if state == "DONE":
                return info
            if state == "FAILED":
                raise TranslationFailed(f"translation {translation_id} failed: {info.get('failureReason')}")
            if self._clock() >= deadline:
                raise TranslationFailed(f"translation {translation_id} still {state} after {timeout:.0f}s")
            self._sleep(interval)

    def download_external_data(self, did: str, file_id: str) -> bytes:
        return self.request("GET", f"documents/d/{did}/externaldata/{file_id}",
                            accept="application/octet-stream", label="download_external_data").content

    def export_step(self, ref: DocRef, kind: str = "partstudio", timeout: float = 300.0,
                    interval: float = 2.0, **options: Any) -> bytes:
        """STEP bytes via start / poll / download. OCC importers convert the file's units to mm."""
        info = self.start_translation(ref, "STEP", kind, **options)
        done = self.wait_translation(info["id"], timeout=timeout, interval=interval)
        ids = done.get("resultExternalDataIds") or []
        if not ids:
            raise TranslationFailed(f"translation {info['id']} finished without a result file")
        return self.download_external_data(done.get("documentId") or ref.did, ids[0])

    def export_stl(self, ref: DocRef, part_id: str | None = None, binary: bool = True,
                   units: str = "millimeter", **params: Any) -> bytes:
        """STL of one part (or the whole Part Studio), in mm by default. Follows Onshape's 307 redirect."""
        ref.need_element()
        q = {"mode": "binary" if binary else "text", "units": units, "partIds": part_id, **params}
        return self.request("GET", f"partstudios/{ref.path}/stl", params=q,
                            accept="application/octet-stream", label="export_stl").content

    def export_gltf(self, ref: DocRef, binary: bool = False, part_id: str | None = None, **params: Any) -> bytes:
        """glTF of the Part Studio (synchronous endpoint). glTF itself is in metres, as the format requires."""
        ref.need_element()
        accept = "model/gltf-binary" if binary else "model/gltf+json"
        return self.request("GET", f"partstudios/{ref.path}/gltf", params={"partId": part_id, **params},
                            accept=accept, label="export_gltf").content


def _qv(v: Any) -> Any:
    return ("true" if v else "false") if isinstance(v, bool) else v


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
