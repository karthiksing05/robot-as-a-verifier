"""The scene around a generated device: desk, backdrop, lights, the ChArUco board and the phone camera.

    w = build_world()                     # preset "C"; build_world(seed=7) for a random device
    arm = SimArm(world=w)                 # loads w.xml_path; arm.app is the device's DeviceMCU
    parts = w.truth(arm.m, arm.d)         # sim truth as features.Part
    w2 = build_world(7, placement=w.random_placement(rng))   # the same device moved on the desk

Cameras: scene_cam is the iPhone on its tripod, hero_cam a 3/4 view for the demo. The desk board
sits where appliance.py puts it, so vision.py's board code works unchanged. Rendering the LCD:
call arm.app.refresh_lcd(renderer) before each render.
"""
import functools
import hashlib
import json
import math
import os
from dataclasses import dataclass

import cv2
import numpy as np

import appliance
import device
import robot
import vision
from appliance import TABLE_Z

NOMINAL_PLACEMENT = {
    "device": (0.0, 0.0, 0.0),            # dx, dy (m) and yaw (deg) from the device's nominal spot
    "camera_pos": (-0.204, 0.485, 0.556),
    "camera_target": (0.195, 0.074, -0.063),  # leaves the device top and the board's near edge 12+ px of frame
}
HERO_CAM = ((0.05, -0.50, 0.30), (0.22, 0.02, -0.03))  # position, target
DESK = (-0.40, 0.95, -0.70, 0.70)                       # x0, x1, y0, y1 (m)
FLOOR_Z = TABLE_Z - 0.75


@dataclass
class World:
    name: str
    xml_path: str
    spec: device.DeviceSpec
    placement: dict

    def make_mcu(self, model):
        return device.DeviceMCU(model)

    def truth(self, model, data):
        return device.truth(model, data)

    def channel_of(self, part_id):
        return device.channel_of(part_id)

    def device_pose(self):
        """4x4 device frame in the arm frame (sim truth; perception never reads it)."""
        return device.device_pose(self.spec, *self.placement["device"])

    def device_geom_ids(self, model):
        """Every geom on the device: housing, panel, controls and decals."""
        root = model.body("device").id

        def on_device(b):
            while b > 0 and b != root:
                b = model.body_parentid[b]
            return b == root

        return [g for g in range(model.ngeom) if on_device(model.geom_bodyid[g])]

    def random_placement(self, rng):
        """Device moved up to 3 cm and 12 deg on the desk, camera bumped up to 3 cm. Draws again
        until the probe can still reach every actionable part."""
        p = NOMINAL_PLACEMENT
        for _ in range(20):
            dev = tuple(float(v) for v in (rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), rng.uniform(-12, 12)))
            cam = tuple(float(v) for v in np.add(p["camera_pos"], rng.uniform(-0.03, 0.03, 3)))
            if device.reachable(self.spec, device.device_pose(self.spec, *dev)):
                return {"device": dev, "camera_pos": cam, "camera_target": p["camera_target"]}
        raise RuntimeError(f"no reachable placement for device {self.name} in 20 draws")


def build_world(seed=None, preset="C", placement=None):
    """Generate the device and write the scene to assets/so101/_world_<name>.xml. Other placements
    get a hash of the placement in the file name, so every World keeps its own file."""
    spec = device.make_spec(seed, preset)
    placement = placement or NOMINAL_PLACEMENT
    vision.write_textures(robot.ASSETS)
    device.save(os.path.join(robot.ASSETS, "_wood.png"), _wood_png())
    assets, body = device.device_xml(spec, device.device_pose(spec, *placement["device"]), robot.ASSETS)
    key = json.dumps(placement, sort_keys=True).encode()
    tag = "" if placement == NOMINAL_PLACEMENT else "_" + hashlib.sha1(key).hexdigest()[:8]
    path = os.path.join(robot.ASSETS, f"_world_{spec.name}{tag}.xml")
    device.save(path, scene_xml(spec.name, placement, assets, body).encode())
    return World(spec.name, path, spec, placement)


@functools.lru_cache(maxsize=None)
def _wood_png():
    return cv2.imencode(".png", wood_texture())[1].tobytes()  # takes 1.5 s, so once per process


def _f(*xs):
    return " ".join(f"{float(x):.6g}" for x in xs)


def _dir(src, dst):
    d = np.subtract(dst, src)
    return _f(*(d / np.linalg.norm(d)))


