"""A device from CAD meshes and one data file, in place of device.py's generated one. No device-specific code here:
everything about a device is in its YAML (see appliances/*/device.yaml).

    w = build_cad_world("appliances/centrifuge/device.yaml", rev="A")   # or rev="F1=B,F2=B,F3=A"
    arm = robot.SimArm(world=w, slop=True, sensing="tactile", effector="probe")  # arm.app is its firmware
    parts = w.truth(arm.m, arm.d)                                       # sim truth, as features.Part
    w.set_root_pose(arm.m, arm.d, "centrifuge", dx=0.01, dy=-0.02, yaw_deg=5)   # move it, at any time

Sim truth: only the loader, the answer key and evaluation read the device file or truth(). Perception doesn't.
"""
import ast
import json
import math
import os
import pathlib
import re
from dataclasses import dataclass

import cv2
import mujoco
import numpy as np
import yaml

import appliance
import device as generated
import robot
import world as world_mod
from features import Part  # noqa: F401
from inventory import parts_from, resolve as _resolve, root_for as _root_for  # the robot side builds a CAD inventory the same way

M = 1e-3
_ALLOWED = {"round": round, "radians": math.radians, "abs": abs, "min": min, "max": max}
_NODES = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Call, ast.Name, ast.Load, ast.Constant, ast.And,
          ast.Or, ast.Not, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.USub, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
          ast.Gt, ast.GtE)


def _compile(expr):
    """A device file's conditions and values: arithmetic and comparisons only."""
    tree = ast.parse(str(expr), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _NODES):
            raise ValueError(f"not allowed in a device file expression: {expr}")
    return compile(tree, "<device file>", "eval")


def _eval(code, names):
    return eval(code, {"__builtins__": {}, **_ALLOWED}, names)  # noqa: S307  only the nodes _compile allowed


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _yaw(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _T(R, p):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, p
    return T


def _f(*xs):
    return " ".join(f"{float(x):.7g}" for x in np.ravel(xs))


def _frame(origin, z, x):
    z = _unit(z)
    x = np.asarray(x, float) - (np.asarray(x, float) @ z) * z
    x = _unit(x)
    return _T(np.c_[x, np.cross(z, x), z], origin)


def _quat(R):
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, float).ravel())
    return q


def parse_rev(rev):
    """"A", or per-fault choices like "F1=B,F2=B,F3=A"."""
    return dict(item.split("=") for item in rev.split(",")) if "=" in rev else None


