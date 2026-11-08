"""A procedurally generated "unknown device": its layout, MuJoCo bodies, microcontroller and sim truth.

    spec = make_spec()                  # preset "C", the demo device
    spec = make_spec(seed=7)            # a random layout that passed the reach check
    mcu = DeviceMCU(model)              # readings, events and the LCD; update() every physics step
    mcu.refresh_lcd(renderer)           # before rendering: push the LCD texture to the GPU
    parts = truth(model, data)          # features.Part per control, from the current sim state
    channel_of("slider_1")              # "FAN": the MCU channel a part drives

world.py turns a spec into a scene with device_xml(). Panel frame: u up the slope, v across (+v is
the arm's +y when the device faces the arm), n outward, origin at the panel centre on its surface.
Device frame: origin on the desk under the panel centre, x away from the arm, z up. A part id is
also its body and joint name ("button_1", "slider_1", ...), so DeviceMCU and truth() only need the
compiled model.
"""
import functools
import math
import os
from dataclasses import dataclass, field

import cv2
import mujoco
import numpy as np

import appliance
import robot
from features import Part, canonical_x, frame

# Button: Rev B's (2.5 mm travel, 1.5 N preload to 2.8 N, switch at 70% travel)
TRAVEL = 0.0025
PRELOAD_N, FULL_N = 1.5, 2.8
SWITCH_AT = 0.7
# Dial and knob: hinge along the normal, +-150 deg, a scripted detent every 30 deg
DETENT = math.radians(30)
TURN_RANGE = math.radians(150)
DETENT_NM = 0.015          # peak detent torque: about 1.4 N at the fin end, so 3 N turns it
# Toggle: the lever tilts +-25 deg and an over-centre torque holds it against either stop
TOGGLE_RAD = math.radians(25)
SNAP_NM = 0.035            # about 2.3 N at the lever tip flips it
LEVER_LEN, LEVER_R = 0.0155, 0.0025  # hinge to tip centre, radius: 18 mm overall
TOGGLE_BASE = (0.016, 0.012, 0.004)
# Door: push-push latch as in Rev B; it pops ajar
DOOR_PUSH_IN = 0.09        # rad, about 2.8 mm at the pad
DOOR_OPEN = appliance.DOOR_OPEN_RAD
SEAM = 0.002
# Slider: knob on a raised track, held by 1 N of friction. MuJoCo's friction creeps under any
# steady force, so the knob's gravity is compensated and its friction constraint stiffened.
RAIL = 0.0015
KNOB_L, KNOB_W = 0.010, 0.014
PLATE = 0.005              # panel plate thickness; it stands this proud of the housing
FEET = 0.004
PANEL_Z = 0.05             # arm-frame height of the panel centre; reachable for 35-50 deg tilts
PANEL_H = PANEL_Z - appliance.TABLE_Z  # the same, above the desk
APPROACH = 0.03            # probe stand-off checked for reach, as in skills.py
PAD_R = 0.006              # probe pad radius
FLASH_S = 1.0
CHANNEL = {"slider": "FAN", "dial": "MODE", "toggle": "POWER", "knob": "TEMP", "door": "DOOR", "display": ""}
ORDER = ("button", "slider", "dial", "toggle", "knob", "door", "display")

# Printing: labels below each control, rendered into one texture over the panel
TXT, GAP = 0.0032, 0.0025  # label cap height, gap to its control (m)
PPM = 8000                 # texture pixels per metre
FONT = cv2.FONT_HERSHEY_DUPLEX
LCD_PX = (480, 176)        # the 60 x 22 mm screen

CAPS = [(0.05, 0.62, 0.72), (0.98, 0.70, 0.10), (0.90, 0.28, 0.22), (0.20, 0.68, 0.32),
        (0.16, 0.42, 0.88), (0.56, 0.34, 0.80), (0.95, 0.45, 0.12), (0.92, 0.92, 0.90)]
HOUSINGS = [(0.90, 0.89, 0.86), (0.78, 0.79, 0.80), (0.24, 0.25, 0.27), (0.62, 0.68, 0.63), (0.84, 0.79, 0.69)]
PANELS = [((0.13, 0.135, 0.145), (0.88, 0.88, 0.86)), ((0.93, 0.93, 0.91), (0.16, 0.16, 0.17)),
          ((0.16, 0.21, 0.29), (0.90, 0.91, 0.92))]  # (plate, ink)
BUTTON_LABELS = [["1", "2", "3", "4"], ["A", "B", "C", "D"], ["START", "STOP", "TIMER", "LIGHT"],
                 ["MENU", "OK", "UP", "DOWN"]]


@dataclass
class Module:
    id: str                 # part id, e.g. "button_1"
    kind: str
    u: float = 0.0          # centre on the panel (m)
    v: float = 0.0
    dims: dict = field(default_factory=dict)  # sizes (m), orientation and start state, per kind
    label: str = ""
    rgba: tuple = (0.1, 0.1, 0.11)


@dataclass
class DeviceSpec:
    name: str
    tilt_deg: float
    panel_w: float          # across (m)
    panel_l: float          # up the slope, door included (m)
    panel_x: float          # arm-frame x of the panel centre at the nominal placement (m)
    door: dict              # flap u0 (hinge), u1, half width hw, pad_u, pad_v, pad_r (panel frame, m)
    modules: list
    colors: dict
    seed: int = None
    attempts: int = 1       # layouts that fitted before one passed the reach check


def channel_of(part_id):
    kind, k = part_id.rsplit("_", 1)
    return f"BTN{k}" if kind == "button" else CHANNEL[kind]


def _part_ids(names):
    """The names that are part ids ("button_1", ...), sorted by kind then number."""
    ids = {n for n in names if n.rsplit("_", 1)[0] in ORDER and n.rsplit("_", 1)[-1].isdigit()}
    return sorted(ids, key=lambda i: (ORDER.index(i.rsplit("_", 1)[0]), int(i.rsplit("_", 1)[1])))


# --- layout ---

def make_spec(seed=None, preset="C"):
    """seed None gives the preset (only "C" exists). A seed gives a random layout whose
    actionable parts the probe can all reach at the nominal placement."""
    if seed is None:
        assert preset == "C", "only preset C exists"
        spec = _preset_c()
        assert reachable(spec, device_pose(spec)), "preset C is out of reach"
        return spec
    rng = np.random.default_rng(seed)
    attempts = 0
    for _ in range(500):
        spec = _random_spec(rng, seed)
        if spec is None:
            continue  # didn't fit on the panel
        attempts += 1
        if reachable(spec, device_pose(spec)):
            spec.attempts = attempts
            return spec
    raise RuntimeError(f"no reachable layout for seed {seed}")


def _panel_x(tilt_deg):
    # steeper panels sit further back, or the low edge is too close for a press along the normal
    return 0.27 + 0.03 * (tilt_deg - 35) / 15


