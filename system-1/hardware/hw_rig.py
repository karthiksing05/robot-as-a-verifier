"""The real rig: the SO-101 on LeRobot's motor bus and the USB wrist camera, as a rig.Rig the pipeline runs on. It needs
the built arm and the camera plugged in, so it has never run: only the drivers under it are tested (tests/).

    rig = hw_rig.make_rig("COM5", "makecu.json", readout_port="COM7")  # torque off: the arm is limp
    rig.arm.enable(confirm=True)                       # the caller has checked the arm is clear to move
    scene = pipeline.scan_device(rig.arm, None, rig.wrist)
    rig.close()                                        # camera closed, then torque off: support the arm first
"""
import json
import os

import numpy as np

import perceive
import pico_readout
import real_arm
import real_wrist
import rgbperceive
import rig

GRIPPER_PX = os.path.join(os.path.dirname(real_wrist.HAND_EYE), "gripper_px.json")  # tools/gripper_mask.py


def make_rig(arm_port, calibration, app=None, pad=None, readout_port=None):
    """arm_port is the servo bus's serial port and calibration lerobot-calibrate's file (real_arm.make_bus). The wrist
    camera is the first USB camera that isn't the laptop's own (real_wrist.find_camera). app is the device's readout,
    real_arm.OperatorReadout unless given, or with readout_port the device's Pico on that serial port
    (pico_readout.PicoReadout). pad is a fingertip sensor (RealArm). The model's wrist camera moves to the mount in
    hand_eye.json (real_wrist.move_mount). Torque stays off."""
    arm = real_arm.RealArm(real_arm.make_bus(arm_port, calibration), app=app, pad=pad)
    try:
        if readout_port:
            arm.app = pico_readout.PicoReadout(readout_port)
        real_wrist.move_mount(arm.m)  # IK and the photos' poses both use the measured camera, so no T_hand_eye on top
        wrist = real_wrist.WristCamera(arm, T_hand_eye=np.eye(4))
        if os.path.exists(GRIPPER_PX):  # where the real gripper sits in the picture, not the sim's render
            g = json.load(open(GRIPPER_PX))
            rgbperceive.GRIPPER_PX = np.round(np.array(g["gripper_px"]) * rgbperceive.PX_WIDTH / g["width"]).astype(np.int32)
            print(f"Gripper mask from {os.path.normpath(GRIPPER_PX)}")
        rgbperceive.FLAT_BUTTONS = True  # see rgbperceive.FLAT_BUTTONS
        # the real toggle's bushing stands 9-14 mm and SAM outlines it at 61-81 mm2, outside the sim switch's 2.5-6 mm base
        # and 100 mm2 minimum (a 6 mm floor keeps the cable bundle out)
        perceive.RULES["toggle"].update(plateau=(0.006, 0.016), area=(50e-6, 400e-6))
    except BaseException:
        arm.close()  # no readout or no camera: let the serial ports go
        raise
    return rig.Rig(arm, wrist, name=f"SO-101 on {arm_port}")