class Firmware:
    """Runs a device file's firmware behind the interface device.DeviceMCU has: readings, events, lcd and update()."""

    def __init__(self, world, model):
        self.w, self.m, cfg = world, model, world.cfg["firmware"]
        self.readings, self.events = dict(cfg["channels"]), []
        self.vars, self.state, self.entered, self.lcd, self.ring = {}, cfg["start"], 0.0, None, "off"
        self.sensors = []
        for s in cfg["sensors"]:
            j = model.joint(s["joint"]) if "joint" in s else None
            self.sensors.append(dict(s, adr=None if j is None else j.qposadr[0], when=_compile(s["when"]) if "when" in s else None,
                                     value=_compile(s["value"]) if "value" in s else None))
        self.rules = [dict(t, when=_compile(t["when"]) if "when" in t else None, after=_compile(t["after"]) if "after" in t else None,
                           do={k: _compile_value(v) for k, v in t.get("do", {}).items()}) for t in cfg["transitions"]]
        self.show_cfg = cfg["states"]
        self.mech = [(b, model.joint(b["name"]).qposadr[0], model.joint(b["name"]).dofadr[0]) for b in world.bodies if "snap" in b]
        self.lcd_tex = model.texture("dev_lcd").id if world.cfg.get("display") else None
        self.light = model.geom("dev_light").id if world.cfg.get("light") else None
        self._t = 0.0
        self._show(0.0)

    def _names(self):
        return {**self.readings, **self.vars}

    def _set(self, ch, value, t):
        if self.readings.get(ch) != value:
            self.readings[ch] = value
            self.events.append((float(t), ch, value))
            return ch
        return None

    def update(self, model, data):
        t = data.time
        changed = []
        for b, qa, da in self.mech:
            s = b["snap"]
            if "until_deg" in s and data.qpos[qa] > math.radians(s["until_deg"]):  # a latch: it acts only near shut
                data.qfrc_applied[da] = 0.0
                continue
            data.qfrc_applied[da] = s["nm"] * math.sin(math.pi / 2 * (data.qpos[qa] - math.radians(s["centre_deg"])) / math.radians(s["centre_deg"]))
        for s in self.sensors:
            if s["adr"] is not None:
                q = float(data.qpos[s["adr"]])
                if s["value"] is not None:
                    v = int(_eval(s["value"], {"q": q}))
                else:
                    v = int(bool(_eval(s["when"], {"q": q})))
                    if s.get("hysteresis") and abs(q - math.radians(15)) < s["hysteresis"]:
                        v = self.readings[s["channel"]]
            else:
                v = int(self.w.object_near(model, data, s))
            if self._set(s["channel"], v, t):
                changed.append(s["channel"])
        if self.state == "running":
            self.vars["left"] = max(0, self.vars.get("left", 0) - (t - self._t))
        self._t = t
        self._step(changed, t)
        self._show(t)
        if self.lcd_tex is not None and self.light is not None:
            colours = self.w.cfg["light"]["colours"]
            model.geom_rgba[self.light] = colours.get(self.ring, colours["off"])

    def _step(self, changed, t):
        for _ in range(4):  # a change can enable the next rule; a few are enough, and it can't loop forever
            fired = False
            for r in self.rules:
                if not r.get("any"):
                    frm = r["from"] if isinstance(r["from"], list) else [r["from"]]
                    if self.state not in frm:
                        continue
                elif self.state == r["to"]:
                    continue
                if r.get("event") and r["event"] not in changed:
                    continue
                if r["when"] is not None and not _eval(r["when"], self._names()):
                    continue
                if r["after"] is not None and t - self.entered < _eval(r["after"], self._names()) - self.vars.get("elapsed0", 0):
                    continue
                for k, code in r["do"].items():
                    v = _eval(code, self._names()) if not isinstance(code, str) else code
                    if k in self.readings:
                        if self._set(k, v, t):
                            changed.append(k)
                    else:
                        self.vars[k] = v
                if r["to"] != self.state or r.get("event"):
                    self.state, self.entered = r["to"], t
                fired = True
                changed = [c for c in changed if c != r.get("event")]
                break
            if not fired:
                return

    def _show(self, t):
        show = self.show_cfg[self.state]["show"]
        text = _format(show["lcd"], self._names())
        self.ring = show["ring"]
        if text == self.lcd:
            return
        self.lcd = text
        if self.lcd_tex is not None:
            rgb = generated.lcd_image(text or " ")[:, :, ::-1]
            adr = self.m.tex_adr[self.lcd_tex]
            self.m.tex_data[adr:adr + rgb.size] = rgb.ravel()

    def refresh_lcd(self, target):
        if self.lcd_tex is None:
            return
        if isinstance(target, mujoco.Renderer):
            if target._gl_context:
                target._gl_context.make_current()
            mujoco.mjr_uploadTexture(self.m, target._mjr_context, self.lcd_tex)
        else:
            target.update_texture(self.lcd_tex)

    def summary(self):
        return "  ".join(f"{k}:{v}" for k, v in self.readings.items()) + f"  LCD:[{self.lcd}] {self.ring}"


def _compile_value(v):
    """A do: value is an expression when it parses as one over names; a bare word like `start` is a string, and so is
    text that doesn't parse as an expression (`NO TUBE`). A quoted literal (`"'NO TUBE'"`) is a string too."""
    if isinstance(v, str) and re.fullmatch(r"[A-Za-z_:]+", v) and v != "time":
        return v
    try:
        return _compile(v)
    except SyntaxError:
        return v


def _format(template, names):
    def sub(match):
        expr, _, fmt = match.group(1).partition(":")
        value = _eval(_compile(expr), names)
        if isinstance(value, float) and not re.search(r"[.eEfgG%]", fmt):  # no precision asked: whole (a countdown's seconds)
            value = int(math.ceil(value))
        return format(value, fmt)
    return re.sub(r"\{([^{}]+)\}", sub, template)