def _door(L, W, width_frac, pad_shift):
    # flap 42 mm up the slope from 6 mm above the panel's low edge; 18 mm pad 31 mm from the hinge
    u0 = -L / 2 + 0.006 + SEAM
    hw = W * width_frac / 2 - SEAM
    return dict(u0=u0, u1=u0 + 0.042, hw=hw, pad_u=u0 + 0.031, pad_v=pad_shift * (hw - 0.016), pad_r=0.009)


def _preset_c():
    dial = dict(r=0.014, h=0.009, fin_l=0.024, fin_w=0.0045, fin_h=0.007, start=3)
    mods = [Module("display_1", "display"), Module("dial_1", "dial", dims=dial, label="MODE"),
            Module("toggle_1", "toggle", dims=dict(along_u=True, on=True), label="POWER")]
    mods += [Module(f"button_{i + 1}", "button", dims=dict(r=0.0075, h=0.003), label=str(i + 1), rgba=CAPS[i])
             for i in range(3)]
    mods.append(Module("slider_1", "slider", dims=dict(len=0.072, h=0.009, along_u=False, start=0.42), label="FAN"))
    colors = dict(housing=HOUSINGS[0], panel=PANELS[0][0], ink=PANELS[0][1], pad=(0.93, 0.42, 0.13),
                  knob=(0.1, 0.1, 0.11), slider=(0.92, 0.92, 0.9), accent=(0.95, 0.45, 0.12))
    spec = DeviceSpec("C", 40.0, 0.175, 0.165, _panel_x(40.0), _door(0.165, 0.175, 0.64, 0), mods, colors)
    assert _place_rows(spec, [mods[:3], mods[3:]])
    return spec


def _random_spec(rng, seed):
    tilt = float(rng.uniform(35, 50))
    W, L = float(rng.uniform(0.165, 0.185)), float(rng.uniform(0.155, 0.17))
    panel, ink = PANELS[rng.integers(len(PANELS))]
    # cap colours, leaving out any too close to the plate's (a white cap on a white plate)
    caps = [i for i in rng.permutation(len(CAPS)) if np.abs(np.subtract(CAPS[i], panel)).max() > 0.2]
    labels = BUTTON_LABELS[rng.integers(len(BUTTON_LABELS))]
    mods = [Module("display_1", "display")]
    for i in range(rng.integers(2, 5)):  # caps at least 3 mm tall still stand proud of the bezel fully pressed
        dims = dict(r=rng.uniform(0.006, 0.009), h=rng.uniform(0.003, 0.004))
        mods.append(Module(f"button_{i + 1}", "button", dims=dims, label=labels[i], rgba=CAPS[caps[i]]))
    if rng.random() < 0.7:
        dims = dict(len=rng.uniform(0.055, 0.08), h=rng.uniform(0.008, 0.010), along_u=bool(rng.random() < 0.5),
                    start=rng.uniform(0.1, 0.9))
        mods.append(Module("slider_1", "slider", dims=dims, label="FAN"))
    if rng.random() < 0.7:
        r = rng.uniform(0.012, 0.015)
        dims = dict(r=r, h=rng.uniform(0.008, 0.010), fin_l=min(rng.uniform(0.022, 0.026), 2 * r - 0.002),
                    fin_w=rng.uniform(0.004, 0.005), fin_h=rng.uniform(0.006, 0.008), start=int(rng.integers(1, 12)))
        mods.append(Module("dial_1", "dial", dims=dims, label="MODE"))
    if rng.random() < 0.7:
        dims = dict(along_u=bool(rng.random() < 0.5), on=bool(rng.random() < 0.5))
        mods.append(Module("toggle_1", "toggle", dims=dims, label="POWER"))
    if rng.random() < 0.35:
        dims = dict(r=rng.uniform(0.010, 0.014), h=rng.uniform(0.010, 0.014), start=int(rng.integers(1, 12)))
        mods.append(Module("knob_1", "knob", dims=dims, label="TEMP"))
    colors = dict(housing=HOUSINGS[rng.integers(len(HOUSINGS))], panel=panel, ink=ink, pad=CAPS[caps[-1]],
                  knob=(0.1, 0.1, 0.11), slider=(0.92, 0.92, 0.9), accent=CAPS[caps[-2]])
    door = _door(L, W, rng.uniform(0.55, 0.75), int(rng.integers(-1, 2)))
    spec = DeviceSpec(f"s{seed}", tilt, W, L, _panel_x(tilt), door, mods, colors)
    return spec if _pack(spec, rng) else None


def _text_w(text, h=TXT):
    if not text:
        return 0.0
    (w, th), _ = cv2.getTextSize(text, FONT, 1.0, 1)
    return h * w / th


def footprint(m):
    """(u_lo, u_hi, v_lo, v_hi) of a module and its printing, around its centre (m)."""
    d, lw, below = m.dims, _text_w(m.label) / 2 + 0.001, GAP + TXT
    if m.kind == "display":
        return -0.015, 0.015, -0.034, 0.034
    if m.kind in ("button", "dial", "knob"):
        r = d["r"] + (0.002 if m.kind == "button" else 0.006)  # bezel, or the printed detent ticks
        return -(r + below), r, -max(r, lw), max(r, lw)
    if m.kind == "slider":
        a, b = d["len"] / 2 + 0.001, 0.0125  # ticks on one side of the 16 mm track
        if d["along_u"]:
            return -(a + below), a, -0.009, b
        return -(0.009 + below), b, -max(a, lw), max(a, lw)
    if d["along_u"]:  # toggle: ON above, OFF and the label below
        return -(0.010 + TXT + GAP + TXT), 0.010 + TXT, -max(0.0065, lw), max(0.0065, lw)
    e = 0.010 + _text_w("OFF")
    return -(0.0065 + below), 0.0065, -e, e


def _control_area(spec):
    """(u0, u1, v0, v1): the panel above the door, less a margin."""
    return (spec.door["u1"] + SEAM + 0.005, spec.panel_l / 2 - 0.005,
            -spec.panel_w / 2 + 0.006, spec.panel_w / 2 - 0.006)


def _place_rows(spec, rows, area=None):
    """Two rows above the door, modules spread evenly left to right (from the arm's view: +v first)."""
    u0, u1, v0, v1 = area or _control_area(spec)
    mid = (u0 + u1) / 2
    for row, (ra, rb) in zip(rows, ((mid, u1), (u0, mid))):
        fps = [footprint(m) for m in row]
        gap = (v1 - v0 - sum(f[3] - f[2] for f in fps)) / (len(row) + 1)
        v = v1
        for m, (ul, uh, vl, vh) in zip(row, fps):
            if uh - ul > rb - ra or gap < 0.004:
                return False
            m.v = v - gap - vh
            m.u = (ra + rb) / 2 - (ul + uh) / 2
            v = m.v + vl
    return True


