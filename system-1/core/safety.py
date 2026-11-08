"""Shared stop signal for the rig and its readout transports."""


class SafetyStop(Exception):
    pass