@dataclass
class CadWorld:
    """The same interface as world.World, for a device from a device file."""
    name: str
    xml_path: str
    cfg: dict
    choices: dict
    params: dict
    placement: dict
    bodies: list
    base: pathlib.Path
    spec: object = None

    # --- what SimArm and the sim's tools call ---

    def make_mcu(self, model):
        return Firmware(self, model)

    def channel_of(self, part_id):
        return None

    def device_pose(self):
        return root_pose(self.cfg, self.placement)

    def device_geom_ids(self, model):
        roots = {model.body(r).id for r in self.cfg["roots"]} | {model.body(o["name"]).id for o in self.cfg.get("objects", [])}

        def on_device(b):
            while b > 0 and b not in roots:
                b = model.body_parentid[b]
            return b in roots

        return [g for g in range(model.ngeom) if on_device(model.geom_bodyid[g])]

    def random_placement(self, rng):
        """The device moved up to 3 cm and 12 deg on the bench."""
        return {"device": (float(rng.uniform(-0.03, 0.03)), float(rng.uniform(-0.03, 0.03)), float(rng.uniform(-12, 12))),
                "camera_pos": world_mod.NOMINAL_PLACEMENT["camera_pos"], "camera_target": world_mod.NOMINAL_PLACEMENT["camera_target"]}

    # --- where things are ---

    def mount(self, root):
        return self.cfg.get("mounts", {}).get(root, "clamped")

    @property
    def reposition_range(self):
        """reposition's bounds, (dx_mm, dy_mm, yaw_deg), from the device file's reposition section."""
        r = self.cfg.get("reposition", {})
        return (float(r.get("dx_mm", 0)), float(r.get("dy_mm", 0)), float(r.get("yaw_deg", 0)))

    def root_T(self, model, data, root):
        """4x4 of a root (its product frame) in the arm frame, now."""
        b = model.body(root).id
        return _T(data.xmat[b].reshape(3, 3).copy(), data.xpos[b].copy())

    def set_root_pose(self, model, data, root, dx=0.0, dy=0.0, yaw_deg=0.0):
        """Move a root by this much from where it is now, as a person bumping the device would: clamped or free."""
        T = self.root_T(model, data, root)
        R = _yaw(yaw_deg) @ T[:3, :3]
        p = T[:3, 3] + [dx, dy, 0.0]
        if self.mount(root) == "free":
            adr = model.joint(f"{root}_free").qposadr[0]
            data.qpos[adr:adr + 3], data.qpos[adr + 3:adr + 7] = p, _quat(R)
            data.qvel[model.joint(f"{root}_free").dofadr[0]:model.joint(f"{root}_free").dofadr[0] + 6] = 0
        else:
            b = model.body(root).id
            model.body_pos[b], model.body_quat[b] = p, _quat(R)
        mujoco.mj_forward(model, data)

    def object_near(self, model, data, sensor):
        """Whether an object's reference point is within a sensor's cylinder, in the sensor root's frame."""
        o = next(o for o in self.cfg["objects"] if o["name"] == sensor["object"])
        b = model.body(sensor["object"]).id
        at = data.xpos[b] + data.xmat[b].reshape(3, 3) @ (np.asarray(o["collar"]) * M)
        T = self.root_T(model, data, sensor["root"])
        local = T[:3, :3].T @ (at - T[:3, 3]) - np.asarray(sensor["near"]) * M
        return bool(np.hypot(local[0], local[1]) < sensor["radius_mm"] * M and abs(local[2]) < sensor["height_mm"] * M)

    def _body_point(self, model, data, body, p):
        """A product-frame point on a body, where it is now. A body's frame is parallel to the product's at rest."""
        b = model.body(body).id
        rest = self.body_rest[body]
        return data.xpos[b] + data.xmat[b].reshape(3, 3) @ ((np.asarray(p, float) * M) - rest)

    def _body_vec(self, model, data, body, v):
        return data.xmat[model.body(body).id].reshape(3, 3) @ np.asarray(v, float)

    def truth(self, model, data):
        return parts_from(self, lambda body, p: self._body_point(model, data, body, p), lambda body, v: self._body_vec(model, data, body, v),
                          lambda c: _state(self, model, data, c))

    def answer_key(self):
        """For scoring only, and never through a tool: what's on this device and what's wrong with it."""
        faults = self.cfg.get("faults", {})
        return {"device": self.name, "choices": self.choices,
                "faults": [{"id": k, "what": v["what"]} for k, v in faults.items() if self.choices.get(k) == "A"],
                "controls": [{"id": c["id"], "kind": c["kind"]} for c in self.cfg["controls"]]}