def _pack(spec, rng):
    """Shuffle modules into two rows (the display in the top one). A slider along the slope takes a
    full-height column at one end. False if they don't fit."""
    u0, u1, v0, v1 = _control_area(spec)
    rest = []
    for m in spec.modules:
        if m.kind == "slider" and m.dims["along_u"]:
            ul, uh, vl, vh = footprint(m)
            if uh - ul > u1 - u0:
                return False
            m.u = (u0 + u1) / 2 - (ul + uh) / 2
            if rng.random() < 0.5:
                m.v, v1 = v1 - vh, v1 - (vh - vl) - 0.004
            else:
                m.v, v0 = v0 - vl, v0 + (vh - vl) + 0.004
        elif m.kind != "display":
            rest.append(m)
    width = lambda m: footprint(m)[3] - footprint(m)[2]
    rows = [[m for m in spec.modules if m.kind == "display"], []]
    for i in rng.permutation(len(rest)):
        room = [r for r in (0, 1)
                if sum(map(width, rows[r])) + width(rest[i]) + 0.004 * (len(rows[r]) + 2) <= v1 - v0]
        if not room:
            return False
        rows[rng.choice(room)].append(rest[i])
    rows = [[r[i] for i in rng.permutation(len(r))] for r in rows]
    return _place_rows(spec, rows, (u0, u1, v0, v1))


def _axis(m):
    """In-plane (u, v) direction a slider's knob or a toggle's ON side points."""
    return (1.0, 0.0) if m.dims["along_u"] else (0.0, -1.0)


def _travel(d):
    return d["len"] - 0.006 - KNOB_L  # 3 mm end caps


def _start_angle(detent):
    return (6 - detent) * DETENT  # detent 1 at +150 deg (counter-clockwise), 11 at -150 deg


# --- reach ---

def panel_pose(spec):
    """4x4 panel frame in the device frame."""
    t = math.radians(spec.tilt_deg)
    T = np.eye(4)
    T[:3, :3] = [[math.cos(t), 0, -math.sin(t)], [0, 1, 0], [math.sin(t), 0, math.cos(t)]]
    T[:3, 3] = [0, 0, PANEL_H]
    return T


def device_pose(spec, dx=0.0, dy=0.0, yaw_deg=0.0):
    """4x4 device frame in the arm frame: dx, dy, yaw from the nominal spot on the desk."""
    a = math.radians(yaw_deg)
    T = np.eye(4)
    T[:3, :3] = [[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]]
    T[:3, 3] = [spec.panel_x + dx, dy, appliance.TABLE_Z]
    return T


def reach_targets(spec):
    """(name, point, normal) in the device frame: where the probe must go, pointing into the surface.
    Sliders, dials and toggles are pushed sideways, so their targets sit beside the moving part."""
    T = panel_pose(spec)
    out = []

    def add(name, u, v, h):
        out.append((name, T[:3, :3] @ [u, v, h] + T[:3, 3], T[:3, 2]))

    for m in spec.modules:
        d = m.dims
        if m.kind == "button":
            add(m.id, m.u, m.v, d["h"])
        elif m.kind == "slider":  # beside the knob, past either end of its travel
            (au, av), e = _axis(m), _travel(d) / 2 + KNOB_L / 2 + PAD_R
            for s in (-1, 1):
                add(f"{m.id} end{s:+d}", m.u + s * e * au, m.v + s * e * av, (RAIL + d["h"]) / 2)
        elif m.kind == "dial":  # beside the fin near its end, anywhere around
            rho = math.hypot(d["fin_l"] / 2 - 0.003, d["fin_w"] / 2 + PAD_R)
            for a in (0, 90, 180, 270):
                ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
                add(f"{m.id} {a}", m.u + rho * ca, m.v + rho * sa, d["h"] + d["fin_h"] / 2)
        elif m.kind == "toggle":  # beside the lever tip, on whichever side it leans
            au, av = _axis(m)
            for s in (-1, 1):
                along = s * (LEVER_LEN * math.sin(TOGGLE_RAD) + LEVER_R + PAD_R)
                add(f"{m.id} {'on' if s > 0 else 'off'}", m.u + along * au, m.v + along * av,
                    TOGGLE_BASE[2] + LEVER_LEN * math.cos(TOGGLE_RAD))
    add("door_1", spec.door["pad_u"], spec.door["pad_v"], 0.001)
    return out


@functools.lru_cache(maxsize=None)
def _arm_ik():
    return robot.IK(mujoco.MjModel.from_xml_path(os.path.join(robot.ASSETS, appliance.SO101_XML)))


def reach(spec, T_device):
    """Per target, at the contact point and 30 mm out along the normal:
    (name, offset m, position error m, probe tilt off the normal deg)."""
    out = []
    for name, p, n in reach_targets(spec):
        p, n = T_device[:3, :3] @ p + T_device[:3, 3], T_device[:3, :3] @ n
        for off in (0.0, APPROACH):
            _, _, err, ang = _arm_ik().solve(p + off * n, -n, np.zeros(5))
            out.append((name, off, err, ang))
    return out


def reachable(spec, T_device):
    """True when IK puts the probe on every target within 1 mm. Tilt isn't limited, as in skills.validate:
    the arm can't yaw the probe, so a yawed device leaves up to about 25 deg, and presses still pass there."""
    return all(err < 1e-3 for _, _, err, _ in reach(spec, T_device))


# --- MuJoCo model ---

def _f(*xs):
    return " ".join(f"{float(x):.6g}" for x in xs)


def save(path, data):
    """Write bytes unless the file already holds them, so rebuilding a world rewrites nothing
    while another process may be loading it."""
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return
    with open(path, "wb") as f:
        f.write(data)


def _bgr(rgb):
    return tuple(int(round(255 * c)) for c in rgb[::-1])


