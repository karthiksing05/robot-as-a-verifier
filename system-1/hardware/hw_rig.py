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
import touch

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
        # one pass: on the real centrifuge the first pass's three views found POWER, START, STOP and TIME+ at the same
        # place and height as with the extra pass, whose 10 views (22 s, and a trip home) went to the lid and the laptop
        rgbperceive.EXTRA_VIEWS = rgbperceive.SAM_AUTO = False
        rgbperceive.KEEP_REJECTED = True  # for the review to name: SPEED and POWER fit no rule in some scans
        # the centrifuge's controls sit in one row; a wooden block at the lid hinge, 43-48 mm up the slope from it, read
        # as a dial or toggle and the review named it POWER or SPEED. The real POWER read 21 mm off the row at most
        rgbperceive.ROW_MAX = 0.03
        rgbperceive.SAVE_CAPS = "last_caps.pkl"  # in the folder rav-server runs in
        # good centrifuge surveys: normal z 0.65-0.74, 84-101 points on the panel, 156 mm long. Bad ones fitted the panel and
        # the box's front as one plane (z 0.34: the views went low), had 27 points (113 in all: the views scanned air), or cut
        # the panel to 108 mm (SPEED lost); one 15 mm off drove the jaw into the buttons. A doubtful survey is taken again
        rgbperceive.SURVEY_TRIES, rgbperceive.SURVEY_CHECK = 3, ((0.55, 0.85), 60, 0.13)
        # the arm's own poses and the survey's plane, always: three views never had enough features to fit poses and
        # their presses landed; five did, and fitted a plane 10 mm off under SPEED (4 of 49 features on it)
        rgbperceive.MIN_TRACKS = 10**9
        # the real toggle's bushing stands 9-14 mm and SAM outlines it at 61-81 mm2, outside the sim switch's 2.5-6 mm base
        # and 100 mm2 minimum (a 6 mm floor keeps the cable bundle out)
        # a device's flat top beside its panel pulled the survey's plane to 23 deg from flat (n_z 0.92) and the views
        # went in from above; real panels sit 40-50 deg (n_z 0.70-0.75)
        perceive.PANEL_NZ = (0.3, 0.85)
        # and a small panel beside a big top and front face is the 4th plane with 48 of 467 points: keep looking
        perceive.PANEL_PLANES, perceive.PANEL_MIN_PTS = 8, 25
        # two points 8 cm off to the side of the centrifuge stretched its panel to 226 mm across, its middle 36 mm off the
        # panel's: the views missed half the panel and the extra pass photographed the laptop beside it
        perceive.PANEL_GROUP = 0.01
        perceive.RULES["toggle"].update(plateau=(0.006, 0.016), area=(50e-6, 400e-6))
        # the real SPEED knob's top reads 12 mm across and 15 mm tall, under the sim knob's 18 mm; and a 34 mm "knob"
        # 13 mm tall was the lid's latch
        perceive.RULES["knob"].update(diam=(0.010, 0.020))
        # an arcade button is a cap inside a wider bezel, and the last look's outline took one ring or the other (9.4 mm
        # for a 15.8 mm scan, 36 for 18): either gives the centre, and a neighbour still moves it over SEARCH_M
        touch.SHRINK, touch.RADIUS_TOL = 0.4, 0.010
        # the fit starts from SAM's outline, and may move the press 8 mm: on STOP's scan photos, from a belief 8 mm off,
        # that found the button in 3 more of 16 tries and never did worse, and the fits that found something else
        # landed 9.6 mm and more from the button
        # From the scan's position (no longer the shifted one) the looks moved presses 0.6-3.7 mm; a 6.2 mm move up the
        # slope on TIME+ missed while 1.7 clicked, so a look may move a press 5 mm at most
        touch.FIT_FROM_OUTLINE, touch.SHIFT_MAX = True, 0.005
        touch.LOOK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "last_looks")
    except BaseException:
        arm.close()  # no readout or no camera: let the serial ports go
        raise
    return rig.Rig(arm, wrist, name=f"SO-101 on {arm_port}")
