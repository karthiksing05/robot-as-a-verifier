"""Quick PNG renders of the assembly, for a person or the model to eyeball a revision (no GUI needed)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

from .build import Built  # noqa: E402

COLORS = {"shell": "#c9c6bf", "insert": "#3b6ea8", "moving": "#e08a2c", "changed": "#d23c3c"}
VIEWS = {"iso": (28, -60), "front": (5, -90), "top": (89, -90)}


def _tris(shape, tol=0.4):
    verts, tris = shape.copy().tessellate(tol, 0.3)     # a copy: meshing stores the mesh on the shape it's given
    v = np.array([p.toTuple() for p in verts])
    return v[np.array(tris)] if len(tris) else np.zeros((0, 3, 3))


def _shade(tris, color):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([-0.4, -0.6, 0.7]) / np.linalg.norm([-0.4, -0.6, 0.7])
    k = 0.55 + 0.45 * np.clip(np.abs(n @ light), 0, 1)
    base = np.array(matplotlib.colors.to_rgb(color))
    return np.clip(base[None, :] * k[:, None], 0, 1)


def render(b: Built, path: str | Path, highlight: set[str] = frozenset(), views=("iso", "front", "top")) -> Path:
    groups = [(_tris(b.shell, 0.8), COLORS["shell"])]
    if b.base is not None:
        groups.append((_tris(b.base, 0.8), "#9e9b94"))
    for fid, p in b.placed.items():
        groups.append((_tris(p.insert), COLORS["changed" if fid in highlight else "insert"]))
        if p.moving is not None:
            groups.append((_tris(p.moving), COLORS["moving"]))
    allv = np.concatenate([g[0].reshape(-1, 3) for g in groups])
    lo, hi = allv.min(0), allv.max(0)
    mid, r = (lo + hi) / 2, (hi - lo).max() / 2
    fig = plt.figure(figsize=(6 * len(views), 6), dpi=110)
    for i, view in enumerate(views):
        ax = fig.add_subplot(1, len(views), i + 1, projection="3d")
        # one collection, so every triangle is depth-sorted against every other (separate ones aren't)
        tris = np.concatenate([g[0] for g in groups if len(g[0])])
        cols = np.concatenate([_shade(g[0], g[1]) for g in groups if len(g[0])])
        ax.add_collection3d(Poly3DCollection(tris, facecolors=cols, edgecolor="none"))
        for fid, p in b.placed.items():
            x, y, z = p.plane.toWorldCoords((0, 0, 0)).toTuple()
            nx, ny, nz = p.plane.zDir.toTuple()
            ax.text(x + nx * 25, y + ny * 25, z + nz * 25, fid, fontsize=7, color="#222")
        ax.set_xlim(mid[0] - r, mid[0] + r)
        ax.set_ylim(mid[1] - r, mid[1] + r)
        ax.set_zlim(mid[2] - r, mid[2] + r)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(*VIEWS[view])
        ax.set_axis_off()
        ax.set_title(f"{b.spec.name} rev {b.spec.rev} - {view}", fontsize=10)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path)
    plt.close(fig)
    return path


def render_parts(parts: dict, path: str | Path, highlight=frozenset(), fixed=frozenset(), title: str = "",
                 views=("iso", "front", "top")) -> Path:
    """Render any product given as named solids: fixed body grey, highlighted (changed) parts red, the rest blue."""
    groups = []
    for name, s in parts.items():
        color = COLORS["changed"] if name in highlight else COLORS["shell"] if name in fixed else COLORS["insert"]
        t = _tris(s, 0.8 if name in fixed else 0.4)
        if len(t):
            groups.append((t, color))
    allv = np.concatenate([g[0].reshape(-1, 3) for g in groups])
    lo, hi = allv.min(0), allv.max(0)
    mid, r = (lo + hi) / 2, (hi - lo).max() / 2
    tris = np.concatenate([g[0] for g in groups])
    cols = np.concatenate([_shade(g[0], g[1]) for g in groups])
    fig = plt.figure(figsize=(6 * len(views), 6), dpi=110)
    for i, view in enumerate(views):
        ax = fig.add_subplot(1, len(views), i + 1, projection="3d")
        ax.add_collection3d(Poly3DCollection(tris, facecolors=cols, edgecolor="none"))
        ax.set_xlim(mid[0] - r, mid[0] + r)
        ax.set_ylim(mid[1] - r, mid[1] + r)
        ax.set_zlim(mid[2] - r, mid[2] + r)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(*VIEWS[view])
        ax.set_axis_off()
        ax.set_title(f"{title} - {view}".strip(" -"), fontsize=10)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path)
    plt.close(fig)
    return path