def device_xml(spec, T_device, folder):
    """(asset XML, worldbody XML) for the device at pose T_device (arm frame). Its textures are
    written into folder as _dev_<name>_*.png. world.py supplies the "scene" and "deco" classes."""
    c, tex = spec.colors, f"_dev_{spec.name}"
    verts, faces = _housing(spec)
    front_x, badge = verts[:, 0].min(), (0.6 * spec.panel_w, 0.045)
    pngs = {"skin": _skin(spec), "door": _door_print(spec), "lcd": lcd_image("READY"),  # DeviceMCU redraws the LCD
            "panel": np.full((8, 8, 3), _bgr(c["panel"]), np.uint8),  # textured too, so it shades like the skin
            "front": _front_print(spec, *badge)}
    for k, img in pngs.items():
        save(os.path.join(folder, f"{tex}_{k}.png"), cv2.imencode(".png", img)[1].tobytes())

    def mat(name, rgb, spec_=0.4, shine=0.5, texture=None, emission=0.0):
        t = f' texture="{texture}"' if texture else ""
        return (f'<material name="{name}" rgba="{_f(*rgb, 1)}" specular="{spec_}" shininess="{shine}" '
                f'emission="{emission}"{t}/>')

    face = " ".join(map(str, faces.ravel()))
    assets = [f'<mesh name="dev_housing" vertex="{_f(*verts.ravel())}" face="{face}"/>']
    assets += [f'<texture name="dev_{k}" type="2d" file="{tex}_{k}.png"/>' for k in pngs]
    assets += [mat("dev_housing", c["housing"], 0.35, 0.45), mat("dev_feet", (0.08, 0.08, 0.08), 0.1, 0.2),
               mat("dev_panel", (1, 1, 1), 0.25, 0.35, "dev_panel"), mat("dev_skin", (1, 1, 1), 0.25, 0.35, "dev_skin"),
               mat("dev_doorprint", (1, 1, 1), 0.25, 0.35, "dev_door"),
               mat("dev_lcd", (1, 1, 1), 0.6, 0.9, "dev_lcd", 0.35),
               mat("dev_cavity", (0.02, 0.02, 0.02), 0.0, 0.1), mat("dev_bezel", (0.04, 0.04, 0.045), 0.7, 0.85),
               mat("dev_trim", (0.07, 0.07, 0.075), 0.4, 0.5), mat("dev_chrome", (0.8, 0.81, 0.83), 1.0, 0.95),
               mat("dev_knob", c["knob"], 0.45, 0.6), mat("dev_slider", c["slider"], 0.5, 0.6),
               mat("dev_accent", c["accent"], 0.4, 0.5), mat("dev_pad", c["pad"], 0.45, 0.6),
               mat("dev_front", (1, 1, 1), 0.35, 0.45, "dev_front")]
    assets += [mat(f"dev_{m.id}", m.rgba, 0.5, 0.7) for m in spec.modules if m.kind == "button"]

    T_panel = panel_pose(spec)
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, T_device[:3, :3].ravel())
    hw = spec.panel_w / 2 + 0.008
    x0, x1 = verts[:, 0].min() + 0.01, verts[:, 0].max() - 0.01
    body = f"""
    <body name="device" pos="{_f(*T_device[:3, 3])}" quat="{_f(*q)}" childclass="scene">
      <geom name="housing" type="mesh" mesh="dev_housing" material="dev_housing"/>
      <geom name="feet" class="deco" type="box" pos="{_f((x0 + x1) / 2, 0, FEET / 2)}"
            size="{_f((x1 - x0) / 2, hw - 0.01, FEET / 2)}" material="dev_feet"/>
      <geom name="front_print" class="deco" type="box" pos="{_f(front_x - 0.0001, 0, 0.05)}" xyaxes="0 -1 0 0 0 1"
            size="{_f(badge[0] / 2, badge[1] / 2, 0.0001)}" material="dev_front"/>
      <body name="panel" pos="{_f(*T_panel[:3, 3])}" euler="0 {-math.radians(spec.tilt_deg):.6g} 0">
        {_plate_xml(spec)}
        {"".join(_module_xml(m) for m in spec.modules)}
        {_door_xml(spec)}
      </body>
    </body>"""
    return "\n    ".join(assets), body


def _housing(spec):
    """The housing: its side profile (front, slope, top, back) extruded across the panel with every
    edge rounded. It is convex, so its collision hull is exact."""
    T = panel_pose(spec)
    u, n = T[[0, 2], 0], T[[0, 2], 2]  # (x, z) in the device frame
    c = T[[0, 2], 3] - PLATE * n       # the housing's slope surface sits under the plate
    a = c - (spec.panel_l / 2 + 0.008) * u
    b = c + (spec.panel_l / 2 + 0.008) * u
    back = b[0] + 0.05
    poly = np.array([[a[0], FEET], [back, FEET], [back, b[1]], b, a])  # counter-clockwise in (x, z)
    return _rounded_extrusion(poly, spec.panel_w / 2 + 0.008, R=0.009, r_side=0.006)


def _rounded_extrusion(poly, hw, R, r_side, seg_deg=12, n_side=4):
    """Convex counter-clockwise (x, z) polygon extruded over y in [-hw, hw], profile corners rounded
    with radius R and the two ends with r_side. Returns (vertices Nx3, faces Mx3)."""
    e = np.roll(poly, -1, 0) - poly
    nrm = np.c_[e[:, 1], -e[:, 0]] / np.linalg.norm(e, axis=1)[:, None]  # outward edge normals
    prev = np.roll(nrm, 1, 0)
    core = poly - R * (prev + nrm) / (1 + np.sum(prev * nrm, 1))[:, None]  # polygon shrunk by R
    ang = np.arctan2(nrm[:, 1], nrm[:, 0])
    arcs = []
    for i in range(len(poly)):
        a0 = ang[i - 1]
        turn = (ang[i] - a0) % (2 * np.pi)
        k = max(2, int(np.ceil(np.degrees(turn) / seg_deg)))
        arcs += [(i, a0 + turn * j / k) for j in range(k + 1)]

    def profile(rho):
        return np.array([core[i] + rho * np.array([np.cos(a), np.sin(a)]) for i, a in arcs])

    th = np.linspace(0, np.pi / 2, n_side + 1)
    layers = [(-(hw - r_side + r_side * np.sin(a)), R - r_side * (1 - np.cos(a))) for a in th[::-1]]
    layers += [(hw - r_side + r_side * np.sin(a), R - r_side * (1 - np.cos(a))) for a in th]
    P = len(arcs)
    verts = [np.c_[pr[:, 0], np.full(P, y), pr[:, 1]] for y, rho in layers for pr in [profile(rho)]]
    verts = np.vstack(verts + [verts[0].mean(0, keepdims=True), verts[-1].mean(0, keepdims=True)])
    faces = []
    for j in range(len(layers) - 1):
        for i in range(P):
            a, b = j * P + i, j * P + (i + 1) % P
            faces += [(a, b, b + P), (a, b + P, a + P)]
    for j, centre in ((0, len(verts) - 2), (len(layers) - 1, len(verts) - 1)):
        faces += [(centre, j * P + i, j * P + (i + 1) % P) for i in range(P)]
    faces = np.array(faces)
    mid = verts.mean(0)
    for f in faces:  # outward winding: the shape is convex
        p = verts[f]
        if np.cross(p[1] - p[0], p[2] - p[0]) @ (p.mean(0) - mid) < 0:
            f[1], f[2] = f[2], f[1]
    return verts, faces


def _box(name, ua, ub, va, vb, nz, hz, material, cls="scene"):
    return (f'<geom name="{name}" class="{cls}" type="box" pos="{_f((ua + ub) / 2, (va + vb) / 2, nz)}" '
            f'size="{_f((ub - ua) / 2, (vb - va) / 2, hz)}" material="{material}"/>')


