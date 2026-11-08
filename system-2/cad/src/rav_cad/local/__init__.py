"""A local CAD workspace where the analyst writes CadQuery code for new part geometry (offline, no Onshape)."""
from .sandbox import SandboxError, run_part_code
from .workspace import Workspace
from .backend import LocalCadBackend, faces_of

__all__ = ["LocalCadBackend", "SandboxError", "Workspace", "faces_of", "run_part_code"]