def _cyclorama(centre=(0.25, 0.0), R=1.8, rc=0.5, top=1.6, segs=72):
    """A seamless studio backdrop all around the desk: floor curving up into a wall, faces pointing in."""
    arc = [(R - rc + rc * math.sin(t), FLOOR_Z + rc - rc * math.cos(t)) for t in np.linspace(0, math.pi / 2, 9)]
    prof = [(0.01, FLOOR_Z)] + arc + [(R, top)]
    th = np.linspace(0, 2 * math.pi, segs, endpoint=False)
    v = np.array([(centre[0] + r * math.cos(t), centre[1] + r * math.sin(t), z) for t in th for r, z in prof])
    P, inside = len(prof), np.array([centre[0], centre[1], FLOOR_Z + 0.5])
    faces = []
    for i in range(segs):
        for k in range(P - 1):
            a, b = i * P + k, (i + 1) % segs * P + k
            for f in ((a, a + 1, b + 1), (a, b + 1, b)):
                n = np.cross(v[f[1]] - v[f[0]], v[f[2]] - v[f[0]])
                faces.append(f if n @ (inside - v[list(f)].mean(0)) > 0 else (f[0], f[2], f[1]))
    return v, np.array(faces)


def scene_xml(name, placement, dev_assets, dev_body):
    x0, x1, y0, y1 = DESK
    bw = appliance.BOARD_SQUARES[0] * appliance.BOARD_SQUARE_M / 2
    bh = appliance.BOARD_SQUARES[1] * appliance.BOARD_SQUARE_M / 2
    bc = appliance.BOARD_CENTER
    cam, (hero, hero_at) = placement["camera_pos"], HERO_CAM
    leg_h = (TABLE_Z - 0.03 - FLOOR_Z) / 2
    legs = "".join(f"""
      <geom class="deco" type="box" pos="{_f(x, y, FLOOR_Z + leg_h)}" size="{_f(0.025, 0.025, leg_h)}"
            material="leg"/>"""
                   for x in (x0 + 0.06, x1 - 0.06) for y in (y0 + 0.06, y1 - 0.06))
    # Key high on the phone's side, so the arm never shadows the panel. Its falloff is down to 2% at the
    # cone's edge (45 deg, exponent 12): a harder edge drew stair-step bands across the backdrop. Its shadow
    # map covers the inner 18 deg (shadowscale 0.4), around the arm and device; wider, it dots the backdrop.
    key, rim = (0.0, 0.70, 1.50), (0.95, -0.35, 0.65)
    cyc_v, cyc_f = _cyclorama()
    return f"""<mujoco model="makecu_world_{name}">
  <include file="{appliance.SO101_XML}"/>
  <option timestep="0.002" cone="elliptic" impratio="10"/>
  <visual>
    <quality shadowsize="4096" offsamples="8"/>
    <map shadowscale="0.4"/>
    <headlight ambient="0.3 0.3 0.31" diffuse="0.15 0.15 0.15" specular="0 0 0"/>
    <global azimuth="215" elevation="-22" offwidth="1920" offheight="1080"/>
  </visual>
  <statistic center="0.2 0 0" extent="0.5"/>
  <default>
    <default class="scene">
      <geom contype="1" conaffinity="0" solref="{appliance.CONTACT_SOLREF}" friction="0.6"/>
    </default>
    <default class="deco">
      <geom contype="0" conaffinity="0"/>
    </default>
  </default>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.86 0.87 0.89" rgb2="0.62 0.63 0.66" width="512" height="3072"/>
    <mesh name="cyclorama" vertex="{_f(*cyc_v.ravel())}" face="{" ".join(map(str, cyc_f.ravel()))}" inertia="shell"/>
    <material name="cyclorama" rgba="0.8 0.8 0.82 1" specular="0" shininess="0"/>
    <texture name="wood" type="2d" file="_wood.png"/>
    <material name="desk" texture="wood" specular="0.25" shininess="0.4"/>
    <material name="leg" rgba="0.15 0.15 0.16 1" specular="0.4" shininess="0.5"/>
    <material name="metal" rgba="0.17 0.17 0.19 1" specular="0.6" shininess="0.6"/>
    <material name="paper" rgba="0.95 0.95 0.94 1" specular="0.05" shininess="0.1"/>
    <texture name="board" type="2d" file="_charuco.png"/>
    <material name="board" texture="board" specular="0.05" shininess="0.1"/>
    {dev_assets}
  </asset>
  <worldbody>
    <light name="key" type="spot" pos="{_f(*key)}" dir="{_dir(key, (0.25, 0, -0.1))}" cutoff="45" exponent="12"
           diffuse="0.8 0.78 0.75" specular="0.4 0.4 0.4" castshadow="true"/>
    <light name="fill" type="directional" dir="{_dir((0, 0, 0), (0.3, 0.8, -0.6))}" diffuse="0.25 0.26 0.28"
           specular="0.05 0.05 0.05" castshadow="false"/>
    <light name="rim" type="spot" pos="{_f(*rim)}" dir="{_dir(rim, (0.3, 0, 0.05))}" cutoff="40" diffuse="0.3 0.3 0.32"
           specular="0.3 0.3 0.3" castshadow="false"/>
    <camera name="scene_cam" pos="{_f(*cam)}" xyaxes="{appliance._camera_xyaxes(cam, placement['camera_target'])}"
            fovy="{appliance.CAMERA_FOVY}"/>
    <camera name="hero_cam" pos="{_f(*hero)}" xyaxes="{appliance._camera_xyaxes(hero, hero_at)}" fovy="40"/>
    <geom name="cyclorama" class="deco" type="mesh" mesh="cyclorama" material="cyclorama"/>
    <body name="rig" childclass="scene">
      <geom name="table" type="box" pos="{_f((x0 + x1) / 2, (y0 + y1) / 2, TABLE_Z - 0.015)}"
            size="{_f((x1 - x0) / 2, (y1 - y0) / 2, 0.015)}" material="desk"/>{legs}
      <geom name="post" type="box" pos="{_f(0.01, 0, TABLE_Z / 2 - 0.0025)}"
            size="{_f(0.04, 0.04, -TABLE_Z / 2 - 0.0025)}" material="metal"/>
      <geom name="board_paper" class="deco" type="box" pos="{_f(bc[0], bc[1], TABLE_Z + 0.0001)}"
            size="{_f(bw + 0.008, bh + 0.008, 0.0001)}" material="paper"/>
      <geom name="board" class="deco" type="box" pos="{_f(bc[0], bc[1], bc[2] - 0.0005)}" size="{_f(bw, bh, 0.0005)}"
            material="board"/>
    </body>
    {dev_body}
    <body name="target" mocap="true" pos="0.22 0 0.12">
      <geom type="sphere" size="0.008" rgba="0.1 0.9 0.3 0.5" contype="0" conaffinity="0"/>
    </body>
  </worldbody>
</mujoco>"""


