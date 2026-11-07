"""Onshape backend pieces: settings (.env), the REST client and, later, tags, checks and the MCP server.

Needs the `onshape` extra (`httpx2`, `mcp`).
"""
from .client import (DocRef, FixtureRecorder, OnshapeClient, OnshapeError, TranslationFailed, decode_fs_value,
                     m_to_mm, mm_expr, mm_to_m, parse_document_url, replay_transport, sign_headers)
from .settings import OnshapeSettings, OnshapeSettingsError, find_repo_root, load_settings

__all__ = ["DocRef", "FixtureRecorder", "OnshapeClient", "OnshapeError", "OnshapeSettings",
           "OnshapeSettingsError", "TranslationFailed", "decode_fs_value", "find_repo_root", "load_settings",
           "m_to_mm", "mm_expr", "mm_to_m", "parse_document_url", "replay_transport", "sign_headers"]
