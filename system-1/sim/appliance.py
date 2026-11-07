"""Parametric test appliance and the scene around it.

Mirrors the plan's CadQuery appliance: one parameter dict per revision, and the
scene XML is generated from it. All positions are in the arm base frame
(x forward, y left, z up, metres).
"""
import math
from dataclasses import dataclass, replace

import mujoco
import numpy as np

from rig import TABLE_Z  # noqa: F401  world.py and device.py read it here

SO101_XML = "so101_new_calib.xml"  # scene file is written next to it in assets/so101/

# Sloped control panel, 45 deg, facing the arm (from the plan's reach check:
# 45 deg presses work 0.22-0.34 m out, -5 to +15 cm relative to the base).
PANEL_CENTER = np.array([0.25, 0.0, 0.04])
PANEL_TILT_DEG = 45.0
# Absolute contact stiffness (N/m, Ns/m). MuJoCo's default scales stiffness by the
# light arm's effective mass, which lets the probe sink ~1 mm at 6 N.
CONTACT_SOLREF = "-15000 -150"

REV_A = {
    "name": "A",
    "button_u": 0.03,                      # position up the slope from panel centre (m)
    "button_y": [-0.035, 0.0, 0.035],
    "button_clearance_mm": [0.40, 0.15, 0.40],  # planted fault: button 2 binds
    "button_travel_mm": 2.5,
    "button_preload_n": 1.5,
    "button_full_force_n": 2.8,
    "door_handle": "pinch_tab",            # planted fault: breaks the no-thumbs rule
}
REV_B = {**REV_A, "name": "B", "button_clearance_mm": [0.40, 0.40, 0.40], "door_handle": "push_latch"}
REVS = {"A": REV_A, "B": REV_B}

# Perception rig (see vision.py). The desk plate is bolted to the arm, so the ChArUco
# board printed on it sits at a known pose in the arm frame. The appliance sits in a
# printed fixture plate that can be anywhere on the desk; one tag on the plate locates it.
BOARD_SQUARES = (5, 7)         # columns along +x, rows along -y
BOARD_SQUARE_M = 0.025
BOARD_MARKER_M = 0.018
BOARD_CENTER = np.array([0.0575, 0.17, TABLE_Z + 0.001])  # centre of the printed surface
FIXTURE_ORIGIN = np.array([0.25, 0.0, TABLE_Z])  # nominal fixture pose: under the panel centre
FIXTURE_TAG_ID = 20
FIXTURE_TAG_M = 0.05           # black square; the printed tag adds a 10 mm white border
FIXTURE_TAG_AT = np.array([-0.02, 0.11, 0.0035])  # centre of the printed surface, fixture frame
CAMERA_FOVY = 42               # vertical, degrees; roughly a phone camera at 16:9
CAMERA_RES = (1280, 720)

# Where things actually are in this sim run. The perception code never reads this.
NOMINAL_PLACEMENT = {
    "fixture": (0.0, 0.0, 0.0),            # dx, dy (m) and yaw (deg) from FIXTURE_ORIGIN
    "camera_pos": (-0.18, 0.46, 0.52),
    "camera_target": (0.17, 0.09, -0.08),
}

DOOR_U = (-0.065, -0.005)  # flap spans this range up the slope; hinge at the low edge
DOOR_HALF_Y = 0.045
DOOR_OPEN_RAD = 0.35  # a push latch pops the door ajar; pulling it wide is a hook job
DOOR_PUSH_IN_RAD = 0.06


def breakaway_force(clearance_mm):
    """Stand-in for a tight hole: below 0.25 mm the cap binds until pushed past ~12 N."""
    return 12.0 if clearance_mm < 0.25 else 0.0


def _panel_axes():
    t = math.radians(PANEL_TILT_DEG)
    u = np.array([math.cos(t), 0.0, math.sin(t)])    # up the slope
    n = np.array([-math.sin(t), 0.0, math.cos(t)])   # outward normal, toward the arm
    return u, np.array([0.0, 1.0, 0.0]), n


def random_placement(rng):
    """Fixture dropped somewhere near its spot on the desk; camera bumped a few cm."""
    p = NOMINAL_PLACEMENT
    return {
        "fixture": (rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), rng.uniform(-10, 10)),
        "camera_pos": tuple(np.array(p["camera_pos"]) + rng.uniform(-0.03, 0.03, 3)),
        "camera_target": p["camera_target"],
    }