def wood_texture(size=2048, seed=3):
    """Butcher-block desk top (BGR): strips along x, each with its own tone and wavy grain."""
    rng = np.random.default_rng(seed)

    def smooth(gy, gx):  # value noise on a gy x gx grid
        return cv2.resize(rng.standard_normal((gy, gx)).astype(np.float32), (size, size), interpolation=cv2.INTER_CUBIC)

    rows = np.arange(size, dtype=np.float32)[:, None]
    edges = np.cumsum(rng.uniform(0.035, 0.06, 60)) * size  # strips 5 to 8 cm wide on the 1.4 m desk
    strip = np.searchsorted(edges, rows[:, 0])
    per = lambda lo, hi: rng.uniform(lo, hi, 61)[strip][:, None]
    warp = 7 * smooth(10, 3) + 2.5 * smooth(60, 14)
    grain = (0.5 + 0.5 * np.sin(2 * np.pi * (rows + warp * per(0.6, 1.4)) / per(7, 16) + per(0, 6.3))) ** 3
    fibre = smooth(size // 2, 8) * 0.5 + smooth(size // 8, 40) * 0.5
    t = np.clip(0.42 * grain + 0.12 * fibre + per(-0.12, 0.12) + 0.25, 0, 1)
    seam = np.abs(rows - edges[np.clip(strip, 0, len(edges) - 1)][:, None]) < 1.5
    t = np.where(seam, 0.95, t)
    light, dark = np.array([0.42, 0.60, 0.78]), np.array([0.20, 0.33, 0.50])  # BGR oak
    img = light * (1 - t[..., None]) + dark * t[..., None]
    return np.clip(img * 255, 0, 255).astype(np.uint8)