def _state(world, model, data, c):
    body = c.get("body")
    if not body:
        return {}
    q = float(data.qpos[model.joint(body).qposadr[0]])
    return {"q": q}


def root_pose(cfg, placement):
    p, (dx, dy, yaw) = cfg["placement"], placement["device"]
    z = appliance.TABLE_Z + cfg.get("stand_mm", 0) * M
    return _T(_yaw(p["yaw"] + yaw), [p["x"] * M + dx, p["y"] * M + dy, z])


def _manifest(base, cfg, rev):
    root = base / cfg["meshes"].format(rev=rev)
    return root, json.loads((root / "manifest.json").read_text())


class _Xml:
    """Collision bits. Arm: type 2, affinity 1. Desk: type 1, affinity 0. Device: 4, 3, so it meets the arm and the desk but
    not itself. Object: 8, 7, so it meets all of those. Bore ring: 16, 8, only objects. Plate with holes: 0, 2, only the arm."""

    def __init__(self, base, cfg, choices):
        self.base, self.cfg, self.choices = base, cfg, choices
        self.manifests = {r: _manifest(base, cfg, r) for r in set(choices.values()) | {"A", "B"}}
        self.assets, self.seen = [], set()
        self.materials = {}

    def find(self, part):
        for rev in ("A", "B"):
            root, m = self.manifests[rev]
            if part in m:
                return root, m[part]
        raise KeyError(f"no part {part} in the meshes")

    def _mesh(self, root, stl):
        name = f"m_{root.name}_{stl[:-4]}"
        if name not in self.seen:
            self.seen.add(name)
            self.assets.append(f'<mesh name="{name}" file="{root / stl}" scale="{M} {M} {M}"/>')
        return name

    def material(self, rgba):
        key = tuple(round(float(c), 3) for c in (rgba or (0.8, 0.8, 0.8, 1)))
        if key not in self.materials:
            self.materials[key] = f"cad_{len(self.materials)}"
            self.assets.append(f'<material name="{self.materials[key]}" rgba="{_f(*key)}" specular="0.15" shininess="0.2"/>')
        return self.materials[key]

    def primitive_stack(self, o):
        """An object's collision as primitives: fit in a bore has to be exact, and a mesh's pieces aren't."""
        c = np.asarray(o["collar_top"], float) * M
        out = ""
        for g in o.get("stack", []):
            r, z0, z1 = g
            mid = c + [0, 0, (z0 + z1) / 2 * M]
            out += (f'<geom type="cylinder" pos="{_f(*mid)}" size="{_f(r * M, abs(z1 - z0) / 2 * M)}" contype="8" conaffinity="7" group="3" '
                    f'solref="{appliance.CONTACT_SOLREF}" friction="0.8"/>')
        for g in o.get("boxes", []):
            jaw = _unit(g["x"])
            R = np.c_[jaw, np.cross([0, 0, 1], jaw), [0, 0, 1]]
            mid = c + np.asarray(g["at"]) * M
            out += (f'<geom type="box" pos="{_f(*mid)}" quat="{_f(*_quat(R))}" size="{_f(*(np.asarray(g["half"]) * M))}" contype="8" conaffinity="7" group="3" '
                    f'solref="{appliance.CONTACT_SOLREF}" friction="0.8"/>')
        return out

    def ring(self, r):
        """A bore as a ring of boxes whose inner faces lie on its diameter: what an object sits in."""
        c, rad, n = np.asarray(r["centre"], float) * M, r["id"] / 2 * M, r.get("n", 24)
        wall, z0, z1 = r.get("wall", 3.0) * M, r["z"][0] * M, r["z"][1] * M
        out = ""
        for i in range(n):
            th = 2 * math.pi * i / n
            u = np.array([math.cos(th), math.sin(th), 0])
            R = np.c_[u, [-u[1], u[0], 0], [0, 0, 1]]
            at = c[:2] + (rad + wall / 2) * u[:2]
            half_w = (rad + wall) * math.tan(math.pi / n)
            out += (f'<geom type="box" pos="{_f(at[0], at[1], (z0 + z1) / 2)}" quat="{_f(*_quat(R))}" size="{_f(wall / 2, half_w, (z1 - z0) / 2)}" contype="16" conaffinity="8" '
                    f'group="3" solref="{appliance.CONTACT_SOLREF}" friction="0.5"/>')
        return out

    def part(self, part, offset, contype=4, conaffinity=3, rgba=None, collide=True):
        root, m = self.find(part)
        pos = _f(*offset)
        out = [f'<geom class="deco" type="mesh" mesh="{self._mesh(root, m["file"])}" pos="{pos}" material="{self.material(rgba or m["rgba"])}"/>']
        if collide:
            for stl in m.get("collision") or [m["file"]]:
                out.append(f'<geom type="mesh" mesh="{self._mesh(root, stl)}" pos="{pos}" contype="{contype}" conaffinity="{conaffinity}" group="3" '
                           f'solref="{appliance.CONTACT_SOLREF}" friction="0.6"/>')
        return "".join(out)

    def box_of(self, parts):
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for part in parts:
            _, m = self.find(part)
            lo, hi = np.minimum(lo, m["min"]), np.maximum(hi, m["max"])
        return lo, hi