def _plate_xml(spec):
    """Panel plate around the door opening, the dark cavity behind the seam, and the printed skin."""
    L, W, d = spec.panel_l, spec.panel_w, spec.door
    o0, o1, ow = d["u0"] - SEAM, d["u1"] + SEAM, d["hw"] + SEAM
    h = -PLATE / 2, PLATE / 2
    return "\n        ".join([
        _box("panel_top", o1, L / 2, -W / 2, W / 2, *h, "dev_panel"),
        _box("panel_bottom", -L / 2, o0, -W / 2, W / 2, *h, "dev_panel"),
        _box("panel_left", o0, o1, ow, W / 2, *h, "dev_panel"),
        _box("panel_right", o0, o1, -W / 2, -ow, *h, "dev_panel"),
        _box("door_cavity", o0, o1, -ow, ow, -PLATE + 0.0005, 0.0005, "dev_cavity", "deco"),
        # decal: texture right along local +x = -v, down along local -y = -u
        f'<geom name="panel_print" class="deco" type="box" pos="{_f((o1 + L / 2) / 2, 0, 0.00005)}" '
        f'euler="0 0 {-math.pi / 2:.6g}" size="{_f(W / 2, (L / 2 - o1) / 2, 0.00005)}" material="dev_skin"/>'])


def _module_xml(m):
    d, at = m.dims, f"{m.u:.6g} {m.v:.6g} 0"
    if m.kind == "button":
        k = (FULL_N - PRELOAD_N) / TRAVEL
        # the bezel is a flat dark disc around the cap (0.2 mm), so even a fully pressed cap shows above it
        return f"""
        <geom name="{m.id}_bezel" class="deco" type="cylinder" pos="{_f(m.u, m.v, 0.0001)}"
              size="{_f(d['r'] + 0.0012, 0.0001)}" material="dev_bezel"/>
        <body name="{m.id}" pos="{at}">
          <joint name="{m.id}" type="slide" axis="0 0 -1" range="0 {TRAVEL}" stiffness="{k:.1f}"
                 springref="{-PRELOAD_N / k:.6f}" damping="2" frictionloss="0.05" armature="0.2"
                 solreflimit="0.004 1" solimplimit="0.99 0.999 0.001"/>
          <geom name="{m.id}_cap" type="cylinder" pos="{_f(0, 0, d['h'] / 2)}" size="{_f(d['r'], d['h'] / 2)}"
                mass="0.005" material="dev_{m.id}"/>
        </body>"""
    if m.kind == "slider":
        L, h, tr = d["len"], d["h"], _travel(d)
        ref = d["start"] * tr
        rails = "".join(f"""
          <geom name="{m.id}_rail_{i}" type="box" pos="{_f(0, s * 0.005, RAIL / 2)}" size="{_f(L / 2, 0.003, RAIL / 2)}"
                material="dev_trim"/>
          <geom name="{m.id}_end_{i}" type="box" pos="{_f(s * (L / 2 - 0.0015), 0, RAIL / 2)}"
                size="{_f(0.0015, 0.002, RAIL / 2)}" material="dev_trim"/>""" for i, s in enumerate((1, -1)))
        # a stiff end stop too, or the knob overshoots it and bounces back
        return f"""
        <frame pos="{at}" euler="0 0 {math.atan2(_axis(m)[1], _axis(m)[0]):.6g}">{rails}
          <geom name="{m.id}_slot" class="deco" type="box" pos="0 0 0.0001" size="{_f(L / 2 - 0.003, 0.002, 0.0001)}"
                material="dev_cavity"/>
          <body name="{m.id}" pos="{_f(ref - tr / 2, 0, 0)}" gravcomp="1">
            <joint name="{m.id}" type="slide" axis="1 0 0" range="0 {tr:.6g}" ref="{ref:.6g}" frictionloss="1"
                   damping="10" armature="0.05" solreffriction="0.004 1" solimpfriction="0.99 0.999 0.001"
                   solreflimit="0.004 1" solimplimit="0.99 0.999 0.001"/>
            <geom name="{m.id}_knob" type="box" pos="{_f(0, 0, (RAIL + h) / 2)}"
                  size="{_f(KNOB_L / 2, KNOB_W / 2, (h - RAIL) / 2)}" mass="0.008" material="dev_slider"/>
            <geom name="{m.id}_stem" class="deco" type="box" pos="{_f(0, 0, RAIL / 2)}"
                  size="{_f(0.0015, 0.0015, RAIL / 2)}" material="dev_trim"/>
            <geom name="{m.id}_line" class="deco" type="box" pos="{_f(0, 0, h + 0.0001)}"
                  size="{_f(0.0007, KNOB_W / 2 - 0.001, 0.0001)}" material="dev_accent"/>
          </body>
        </frame>"""
    if m.kind in ("dial", "knob"):
        r, h, ref = d["r"], d["h"], _start_angle(d["start"])
        if m.kind == "dial":
            extra = f"""
          <geom name="{m.id}_fin" type="box" pos="{_f(0, 0, h + d['fin_h'] / 2)}"
                size="{_f(d['fin_l'] / 2, d['fin_w'] / 2, d['fin_h'] / 2)}" mass="0.002" material="dev_knob"/>
          <geom name="{m.id}_mark" class="deco" type="box"
                pos="{_f(d['fin_l'] / 2 - 0.0025, 0, h + d['fin_h'] + 0.0001)}"
                size="{_f(0.002, d['fin_w'] / 2 - 0.0006, 0.0001)}" material="dev_accent"/>"""
        else:  # grip ridges and a pointer line
            extra = "".join(f"""
          <geom class="deco" type="box" pos="{_f(r * math.cos(a), r * math.sin(a), h / 2)}" euler="0 0 {a:.6g}"
                size="{_f(0.0006, 0.0008, h / 2 - 0.0005)}" material="dev_knob"/>"""
                            for a in np.linspace(0, 2 * np.pi, 24, endpoint=False))
            extra += f"""
          <geom name="{m.id}_mark" class="deco" type="box" pos="{_f(r - 0.0035, 0, h + 0.0001)}"
                size="{_f(0.0025, 0.0007, 0.0001)}" material="dev_accent"/>"""
        return f"""
        <body name="{m.id}" pos="{at}" euler="0 0 {ref:.6g}">
          <joint name="{m.id}" type="hinge" axis="0 0 1" range="{_f(-TURN_RANGE, TURN_RANGE)}" ref="{ref:.6g}"
                 damping="0.004" armature="0.0001" frictionloss="0.001"/>
          <geom name="{m.id}_knob" type="cylinder" pos="{_f(0, 0, h / 2)}" size="{_f(r, h / 2)}" mass="0.01"
                material="dev_knob"/>
          <geom name="{m.id}_skirt" class="deco" type="cylinder" pos="0 0 0.0006" size="{_f(r + 0.0015, 0.0006)}"
                material="dev_knob"/>{extra}
        </body>"""
    if m.kind == "toggle":
        bl, bw, bh = TOGGLE_BASE
        ref = TOGGLE_RAD if d["on"] else -TOGGLE_RAD
        return f"""
        <frame pos="{at}" euler="0 0 {math.atan2(_axis(m)[1], _axis(m)[0]):.6g}">
          <geom name="{m.id}_base" type="box" pos="{_f(0, 0, bh / 2)}" size="{_f(bl / 2, bw / 2, bh / 2)}"
                material="dev_trim"/>
          <geom name="{m.id}_nut" class="deco" type="cylinder" pos="{_f(0, 0, bh + 0.0008)}" size="0.0035 0.0008"
                material="dev_chrome"/>
          <body name="{m.id}" pos="{_f(0, 0, bh)}" euler="0 {ref:.6g} 0">
            <joint name="{m.id}" type="hinge" axis="0 1 0" range="{_f(-TOGGLE_RAD, TOGGLE_RAD)}" ref="{ref:.6g}"
                   damping="0.0005" armature="0.0002" solreflimit="0.004 1" solimplimit="0.99 0.999 0.001"/>
            <geom name="{m.id}_lever" type="capsule" fromto="{_f(0, 0, 0, 0, 0, LEVER_LEN)}" size="{LEVER_R}"
                  mass="0.002" material="dev_chrome"/>
          </body>
        </frame>"""
    # display: a glossy bezel with the LCD decal on top
    return f"""
        <geom name="{m.id}_bezel" type="box" pos="{_f(m.u, m.v, 0.0006)}" size="0.014 0.033 0.0006"
              material="dev_bezel"/>
        <geom name="{m.id}" class="deco" type="box" pos="{_f(m.u, m.v, 0.00125)}" euler="0 0 {-math.pi / 2:.6g}"
              size="0.030 0.011 0.00005" material="dev_lcd"/>"""


