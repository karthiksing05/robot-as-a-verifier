"""Feature type registry. Add a type: write build(params, ctx) -> FeatureGeom with a defaults dict, register it."""
from __future__ import annotations

from typing import Callable

from . import door, fixed, plunger, slot

TYPES: dict[str, tuple[Callable, dict]] = {
    "button": (plunger.build, plunger.BUTTON),
    "push_latch": (plunger.build, plunger.PUSH_LATCH),
    "dial": (plunger.build, plunger.DIAL),
    "slider": (slot.build, slot.SLIDER),
    "toggle": (slot.build, slot.TOGGLE),
    "window": (fixed.window, fixed.WINDOW),
    "handle": (fixed.handle, fixed.HANDLE),
    "door": (door.build, door.DOOR),
}

PRESSABLE = {"button", "push_latch", "dial", "slider", "toggle"}     # the fingertip taps bare panel near these


def effective_params(feature) -> dict:
    """Type defaults overlaid with the feature's params. An unknown type or parameter name is an error."""
    if feature.type not in TYPES:
        raise KeyError(f"feature '{feature.id}': unknown type '{feature.type}' (known: {sorted(TYPES)})")
    defaults = TYPES[feature.type][1]
    unknown = set(feature.params) - set(defaults)
    if unknown:
        raise KeyError(f"feature '{feature.id}': unknown parameter(s) {sorted(unknown)} for type "
                       f"'{feature.type}' (known: {sorted(defaults)})")
    return {**defaults, **feature.params}