def _inertial(box, mass, offset=np.zeros(3)):
    lo, hi = np.asarray(box[0]) * M, np.asarray(box[1]) * M
    c, s = (lo + hi) / 2 + offset, hi - lo
    i = mass / 12 * np.array([s[1] ** 2 + s[2] ** 2, s[0] ** 2 + s[2] ** 2, s[0] ** 2 + s[1] ** 2])
    return f'<inertial pos="{_f(*c)}" mass="{mass}" diaginertia="{_f(*i)}"/>'


def _body_xml(x, b, params):
    j, name = b["joint"], b["name"]
    anchor = np.asarray(j["anchor"], float) * M
    geoms = ""
    for part in b.get("parts", []):
        geoms += x.part(part, -anchor, collide=not b.get("collide_geoms_only"))
    boxes = b.get("parts") or []
    for g in b.get("geoms", []):
        tail = f'contype="4" conaffinity="3" solref="{appliance.CONTACT_SOLREF}" friction="0.6"'
        show = f'rgba="{_f(*g["rgba"])}"' if "rgba" in g else 'group="3"'
        if g["type"] == "box":  # centre, half sizes, and its x and z axes
            z, xx = _unit(g["z"]), _unit(g["x"])
            R = np.c_[xx, np.cross(z, xx), z]
            geoms += (f'<geom type="box" pos="{_f(*(np.asarray(g["pos"]) * M - anchor))}" quat="{_f(*_quat(R))}" size="{_f(*(np.asarray(g["half"]) * M))}" '
                      f'mass="{g.get("mass", 0.001)}" {show} {tail}/>')
        else:
            a, c = np.asarray(g["fromto"][:3]) * M - anchor, np.asarray(g["fromto"][3:]) * M - anchor
            geoms += f'<geom type="{g["type"]}" fromto="{_f(*a, *c)}" size="{g["radius"] * M}" mass="{g.get("mass", 0.001)}" {show} {tail}/>'
    kind = j["type"]
    rng = np.asarray(j["range"], float) * (M if kind == "slide" else math.pi / 180)
    attrs = f'range="{_f(*rng)}" damping="{j.get("damping", 0)}" frictionloss="{j.get("frictionloss", 0)}" armature="{j.get("armature", 0)}"'
    if "stiffness" in j:
        k = j["stiffness"]
        attrs += f' stiffness="{k}" springref="{-j.get("preload_n", 0) / k:.6f}"'
    inertial = _inertial(x.box_of(boxes), j.get("mass", 0.02), -anchor) if boxes else ""
    grav = ' gravcomp="1"' if kind == "slide" or b.get("gravcomp") else ""
    return (f'<body name="{name}" pos="{_f(*anchor)}"{grav}>{inertial}'
            f'<joint name="{name}" type="{kind}" axis="{_f(*_unit(j["axis"]))}" {attrs} solreflimit="0.004 1" solimplimit="0.99 0.999 0.001" '
            f'solreffriction="0.004 1" solimpfriction="0.99 0.999 0.001"/>{geoms}</body>')