def fixture_pose(placement):
    """4x4 pose of the fixture frame in the arm frame."""
    dx, dy, yaw = placement["fixture"]
    a = math.radians(yaw)
    T = np.eye(4)
    T[:3, :3] = [[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]]
    T[:3, 3] = FIXTURE_ORIGIN + [dx, dy, 0]
    return T


def moved(ctrls, T_fixture):
    """The CAD controls (nominal fixture pose) after the fixture moves to T_fixture."""
    T = T_fixture @ np.linalg.inv(fixture_pose(NOMINAL_PLACEMENT))
    return {k: replace(c, pos=T[:3, :3] @ c.pos + T[:3, 3], normal=T[:3, :3] @ c.normal) for k, c in ctrls.items()}


def _camera_xyaxes(pos, target):
    f = np.subtract(target, pos) / np.linalg.norm(np.subtract(target, pos))
    right = np.cross(f, [0, 0, 1])
    right /= np.linalg.norm(right)
    return " ".join(f"{v:.5f}" for v in (*right, *np.cross(right, f)))


@dataclass
class Control:
    name: str
    kind: str          # "button" or "door"
    pos: np.ndarray    # contact point on the surface, arm frame
    normal: np.ndarray # outward surface normal
    skills: tuple      # skills that can actuate it
    travel_mm: float   # expected travel from CAD
    expected_force_n: float = 0.0  # force at full travel from CAD
    requires: str = "push"


def controls(params):
    u, y, n = _panel_axes()
    out = {}
    cap_height = 0.003
    for i, by in enumerate(params["button_y"]):
        p = PANEL_CENTER + params["button_u"] * u + by * y + cap_height * n
        out[f"btn{i + 1}"] = Control(f"btn{i + 1}", "button", p, n, ("press", "press_hold"),
                                     params["button_travel_mm"], params["button_full_force_n"])
    # Latch point near the top edge of the flap.
    p = PANEL_CENTER + (DOOR_U[1] - 0.012) * u + 0.002 * n
    if params["door_handle"] == "push_latch":
        out["door"] = Control("door", "door", p, n, ("push_latch",), 2.0)
    else:
        out["door"] = Control("door", "door", p, n, (), 0.0, requires="pinch")
    return out