def _door_xml(spec):
    d = spec.door
    dl = d["u1"] - d["u0"]
    # flap, pad and print: 1.4e-5 kg.m2 about the hinge; armature adds about 10%, and the stops are stiff
    # so a flap this light doesn't sink into them (as in appliance.scene_xml)
    return f"""
        <body name="door_1" pos="{_f(d['u0'], 0, -0.0015)}">
          <joint name="door_1" type="hinge" axis="0 -1 0" range="{_f(-DOOR_PUSH_IN, 0)}" stiffness="1.5"
                 damping="0.05" armature="1.5e-6" solreflimit="0.004 1"/>
          <geom name="door_1_flap" type="box" pos="{_f(dl / 2, 0, 0)}" size="{_f(dl / 2, d['hw'], 0.0015)}"
                mass="0.02" material="dev_panel"/>
          <geom name="door_1_print" class="deco" type="box" pos="{_f(dl / 2, 0, 0.00155)}"
                euler="0 0 {-math.pi / 2:.6g}" size="{_f(d['hw'], dl / 2, 0.00005)}" material="dev_doorprint"/>
          <geom name="door_1_pad" type="cylinder" pos="{_f(d['pad_u'] - d['u0'], d['pad_v'], 0.002)}"
                size="{_f(d['pad_r'], 0.0005)}" mass="0.002" material="dev_pad"/>
        </body>"""


# --- printing ---

class _Print:
    """Draws onto a panel-frame region u in [u0, u1], v in [-hw, hw] (image right is -v, down is -u)."""

    def __init__(self, u0, u1, hw, bg, ink):
        self.u1, self.hw, self.ink = u1, hw, ink
        self.img = np.empty((round((u1 - u0) * PPM), round(2 * hw * PPM), 3), np.uint8)
        self.img[:] = bg

    def px(self, u, v):
        return round((self.hw - v) * PPM), round((self.u1 - u) * PPM)

    def line(self, u0, v0, u1, v1, w=0.0004):
        cv2.line(self.img, self.px(u0, v0), self.px(u1, v1), self.ink, max(1, round(w * PPM)), cv2.LINE_AA)

    def text(self, s, u, v, h=TXT):
        (w, th), _ = cv2.getTextSize(s, FONT, 1.0, 1)
        scale = h * PPM / th
        col, row = self.px(u, v)
        cv2.putText(self.img, s, (round(col - w * scale / 2), round(row + h * PPM / 2)), FONT, scale, self.ink,
                    max(1, round(scale * 1.6)), cv2.LINE_AA)


def _skin(spec):
    """Labels, detent ticks, slider scale and toggle ON/OFF over the panel above the door."""
    c = spec.colors
    p = _Print(spec.door["u1"] + SEAM, spec.panel_l / 2, spec.panel_w / 2, _bgr(c["panel"]), _bgr(c["ink"]))
    for m in spec.modules:
        d = m.dims
        if m.kind in ("dial", "knob"):
            for k in range(-5, 6):
                a, end = k * DETENT, abs(k) == 5
                ca, sa = math.cos(a), math.sin(a)
                r0, r1 = d["r"] + 0.0025, d["r"] + (0.006 if end else 0.0052)
                p.line(m.u + r0 * ca, m.v + r0 * sa, m.u + r1 * ca, m.v + r1 * sa, 0.0006 if end else 0.0004)
        elif m.kind == "slider":
            (au, av), tr = _axis(m), _travel(d)
            su, sv = (0.0, 1.0) if d["along_u"] else (1.0, 0.0)  # tick side: +v or +u
            for i in range(11):
                s = -tr / 2 + tr * i / 10
                cu, cv = m.u + s * au, m.v + s * av
                r1 = 0.0125 if i in (0, 5, 10) else 0.0112
                p.line(cu + 0.0088 * su, cv + 0.0088 * sv, cu + r1 * su, cv + r1 * sv)
        elif m.kind == "toggle":
            au, av = _axis(m)
            e = 0.010 + (TXT / 2 if d["along_u"] else _text_w("OFF") / 2)
            p.text("ON", m.u + e * au, m.v + e * av)
            p.text("OFF", m.u - e * au, m.v - e * av)
        if m.label:
            p.text(m.label, m.u + footprint(m)[0] + TXT / 2, m.v)
    return p.img


def _door_print(spec):
    """PUSH under the pad and a ring around it, on the flap."""
    d = spec.door
    dl = d["u1"] - d["u0"]
    p = _Print(-dl / 2, dl / 2, d["hw"], _bgr(spec.colors["panel"]), _bgr(spec.colors["ink"]))
    pu, pv = d["pad_u"] - d["u0"] - dl / 2, d["pad_v"]
    ring = round((d["pad_r"] + 0.0018) * PPM)
    cv2.circle(p.img, p.px(pu, pv), ring, p.ink, max(1, round(0.0004 * PPM)), cv2.LINE_AA)
    p.text("PUSH", pu - d["pad_r"] - GAP - TXT / 2, pv)
    return p.img


