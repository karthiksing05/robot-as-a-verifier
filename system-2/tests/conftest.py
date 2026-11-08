"""Tests never write the real model ledger or server registry."""
import os
import tempfile

_scratch = tempfile.mkdtemp(prefix="rav-tests-")
os.environ.setdefault("RAV_LEDGER", os.path.join(_scratch, "ledger.jsonl"))
os.environ.setdefault("RAV_SERVER_REGISTRY", os.path.join(_scratch, "servers.json"))