def scene_xml(params, placement=NOMINAL_PLACEMENT):
    u, _, n = _panel_axes()
    c = PANEL_CENTER
    k = (params["button_full_force_n"] - params["button_preload_n"]) / (params["button_travel_mm"] / 1000)
    springref = -params["button_preload_n"] / k  # spring sits beyond the rest stop -> preload
    travel = params["button_travel_mm"] / 1000

    buttons = ""
    for i, by in enumerate(params["button_y"]):
        buttons += f"""
        <body name="btn{i + 1}" pos="{params['button_u']} {by} 0">
          <joint name="btn{i + 1}" type="slide" axis="0 0 -1" range="0 {travel}" stiffness="{k:.1f}"
                 springref="{springref:.5f}" damping="2" frictionloss="0.05" armature="0.2"
                 solreflimit="0.004 1" solimplimit="0.99 0.999 0.001"/>
          <geom type="cylinder" pos="0 0 0.0015" size="0.007 0.0015" mass="0.005" rgba="{'0.85 0.2 0.2 1' if i == 1 else '0.2 0.6 0.9 1'}"/>
        </body>"""

    door_len = DOOR_U[1] - DOOR_U[0]
    tab = ""
    if params["door_handle"] == "pinch_tab":
        tab = f'<geom type="box" pos="{door_len - 0.004} 0 0.008" size="0.004 0.012 0.008" rgba="0.3 0.3 0.3 1"/>'
    # The 20 g, 58 mm flap has 2.4e-5 kg.m2 about its hinge; armature adds about 10%. A flap this light
    # sinks 0.06 rad into MuJoCo's default soft limits, so its stops get the buttons' stiff solreflimit.
    door = f"""
        <body name="door" pos="{DOOR_U[0]} 0 0">
          <joint name="door" type="hinge" axis="0 -1 0" range="{-DOOR_PUSH_IN_RAD} 0" stiffness="3" damping="0.05"
                 armature="2.5e-6" solreflimit="0.004 1"/>
          <geom type="box" pos="{door_len / 2} 0 0.0015" size="{door_len / 2 - 0.001} {DOOR_HALF_Y} 0.0015" mass="0.02" rgba="0.75 0.75 0.7 1"/>
          {tab}
        </body>"""

    # Housing below and behind the slope. Low front edge of the panel sets its height.
    front_edge = c - 0.07 * u
    back_edge = c + 0.07 * u
    x0, x1 = front_edge[0], front_edge[0] + 0.16
    hz = (front_edge[2] - TABLE_Z) / 2
    rear_x0 = back_edge[0]
    rear_hz = (back_edge[2] - front_edge[2]) / 2
    fx = fixture_pose(placement)[:3, 3]
    bw, bh = BOARD_SQUARES[0] * BOARD_SQUARE_M / 2, BOARD_SQUARES[1] * BOARD_SQUARE_M / 2
    tag_half = FIXTURE_TAG_M / 2 + 0.01
    cam = placement["camera_pos"]

    return f"""<mujoco model="makecu_test_rig">
  <include file="{SO101_XML}"/>
  <option timestep="0.002" cone="elliptic" impratio="10"/>
  <visual>
    <headlight diffuse="0.6 0.6 0.6" ambient="0.35 0.35 0.35" specular="0 0 0"/>
    <global azimuth="300" elevation="-25" offwidth="1280" offheight="720"/>
  </visual>
  <statistic center="0.18 0 0.02" extent="0.45"/>
  <default>
    <default class="scene">
      <geom contype="1" conaffinity="0" solref="{CONTACT_SOLREF}" friction="0.6"/>
    </default>
  </default>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.4 0.55 0.7" rgb2="0.05 0.05 0.1" width="512" height="3072"/>
    <texture name="wood" type="2d" builtin="flat" rgb1="0.55 0.42 0.3" width="64" height="64"/>
    <material name="table" texture="wood" rgba="0.6 0.47 0.34 1"/>
    <texture name="board" type="2d" file="_charuco.png"/>
    <material name="board" texture="board"/>
    <texture name="tag" type="2d" file="_fixture_tag.png"/>
    <material name="tag" texture="tag"/>
  </asset>
  <worldbody>
    <light pos="0.2 -0.3 1.0" dir="0 0.3 -1" directional="true"/>
    <camera name="scene_cam" pos="{cam[0]} {cam[1]} {cam[2]}" xyaxes="{_camera_xyaxes(cam, placement['camera_target'])}" fovy="{CAMERA_FOVY}"/>
    <body name="rig" childclass="scene">
      <geom name="table" type="box" pos="0.2 0 {TABLE_Z - 0.01}" size="0.45 0.4 0.01" material="table"/>
      <geom name="post" type="box" pos="0.01 0 {(TABLE_Z) / 2 - 0.0025}" size="0.04 0.04 {-TABLE_Z / 2 - 0.0025}" rgba="0.3 0.3 0.32 1"/>
      <geom name="board" type="box" pos="{BOARD_CENTER[0]} {BOARD_CENTER[1]} {BOARD_CENTER[2] - 0.0005}" size="{bw} {bh} 0.0005" material="board" contype="0" conaffinity="0"/>
      <body name="fixture" pos="{fx[0]} {fx[1]} {fx[2]}" euler="0 0 {math.radians(placement['fixture'][2])}">
        <geom name="fixture_plate" type="box" pos="0.03 0.045 0.0015" size="0.09 0.115 0.0015" rgba="0.35 0.35 0.38 1"/>
        <geom name="fixture_tag" type="box" pos="{FIXTURE_TAG_AT[0]} {FIXTURE_TAG_AT[1]} {FIXTURE_TAG_AT[2] - 0.0005}" size="{tag_half} {tag_half} 0.0005" material="tag" contype="0" conaffinity="0"/>
        <!-- appliance children keep arm-frame coordinates for the nominal placement -->
        <body name="appliance" pos="{-FIXTURE_ORIGIN[0]} {-FIXTURE_ORIGIN[1]} {-FIXTURE_ORIGIN[2]}">
          <geom name="housing" type="box" pos="{(x0 + x1) / 2} 0 {TABLE_Z + hz}" size="0.08 0.06 {hz}" rgba="0.92 0.92 0.88 1"/>
          <geom name="housing_rear" type="box" pos="{(rear_x0 + x1) / 2} 0 {front_edge[2] + rear_hz}" size="{(x1 - rear_x0) / 2} 0.06 {rear_hz}" rgba="0.92 0.92 0.88 1"/>
          <geom name="lcd" type="box" pos="{x0 - 0.001} 0 {TABLE_Z + 1.4 * hz}" size="0.002 0.035 0.015" rgba="0.1 0.25 0.15 1"/>
          <body name="panel" pos="{c[0]} {c[1]} {c[2]}" euler="0 {-math.radians(PANEL_TILT_DEG)} 0">
            <geom name="panel" type="box" pos="0 0 -0.004" size="0.07 0.06 0.004" rgba="0.85 0.85 0.8 1"/>
            <geom name="housing_slope" type="box" pos="0 0 -0.039" size="0.07 0.06 0.031" rgba="0.92 0.92 0.88 1"/>
            {buttons}
            {door}
          </body>
        </body>
      </body>
    </body>
    <body name="target" mocap="true" pos="0.22 0 0.12">
      <geom type="sphere" size="0.008" rgba="0.1 0.9 0.3 0.5" contype="0" conaffinity="0"/>
    </body>
  </worldbody>
</mujoco>"""


