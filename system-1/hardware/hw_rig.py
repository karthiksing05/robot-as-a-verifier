"""The real rig: the SO-101 on LeRobot's motor bus and the USB wrist camera, as a rig.Rig the pipeline runs on. It needs
the built arm and the camera plugged in, so it has never run: only the drivers under it are tested (tests/).

    rig = hw_rig.make_rig("COM5", "makecu.json")   # torque off: the arm is limp and nothing moves
    rig.arm.enable(confirm=True)                   # the caller has checked the arm is clear to move
    scene = pipeline.scan_device(rig.arm, None, rig.wrist)
    rig.close()                                    # camera closed, then torque off: support the arm first
"""
import real_arm
import real_wrist
import rig


def make_rig(arm_port, calibration, app=None, pad=None):
    """arm_port is the servo bus's serial port and calibration lerobot-calibrate's file (real_arm.make_bus). The wrist
    camera is the first USB camera that isn't the laptop's own (real_wrist.find_camera). app is the device's readout,
    real_arm.OperatorReadout unless given, and pad a fingertip sensor (RealArm). Torque stays off."""
    arm = real_arm.RealArm(real_arm.make_bus(arm_port, calibration), app=app, pad=pad)
    try:
        wrist = real_wrist.WristCamera(arm)
    except BaseException:
        arm.close()  # no camera: let the serial port go
        raise
    return rig.Rig(arm, wrist, name=f"SO-101 on {arm_port}")
