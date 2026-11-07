"""Give one SO-101 follower motor its id, for when lerobot-setup-motors stopped partway. Run it in the LeRobot environment.

    python setup_one_motor.py COM10 shoulder_pan

It asks you to connect that motor alone, then does exactly what lerobot-setup-motors does for it.
Names and ids: shoulder_pan 1, shoulder_lift 2, elbow_flex 3, wrist_flex 4, wrist_roll 5, gripper 6.
"""
import sys

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

port, motor = sys.argv[1], sys.argv[2]
follower = SO101Follower(SO101FollowerConfig(port=port))
follower.bus.setup_motors([motor])