def build_cad_world(path, rev="B", placement=None, mounts=None):
    """path: a device file. rev: a name in its revs, or fault choices like "F1=B,F2=B,F3=A". mounts: {root: "clamped" |
    "free"} over the file's, e.g. to let the arm push a root the file clamps."""
    path = pathlib.Path(path).resolve()
    base, cfg = path.parent, yaml.safe_load(path.read_text())
    if mounts:
        cfg["mounts"] = {**cfg.get("mounts", {}), **mounts}
    choices = parse_rev(rev) or cfg["revs"][rev]
    params, parts = {}, {}
    for fault, opts in cfg.get("faults", {}).items():
        chosen = opts[choices[fault]]
        params.update(chosen.get("params", {}))
        parts.update(chosen.get("parts", {}))
    params.update(cfg.get("params") or {})  # a patched device's own values (a travel its new geometry gives) win over its revision's
    params.update(parts)
    params.update({f: c for f, c in choices.items()})
    if cfg.get("firmware"):  # firmware faults are data too: a dead switch, a wrong channel or default, a broken interlock
        cfg["firmware"] = _subst(cfg["firmware"], params)
    x = _Xml(base, cfg, choices)
    placement = placement or world_mod.NOMINAL_PLACEMENT
    T = root_pose(cfg, placement)
    bodies = [_expand(b, params) for b in cfg["bodies"]]
    world_xml, boxes, rest = "", {}, {}
    stand = cfg.get("stand_mm", 0) * M
    if stand:
        world_xml += (f'<body name="_stand_board"><geom name="_stand_board" type="box" pos="{_f(0.385, 0, appliance.TABLE_Z + stand / 2)}" size="{_f(0.21, 0.40, stand / 2)}" '
                      f'material="desk" contype="1" conaffinity="0" solref="{appliance.CONTACT_SOLREF}" friction="0.6"/></body>')
    for root, r in cfg["roots"].items():
        rp = [_named(p, params) for p in r["parts"]]
        mount = cfg.get("mounts", {}).get(root, "clamped")
        joint = f'<freejoint name="{root}_free"/>' if mount == "free" else ""
        arm_only = set(r.get("arm_only", []))  # holes matter to objects: they meet the rings, and the arm meets these
        geoms = "".join(x.part(p, (0, 0, 0), *((0, 2) if p in arm_only else (4, 3))) for p in rp)
        geoms += "".join(x.part(p, (0, 0, 0), collide=False) for p in r.get("visual_only", []))
        geoms += "".join(x.ring(_resolve(g, params)) for g in r.get("rings", []))
        kids = "".join(_body_xml(x, b, params) for b in bodies if b["root"] == root)
        boxes[root] = x.box_of(rp)
        rest[root] = np.zeros(3)
        extra = _screen_xml(x, cfg, root)
        world_xml += (f'<body name="{root}" pos="{_f(*T[:3, 3])}" quat="{_f(*_quat(T[:3, :3]))}">{joint}{_inertial(boxes[root], r["mass_kg"])}'
                      f'{geoms}{extra}{kids}</body>')
    for b in bodies:
        rest[b["name"]] = np.asarray(b["joint"]["anchor"], float) * M
    for o in cfg.get("objects", []):
        b = x.box_of([o["part"]])
        rest[o["name"]] = np.zeros(3)
        world_xml += (f'<body name="{o["name"]}" pos="{_f(*T[:3, 3])}" quat="{_f(*_quat(T[:3, :3]))}"><freejoint name="{o["name"]}_free"/>{_inertial(b, o["mass_kg"])}'
                      f'{x.part(o["part"], (0, 0, 0), collide=False, rgba=o.get("rgba"))}{x.primitive_stack(o)}</body>')
    robot_assets = robot.ASSETS
    generated.save(os.path.join(robot_assets, f"_dev_{cfg['name']}_lcd.png"), cv2.imencode(".png", generated.lcd_image(" "))[1].tobytes())
    assets = "\n".join(x.assets)
    if cfg.get("display"):
        assets += (f'<texture name="dev_lcd" type="2d" file="_dev_{cfg["name"]}_lcd.png"/>'
                   '<material name="dev_lcd" texture="dev_lcd" specular="0.6" shininess="0.9" emission="0.35"/>')
    world_mod.vision.write_textures(robot_assets)
    generated.save(os.path.join(robot_assets, "_wood.png"), world_mod._wood_png())
    tag = "_".join(f"{k}{v}" for k, v in sorted(choices.items())) + "_" + "_".join(f"{cfg.get('mounts', {}).get(r, 'clamped')[0]}" for r in cfg["roots"])
    import hashlib
    tag += "_" + hashlib.sha1(json.dumps(placement, sort_keys=True).encode()).hexdigest()[:6]
    xml = world_mod.scene_xml(cfg["name"], placement, assets, world_xml)
    out = os.path.join(robot_assets, f"_world_{cfg['name']}_{tag}.xml")
    generated.save(out, xml.encode())
    w = CadWorld(cfg["name"], out, cfg, choices, params, placement, bodies, base)
    w.body_rest, w.root_boxes, w.table_z = rest, boxes, appliance.TABLE_Z + stand
    return w


