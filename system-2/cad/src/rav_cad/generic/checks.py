"""Robot-centred checks on any product: a dict of named solids in one frame (mm) and its Tags.

What they ask, in the order a fix should be judged:

- valid:   each part a fix touches is one valid solid
- prints:  each part a fix touches fits the printer bed
- scope:   (with `before`) only reprintable parts changed, all of one control, and something did change
- at rest: no two parts overlap
- fit:     each sliding pair keeps at least min_clearance, measured at mid-travel
- motion:  moving parts, stepped through their travel or swing, never run into another part
- reach:   a fingertip cylinder can get from outside to each control's contact without hitting anything
- grip:    a pull control catches the fingertip when it pulls (a hook), so nothing needs a pinch

Not checked yet: wall thickness (min_wall is in the tags but needs a ray-sampled thickness test), and anything
that needs physics (spring force, latching).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

import cadquery as cq

from ..parametric.geom import distance, overlap_volume, signature
from .tags import Control, Tags

TOUCH_EPS = 0.05          # mm^3 of overlap treated as touching, not colliding
REACH_MM = 60.0           # how far out the fingertip starts
STOP_SHORT_MM = 0.5       # the fingertip stops this far short of a press contact
PULL_MM = 6.0             # how far a pull is tried


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    control: str | None = None
    known: bool = False       # failed in the tested revision too, on another control: not this fix's doing


def failures(results: list[Result]) -> list[str]:
    return [f"{r.name}: {r.detail}" for r in results if not r.ok]


def as_json(results: list[Result]) -> list[dict]:
    return [asdict(r) for r in results]


def _overlaps(a: cq.Shape, b: cq.Shape) -> bool:
    ba, bb = a.BoundingBox(), b.BoundingBox()
    if ba.xmax < bb.xmin or bb.xmax < ba.xmin or ba.ymax < bb.ymin or bb.ymax < ba.ymin or ba.zmax < bb.zmin or bb.zmax < ba.zmin:
        return False
    return overlap_volume(a, b) > TOUCH_EPS


def _fused(parts: dict[str, cq.Shape], names: tuple[str, ...]) -> cq.Shape | None:
    shapes = [parts[n] for n in names if n in parts]
    if not shapes:
        return None
    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _pose(shape: cq.Shape, c: Control, fraction: float) -> cq.Shape:
    m = c.motion
    if m.type == "slide":
        return shape.translate(cq.Vector(*m.axis) * (m.travel * fraction))
    p = cq.Vector(*m.point)
    return shape.rotate(p, p + cq.Vector(*m.axis), m.degrees * fraction)


def _finger(start: cq.Vector, direction: cq.Vector, length: float, d: float) -> cq.Shape:
    return cq.Solid.makeCylinder(d / 2, length, pnt=start, dir=direction)


def _changed(before: dict[str, cq.Shape], after: dict[str, cq.Shape]) -> list[str]:
    names = set(before) | set(after)
    return sorted(n for n in names if n not in before or n not in after or signature(before[n]) != signature(after[n]))


def run(parts: dict[str, cq.Shape], tags: Tags, before: dict[str, cq.Shape] | None = None, target: str | None = None,
        steps: int = 4) -> list[Result]:
    """Every check, as a list of results.

    To judge a fix, pass `before` (the revision the robot tested) and `target` (the control the fix is for). A check
    that already failed in `before` on some other control is then reported with known=True and doesn't block: one
    fix shouldn't be refused for a fault it isn't about. Failures on the target control always block."""
    out = _run(parts, tags, before, steps)
    if before is None:
        return out
    already = {r.name for r in _run(before, tags, None, steps) if not r.ok}
    for r in out:
        if not r.ok and r.name in already and (r.control is None or r.control != target) and not r.name.startswith("fix "):
            r.ok, r.known = True, True
            r.detail = f"already failing in the tested revision, not this fix's doing: {r.detail}"
    return out


def _run(parts: dict[str, cq.Shape], tags: Tags, before: dict[str, cq.Shape] | None, steps: int) -> list[Result]:
    out: list[Result] = []
    add = lambda name, ok, detail="", control=None: out.append(Result(name, bool(ok), detail, control))  # noqa: E731

    missing = tags.missing(set(parts))
    if missing:
        add("tags match the model", False, f"the tag file names parts the model doesn't have: {', '.join(missing)}")
        return out

    changed = _changed(before, parts) if before is not None else None
    judged = changed if changed is not None else sorted(tags.reprintable() & set(parts))

    # valid and printable
    bed = sorted(tags.bed)
    for name in judged:
        if name not in parts:
            add(f"{name}: still exists", False, "a fix removed this part")
            continue
        s = parts[name]
        solids = len(s.Solids())
        add(f"{name}: one valid solid", s.isValid() and solids == 1,
            "" if s.isValid() and solids == 1 else f"{solids} solids, valid={s.isValid()}", tags.owner(name))
        bb = s.BoundingBox()
        size = sorted((bb.xlen, bb.ylen, bb.zlen))
        add(f"{name}: fits the printer", all(a <= b for a, b in zip(size, bed)),
            f"{bb.xlen:.0f} x {bb.ylen:.0f} x {bb.zlen:.0f} mm on a {' x '.join(f'{b:g}' for b in tags.bed)} bed", tags.owner(name))

    # scope of a fix
    if changed is not None:
        fixed = [n for n in changed if n in tags.fixed]
        stray = [n for n in changed if n not in tags.reprintable() and n not in tags.fixed]
        owners = sorted({tags.owner(n) for n in changed if tags.owner(n)})
        add("fix changes something", bool(changed), "" if changed else "no part differs from the tested revision")
        add("fix leaves the body alone", not fixed, f"changes {', '.join(fixed)}, which means reprinting the body" if fixed else "")
        add("fix changes only reprintable parts", not stray, f"changes {', '.join(stray)}" if stray else ", ".join(changed))
        add("fix stays within one control", len(owners) <= 1, f"touches {', '.join(owners)}" if len(owners) > 1 else "")

    # at rest: nothing overlaps
    hits = [f"{a} / {b}" for a, b in combinations(sorted(parts), 2) if _overlaps(parts[a], parts[b])]
    add("parts don't overlap at rest", not hits, "; ".join(hits))

    for c in tags.controls.values():
        moving = _fused(parts, c.moving)
        others = {n: s for n, s in parts.items() if n not in c.moving}

        # fit: sliding clearance at mid-travel
        if c.fit and c.motion and c.motion.type == "slide":
            a, b = c.fit
            sa = _pose(parts[a], c, 0.5) if a in c.moving else parts[a]
            sb = _pose(parts[b], c, 0.5) if b in c.moving else parts[b]
            gap = distance(sa, sb)
            add(f"{c.id}: sliding clearance", gap >= tags.min_clearance - 1e-3,
                f"{gap:.2f} mm between {a} and {b}, needs {tags.min_clearance:g}", c.id)

        # motion: stepped through its travel or swing
        if moving is not None and c.motion is not None:
            hit = []
            for k in range(1, steps + 1):
                posed = _pose(moving, c, k / steps)
                hit += [f"{n} at {k / steps:.0%}" for n, s in others.items() if _overlaps(posed, s)]
            what = f"{c.motion.travel:g} mm" if c.motion.type == "slide" else f"{c.motion.degrees:g} degrees"
            add(f"{c.id}: moves freely", not hit, f"hits {', '.join(hit)}" if hit else f"clear through {what}", c.id)

        # reach, and for a pull control, a hook to pull against
        if c.contact is None or c.approach is None:
            continue
        contact, d = cq.Vector(*c.contact), cq.Vector(*c.approach)
        if c.skill == "pull":
            path = _finger(contact - d * REACH_MM, d, REACH_MM, tags.fingertip_d)
            blocked = [n for n, s in parts.items() if _overlaps(path, s)]
            add(f"{c.id}: fingertip reaches the handle", not blocked,
                f"a {tags.fingertip_d:g} mm fingertip hits {', '.join(blocked)} on the way in" if blocked else "", c.id)
            # pulled from where it got to: the swept fingertip has to catch the moving part, or nothing opens it
            pull = cq.Vector(*c.pull)
            sweep = _finger(contact, pull, PULL_MM, tags.fingertip_d).fuse(
                cq.Solid.makeSphere(tags.fingertip_d / 2, contact + pull * PULL_MM, angleDegrees1=-90, angleDegrees2=90))
            caught = not blocked and moving is not None and _overlaps(sweep, moving)
            why = ("the fingertip can't get into place first" if blocked
                   else f"pulling {PULL_MM:g} mm catches nothing: it would need a pinch or a grip")
            add(f"{c.id}: opens with a hooked fingertip", caught, "" if caught else why, c.id)
        else:
            length = REACH_MM - STOP_SHORT_MM
            path = _finger(contact - d * REACH_MM, d, length, tags.fingertip_d)
            blocked = [n for n, s in others.items() if _overlaps(path, s)]
            add(f"{c.id}: fingertip reaches it", not blocked,
                f"a {tags.fingertip_d:g} mm fingertip hits {', '.join(blocked)} on the way in" if blocked else "", c.id)
    return out