def _front_print(spec, w, h):
    """Model name and vent slots for the front face, in shades of the housing colour."""
    img = np.empty((round(h * PPM), round(w * PPM), 3), np.uint8)
    img[:] = _bgr(spec.colors["housing"])
    dark, mid = tuple(round(0.3 * v) for v in img[0, 0]), tuple(round(0.55 * v) for v in img[0, 0])
    for i in range(4):
        y = round((0.019 + 0.0065 * i) * PPM)
        cv2.line(img, (round(0.012 * PPM), y), (round((w - 0.012) * PPM), y), dark, round(0.0032 * PPM), cv2.LINE_AA)
    text = f"MODEL {spec.name.upper()}"
    scale = 0.0045 * PPM / cv2.getTextSize(text, FONT, 1.0, 1)[0][1]
    cv2.putText(img, text, (round(0.012 * PPM), round(0.009 * PPM)), FONT, scale, mid, max(1, round(scale * 1.6)),
                cv2.LINE_AA)
    return img


def _lcd_lines(text):
    """Split at double spaces into at most two lines, as even as possible."""
    chunks = text.split("  ")
    if len(chunks) < 2:
        return [text]
    k = min(range(1, len(chunks)), key=lambda i: max(len("  ".join(chunks[:i])), len("  ".join(chunks[i:]))))
    return ["  ".join(chunks[:k]), "  ".join(chunks[k:])]


def lcd_image(text):
    """BGR image of the LCD: bright green text on a dark green background."""
    w, h = LCD_PX
    img = np.empty((h, w, 3), np.uint8)
    img[:] = (24, 52, 18)
    cv2.rectangle(img, (6, 6), (w - 7, h - 7), (36, 80, 28), 2)
    lines = _lcd_lines(text)
    sizes = [cv2.getTextSize(s, FONT, 1.0, 1)[0] for s in lines]
    scale = min(0.86 * w / max(s[0] for s in sizes), (0.34 if len(lines) > 1 else 0.46) * h / sizes[0][1])
    for i, (s, (tw, th)) in enumerate(zip(lines, sizes)):
        y = h / 2 + th * scale / 2 + (i - (len(lines) - 1) / 2) * 0.46 * h
        cv2.putText(img, s, (round((w - tw * scale) / 2), round(y)), FONT, scale, (110, 235, 120),
                    max(1, round(scale * 1.7)), cv2.LINE_AA)
    return img


# --- the device's microcontroller ---

class DeviceMCU:
    """The device's own microcontroller: readings over "serial", an event log, and its LCD.

    readings: e.g. {"BTN1": 0, "BTN2": 0, "BTN3": 0, "FAN": 0.42, "MODE": 3, "POWER": 1, "DOOR": 0}
    events:   (sim_time, channel, value) whenever a discrete channel changes. FAN is continuous:
              sample it before and after a slide.
    lcd:      the text on the display. Call refresh_lcd(renderer or viewer) before rendering.
    It also plays the mechanisms MuJoCo can't: dial detents, the toggle's snap, the door latch.
    """

    def __init__(self, model):
        self.m = model
        ids = _part_ids(model.joint(j).name for j in range(model.njnt))
        self.joints = {i: (model.joint(i).qposadr[0], model.joint(i).dofadr[0], model.joint(i).id) for i in ids}
        self.readings, self.events = {}, []
        self.dead = set()  # channels wired to nothing: faults.py's dead_ faults. They keep their first reading
        self.slider_end = {i: model.jnt_range[j][1] for i, (_, _, j) in self.joints.items()}  # a jam mustn't rescale the reading
        self.latched, self.armed = True, False
        self._flash, self._flash_until = "", -1.0
        for pid, (qa, _, j) in self.joints.items():
            self._read(pid, model.qpos0[qa], j, 0.0)
        self.lcd_tex = model.texture("dev_lcd").id
        self.lcd = None
        self._show(0.0)

    def update(self, model, data):
        for pid, (qa, da, j) in self.joints.items():
            kind, q = pid.rsplit("_", 1)[0], data.qpos[qa]
            if kind in ("dial", "knob"):
                data.qfrc_applied[da] = -DETENT_NM * math.sin(2 * math.pi * q / DETENT)
            elif kind == "toggle":
                data.qfrc_applied[da] = SNAP_NM * math.sin(math.pi / 2 * q / TOGGLE_RAD)
            elif kind == "door" and self.latched:  # push-push latch: push in, let go, it pops open
                if q < -0.7 * DOOR_PUSH_IN:
                    self.armed = True
                elif self.armed and q > -0.2 * DOOR_PUSH_IN:
                    self.latched = False
                    model.jnt_range[j] = [-DOOR_PUSH_IN, DOOR_OPEN]
                    model.qpos_spring[qa] = DOOR_OPEN + 0.3
                    model.jnt_stiffness[j] = 0.3
            self._read(pid, q, j, data.time)
        self._show(data.time)

    def _read(self, pid, q, j, t):
        kind, k = pid.rsplit("_", 1)
        ch = channel_of(pid)
        if ch in self.dead and ch in self.readings:
            return
        if kind == "slider":
            self.readings[ch] = round(float(np.clip(q / self.slider_end[pid], 0, 1)), 3)
            return
        if kind == "button":
            val = int(q > SWITCH_AT * TRAVEL)
        elif kind in ("dial", "knob"):
            val = int(np.clip(6 - round(q / DETENT), 1, 11))
        elif kind == "toggle":  # with hysteresis around the centre
            val = int(q > 0) if abs(q) > 0.1 or ch not in self.readings else self.readings[ch]
        else:
            val = int(not self.latched)
        if ch in self.readings and self.readings[ch] != val:
            self.events.append((float(t), ch, val))
            if kind == "button" and val:
                self._flash, self._flash_until = f"BTN {k}", t + FLASH_S
            elif kind == "door":
                self._flash, self._flash_until = "DOOR OPEN", t + FLASH_S
        self.readings[ch] = val

    def _status(self):
        r, s = self.readings, []
        if "POWER" in r:
            s.append(f"PWR {'ON' if r['POWER'] else 'OFF'}")
        if "FAN" in r:
            s.append(f"FAN {round(100 * r['FAN'])}%")
        for ch in ("MODE", "TEMP"):
            if ch in r:
                s.append(f"{ch} {r[ch]}")
        if r.get("DOOR"):
            s.append("DOOR OPEN")
        return "  ".join(s) or "READY"

    def _show(self, t):
        text = self._flash if t < self._flash_until else self._status()
        if text == self.lcd:
            return
        self.lcd = text
        rgb = lcd_image(text)[:, :, ::-1]
        adr = self.m.tex_adr[self.lcd_tex]
        self.m.tex_data[adr:adr + rgb.size] = rgb.ravel()

    def refresh_lcd(self, target):
        """Push the LCD texture to a mujoco.Renderer or a viewer handle; call it before rendering."""
        if isinstance(target, mujoco.Renderer):
            if target._gl_context:  # as Renderer.render() does, so the upload reaches this renderer
                target._gl_context.make_current()
            mujoco.mjr_uploadTexture(self.m, target._mjr_context, self.lcd_tex)
        else:
            target.update_texture(self.lcd_tex)

    @property
    def door_open(self):
        return not self.latched

    @property
    def switches(self):
        """Button switch states in order, as skills.py reads them from Rev A/B."""
        return [bool(v) for k, v in self.readings.items() if k.startswith("BTN")]

    def summary(self):
        vals = "  ".join(f"{k}:{v:g}" for k, v in self.readings.items())
        return f"{vals}  LCD:[{self.lcd}]"