def _subst(item, params):
    """$name in a device file's firmware: a whole value "$name" becomes the choice's value, of its own type (a number, a
    list, a channel map); inside a longer string (an expression, a template, a channel name), its text. Keys too, so a
    channel's name can be a fault. A $name no choice defines is an error, not a silent string."""
    if isinstance(item, dict):
        return {_subst(k, params): _subst(v, params) for k, v in item.items()}
    if isinstance(item, list):
        return [_subst(v, params) for v in item]
    if isinstance(item, str) and "$" in item:
        if re.fullmatch(r"\$[A-Za-z_]\w*", item):
            if item[1:] not in params:
                raise KeyError(f"firmware uses {item}, which no fault choice defines")
            return params[item[1:]]

        def one(m):
            if m.group(1) not in params:
                raise KeyError(f"firmware uses ${m.group(1)}, which no fault choice defines")
            return str(params[m.group(1)])
        return re.sub(r"\$([A-Za-z_]\w*)", one, item)
    return item


def _named(part, params):
    """A part name in a device file: `$key` from the fault choices, `{F1}` a fault's choice."""
    if part.startswith("$"):
        return params[part[1:]]
    return part.format(**params) if "{" in part else part


def _expand(b, params):
    b = _resolve({k: v for k, v in b.items() if k != "parts"}, params) | {"parts": [_named(p, params) for p in b.get("parts", [])]}
    return b


def _screen_xml(x, cfg, root):
    out = ""
    d = cfg.get("display")
    if d and d.get("root") == root:
        z, up = _unit(d["normal"]), _unit(d["up"])
        y = up
        xx = np.cross(y, z)
        out += (f'<geom name="dev_screen" class="deco" type="box" pos="{_f(*(np.asarray(d["centre"]) * M + z * 0.0002))}" quat="{_f(*_quat(np.c_[xx, y, z]))}" '
                f'size="{_f(d["size"][0] / 2 * M, d["size"][1] / 2 * M, 0.0001)}" material="dev_lcd"/>')
    li = cfg.get("light")
    if li and li.get("root") == root:
        c = np.asarray(li["centre"]) * M
        out += (f'<geom name="dev_light" class="deco" type="cylinder" pos="{_f(*c)}" size="{_f(li["radius"] * M, 0.0005)}" rgba="0.1 0.1 0.1 1"/>')
    return out
