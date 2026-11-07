"""What perception hands to the planner: one record per functional part of the device.

The format joins two papers. GAPartNet (Geng et al., CVPR 2023) gives each part a class
and a pose in a frame defined per class, so a short rule per class turns the pose into
arm motion. SceneFun3D (Delitzas et al., CVPR 2024) gives each part an affordance label
and a motion: translation or rotation, an axis, and an origin.

Part frame conventions (all kinds): origin on the part, z = outward surface normal.
  button   origin: centre of the cap top. x: any in-plane direction.
  slider   origin: centre of the knob top. x: the slot axis. state: knob position 0..1 along +x.
  dial     origin: centre of the knob top (under the fin). x: the fin's long axis. state: 0.
  toggle   origin: the hinge, on the base top. x: the way the lever tip leans now. state: +1.
  door     origin: centre of the push pad. x: from the hinge toward the free edge.
  knob     like dial, but no fin, so turning it needs a pinch grip.
  display  origin: centre of the screen. No motion.
Where x has no physical sign (slider, dial), canonical_x() picks one, so truth and
perception agree. Per-kind extras go in meta, under the keys device.truth() uses.
"""
from dataclasses import dataclass, field

import numpy as np

KINDS = ("button", "slider", "dial", "toggle", "door", "knob", "display")
# SceneFun3D labels. Their example of tip_push is a light switch, so toggles are tip_push too.
AFFORDANCE = {"button": "tip_push", "slider": "tip_push", "dial": "rotate", "toggle": "tip_push",
              "door": "tip_push", "knob": "rotate", "display": "none"}
# The no-thumbs rule: only a fingertip pad may touch the product.
GRIP = {"knob": "pinch"}


@dataclass
class Part:
    id: str                 # "button_1", "slider_1", ...
    kind: str               # one of KINDS
    T: np.ndarray           # 4x4 part frame in the arm frame (see module docstring)
    size: np.ndarray        # extent along the part frame's x, y, z (m); z is height above the surface
    motion: str = ""        # "translation", "rotation", or "" (display)
    axis: np.ndarray = None   # unit vector, the way the part moves when actuated (arm frame)
    origin: np.ndarray = None # a point on the motion axis (arm frame)
    state: float = 0.0
    range: tuple = (0.0, 0.0)  # how far it can move from here along +axis (m or rad); (0, 0) if unknown
    score: float = 1.0      # classifier confidence, 0..1
    points: np.ndarray = None  # Nx3 measured points, for overlays
    meta: dict = field(default_factory=dict)  # per-kind extras, e.g. slot ends, fin length

    @property
    def pos(self):
        return self.T[:3, 3]

    @property
    def normal(self):
        return self.T[:3, 2]

    @property
    def x(self):
        return self.T[:3, 0]

    @property
    def affordance(self):
        return AFFORDANCE[self.kind]

    @property
    def grip(self):
        return GRIP.get(self.kind, "tip")


def canonical_x(v, n):
    """v projected onto the plane normal to n, signed to point left and up as seen on that plane.

    The reference is +y plus +z, each projected onto the plane. On a sloped panel facing the arm
    the sign flips 45 deg from both the across and the up-slope directions, so a slider along
    either, or a dial at any detent, keeps its sign under small yaw and measurement noise."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    flat = lambda a: np.asarray(a, float) - (np.asarray(a, float) @ n) * n
    v = flat(v) / np.linalg.norm(flat(v))
    ref = sum(r / np.linalg.norm(r) for r in (flat([0, 1, 0]), flat([0, 0, 1])) if np.linalg.norm(r) > 1e-6)
    return v if v @ ref >= 0 else -v


def frame(origin, z, x):
    """4x4 frame from an origin, a z axis and a rough x axis (made orthogonal to z)."""
    z = np.asarray(z, float) / np.linalg.norm(z)
    x = np.asarray(x, float) - (np.asarray(x, float) @ z) * z
    x /= np.linalg.norm(x)
    T = np.eye(4)
    T[:3, :3] = np.c_[x, np.cross(z, x), z]
    T[:3, 3] = origin
    return T


def match(perceived, truth, max_dist=0.015):
    """Pair each true part with the nearest perceived part of any kind within max_dist (m).

    Returns (pairs, missed_truth, extra_perceived), pairs as (truth, perceived)."""
    pairs, used = [], set()
    for t in truth:
        best = min(((np.linalg.norm(p.pos - t.pos), i) for i, p in enumerate(perceived) if i not in used),
                   default=(np.inf, None))
        if best[0] <= max_dist:
            pairs.append((t, perceived[best[1]]))
            used.add(best[1])
    missed = [t for t in truth if all(t is not a for a, _ in pairs)]
    extra = [p for i, p in enumerate(perceived) if i not in used]
    return pairs, missed, extra