# --- sim truth ---

def truth(model, data):
    """features.Part for every control on the device, from body, joint and geom poses in data.

    Choices features.py leaves open: button state is the pressed fraction (0 released). Dial and
    knob axes are +n, so MODE and TEMP count up clockwise. The toggle's axis turns its tip toward
    -x, which flips it. The door's axis is its hinge line, pointing the way a push on the pad turns
    it (that works the latch); its state is the opening angle (rad: 0 shut, negative pushed in,
    DOOR_OPEN once popped) and its size is the flap's. range is always measured from here along
    +axis, so a latched door has (0, DOOR_PUSH_IN)."""
    panel = model.body("panel").id
    R_panel = data.xmat[panel].reshape(3, 3)
    n, across, p0 = R_panel[:, 2], R_panel[:, 1], data.xpos[panel]

    def geom(name):
        g = model.geom(name).id
        return data.geom_xpos[g].copy(), data.geom_xmat[g].reshape(3, 3).copy(), model.geom_size[g].copy()

    def height(p):
        return float((p - p0) @ n)

    parts = []
    for pid in _part_ids([model.body(b).name for b in range(model.nbody)] + ["display_1"]):
        kind = pid.rsplit("_", 1)[0]
        if kind == "display":
            c, R, s = geom(pid)
            top = c + s[2] * R[:, 2]
            parts.append(Part(pid, kind, frame(top, R[:, 2], canonical_x(R[:, 0], R[:, 2])),
                              np.array([2 * s[0], 2 * s[1], height(top)]), meta=dict(screen=(2 * s[0], 2 * s[1]))))
            continue
        j = model.joint(pid).id
        q, (lo, hi) = float(data.qpos[model.jnt_qposadr[j]]), model.jnt_range[j]
        axis, anchor = data.xaxis[j].copy(), data.xanchor[j].copy()
        if kind == "button":
            c, R, s = geom(pid + "_cap")
            top = c + s[1] * R[:, 2]
            parts.append(Part(pid, kind, frame(top, R[:, 2], canonical_x(across, R[:, 2])),
                              np.array([2 * s[0], 2 * s[0], height(top)]), "translation", axis, top, q / hi,
                              (lo - q, hi - q), meta=dict(radius=s[0], travel=hi, switch_at=SWITCH_AT)))
        elif kind == "slider":
            c, R, s = geom(pid + "_knob")
            z, slot = R[:, 2], R[:, 0]
            top, x = c + s[2] * z, canonical_x(slot, z)
            f = q / hi if x @ slot > 0 else 1 - q / hi
            start = top - f * hi * x  # exact even when the knob is a hair past a stop
            f = float(np.clip(f, 0, 1))
            meta = dict(slot_ends=np.array([start, start + hi * x]), travel=hi, knob_len=2 * s[0], knob_width=2 * s[1],
                        side_height=height(c), track_len=2 * model.geom_size[model.geom(pid + "_rail_0").id][0])
            parts.append(Part(pid, kind, frame(top, z, x), np.array([2 * s[0], 2 * s[1], height(top)]), "translation",
                              x, top, f, (-f * hi, (1 - f) * hi), meta=meta))
        elif kind in ("dial", "knob"):
            c, R, s = geom(pid + "_knob")
            z = R[:, 2]
            top = c + s[1] * z
            meta = dict(knob_radius=s[0], knob_height=height(top), angle=q,
                        detent=int(np.clip(6 - round(q / DETENT), 1, 11)), detent_step=DETENT)
            if kind == "dial":
                fc, fR, fs = geom(pid + "_fin")
                x, size = canonical_x(fR[:, 0], z), [2 * s[0], 2 * s[0], height(fc) + fs[2]]
                meta.update(fin_length=2 * fs[0], fin_width=2 * fs[1], fin_height=2 * fs[2])
            else:
                x, size = canonical_x(across, z), [2 * s[0], 2 * s[0], height(top)]
            parts.append(Part(pid, kind, frame(top, z, x), np.array(size), "rotation", axis, top, 0.0,
                              (lo - q, hi - q), meta=meta))
        elif kind == "toggle":
            c, _, s = geom(pid + "_lever")
            lever = (c - anchor) / np.linalg.norm(c - anchor)  # a fromto capsule's z points back at the hinge
            tip = c + s[1] * lever
            x = lever - (lever @ n) * n
            x /= np.linalg.norm(x)
            bs = geom(pid + "_base")[2]
            parts.append(Part(pid, kind, frame(anchor, n, x), np.array([2 * bs[0], 2 * bs[1], height(tip) + s[0]]),
                              "rotation", np.cross(x, n), anchor, 1.0, (0.0, abs(q) + TOGGLE_RAD),
                              meta=dict(lever_len=2 * s[1] + s[0], lever_radius=s[0], tip=tip, base_size=2 * bs,
                                        angle=q, on=bool(q > 0))))
        elif kind == "door":
            fc, fR, fs = geom("door_1_flap")
            pc, _, ps = geom("door_1_pad")
            z, x, y = fR[:, 2], fR[:, 0], fR[:, 1]
            top = pc + ps[1] * z
            corners = np.array([fc + fR @ [sx * fs[0], sy * fs[1], fs[2]]
                                for sx, sy in ((-1, 1), (-1, -1), (1, -1), (1, 1))])  # hinge side first
            meta = dict(corners=corners, hinge=np.array([anchor + fs[1] * y, anchor - fs[1] * y]), pad_radius=ps[0],
                        push_travel=DOOR_PUSH_IN * float((top - anchor) @ x), latched=bool(hi <= 0),
                        open_angle=DOOR_OPEN)
            # the joint opens the door along +axis; the Part's axis is the push that works the latch
            parts.append(Part(pid, kind, frame(top, z, x), np.array([2 * fs[0], 2 * fs[1], height(top)]), "rotation",
                              -axis, anchor, q, (q - hi, q - lo), meta=meta))
    return parts
