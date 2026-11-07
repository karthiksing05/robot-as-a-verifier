"""Checks that work on any product's CAD, not just our parametric appliance.

A product comes as a STEP assembly of named parts (exported from Onshape, or from our CadQuery model) plus a small
tag file that says which parts are controls, how they move and how the robot reaches them. The checks then ask what
the robot needs: can the fingertip reach each control, do moving parts keep clear through their travel, did a fix
change only parts we can reprint. See tags.py for the file and checks.py for the checks.
"""
from .checks import Result, failures, run
from .step import load_step, save_step
from .tags import Control, Motion, Tags

__all__ = ["Control", "Motion", "Result", "Tags", "failures", "load_step", "run", "save_step"]