class ApplianceState:
    """Ground truth the appliance's own microcontroller would report: switches, door, LCD."""

    SWITCH_AT = 0.7  # fraction of travel where the switch closes

    def __init__(self, model, params):
        self.params = params
        self.travel = params["button_travel_mm"] / 1000
        self.btn_q = [model.joint(f"btn{i + 1}").qposadr[0] for i in range(3)]
        self.btn_dof = [model.joint(f"btn{i + 1}").dofadr[0] for i in range(3)]
        self.btn_jnt = [model.joint(f"btn{i + 1}").id for i in range(3)]
        self.breakaway = [breakaway_force(c) for c in params["button_clearance_mm"]]
        self.stuck = [False] * 3
        for i in range(3):
            if self.breakaway[i]:
                self._set_stuck(model, i, True)
        self.door_jnt = model.joint("door").id
        self.door_q = model.joint("door").qposadr[0]
        self.latched = True
        self.armed = False
        self.lcd = "READY"
        self.lcd_until = 0.0
        self.switches = [False] * 3

    def _set_stuck(self, model, i, stuck):
        # MuJoCo's joint friction creeps under any steady push, so binding is modelled
        # as a lock (zero range, heavy plunger) that releases past the breakaway force.
        self.stuck[i] = stuck
        model.jnt_range[self.btn_jnt[i]] = [0, 0 if stuck else self.travel]
        model.dof_armature[self.btn_dof[i]] = 50.0 if stuck else 0.2

    def _stop_force(self, data, i):
        """How hard the button is being pushed into its locked stop (N)."""
        rows = (data.efc_type == mujoco.mjtConstraint.mjCNSTR_LIMIT_JOINT) & (data.efc_id == self.btn_jnt[i])
        return float(np.abs(data.efc_force[rows]).sum())

    def update(self, model, data):
        for i in range(3):
            if not self.breakaway[i]:
                continue
            # the stop carries the push minus the spring preload, so add it back
            if self.stuck[i] and self._stop_force(data, i) + self.params["button_preload_n"] > self.breakaway[i]:
                self._set_stuck(model, i, False)
            elif not self.stuck[i] and data.qpos[self.btn_q[i]] < 1e-4 and abs(data.qvel[self.btn_dof[i]]) < 1e-3:
                self._set_stuck(model, i, True)
        for i, adr in enumerate(self.btn_q):
            closed = bool(data.qpos[adr] > self.SWITCH_AT * self.travel)
            if closed and not self.switches[i]:
                self._show(data, f"BTN {i + 1}")
            self.switches[i] = closed

        # Push-push latch: push the flap in, let go, it springs open.
        if self.params["door_handle"] == "push_latch" and self.latched:
            angle = data.qpos[self.door_q]
            if angle < -0.7 * DOOR_PUSH_IN_RAD:
                self.armed = True
            elif self.armed and angle > -0.2 * DOOR_PUSH_IN_RAD:
                self.latched = False
                model.jnt_range[self.door_jnt] = [-DOOR_PUSH_IN_RAD, DOOR_OPEN_RAD]
                model.qpos_spring[self.door_q] = DOOR_OPEN_RAD + 0.3
                model.jnt_stiffness[self.door_jnt] = 0.3
                self._show(data, "DOOR OPEN")
        if data.time > self.lcd_until and self.lcd != "READY" and not self.lcd.startswith("DOOR"):
            self.lcd = "READY"

    def _show(self, data, text):
        self.lcd = text
        self.lcd_until = data.time + 1.0

    @property
    def door_open(self):
        return not self.latched

    def summary(self):
        sw = " ".join(f"B{i + 1}:{'ON ' if s else 'off'}" for i, s in enumerate(self.switches))
        return f"{sw}  door:{'OPEN' if self.door_open else 'latched'}  LCD:[{self.lcd}]"
