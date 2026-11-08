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
SLIDE_STEP_MM = 0.5       # a sliding hook moves in this many mm at a time until it touches
BACK_OFF_MM = 0.5         # and backs off this much before it pulls
HOOK_CORE_MM = 2.0        # the column over a hook's centre that must meet the control for the pull to catch it


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


def place_travel(shape: cq.Shape, c: Control) -> float:
    """How far a placed part still has to go for its leading end to reach the seat (0 when it's already there)."""
    m = c.motion
    a = cq.Vector(*m.axis)
    i = max(range(3), key=lambda k: abs(m.axis[k]))
    if abs(m.axis[i]) > 0.9999:                      # along a coordinate axis: the bounding box is exact
        bb = shape.BoundingBox()
        lead = (bb.xmax, bb.ymax, bb.zmax)[i] if m.axis[i] > 0 else -(bb.xmin, bb.ymin, bb.zmin)[i]
    else:
        lead = max(cq.Vector(*v.toTuple()).dot(a) for v in shape.Vertices())
    return max(0.0, cq.Vector(*m.seat).dot(a) - lead)


def _pose(shape: cq.Shape, c: Control, fraction: float, travel: float | None = None) -> cq.Shape:
    m = c.motion
    if m.type in ("slide", "place"):
        return shape.translate(cq.Vector(*m.axis) * ((m.travel if travel is None else travel) * fraction))
    p = cq.Vector(*m.point)
    return shape.rotate(p, p + cq.Vector(*m.axis), m.degrees * fraction)


def _finger(start: cq.Vector, direction: cq.Vector, length: float, d: float) -> cq.Shape:
    return cq.Solid.makeCylinder(d / 2, length, pnt=start, dir=direction)


def _changed(before: dict[str, cq.Shape], after: dict[str, cq.Shape]) -> list[str]:
    names = set(before) | set(after)
    return sorted(n for n in names if n not in before or n not in after or signature(before[n]) != signature(after[n]))


def run(parts: dict[str, cq.Shape], tags: Tags, before: dict[str, cq.Shape] | None = None, target: str | None = None,
        steps: int = 4, quick: bool = False) -> list[Result]:
    """Every check, as a list of results.

    To judge a fix, pass `before` (the revision the robot tested) and `target` (the control the fix is for). A check
    that already failed in `before` on some other control is then reported with known=True and doesn't block: one
    fix shouldn't be refused for a fault it isn't about. Failures on the target control always block.

    `quick` (with `before`) checks only what the change can affect: overlaps involving changed parts, and the
    controls that own a changed part or are the target. It's for the analyst's iterations; the full run gates apply."""
    if quick and before is not None:
        changed = set(_changed(before, parts))
        controls = {c.id for c in tags.controls.values()
                    if c.id == target or changed & (set(c.parts) | set(c.moving) | set(c.fit or ()) | set(c.actuates))}
        return _run(parts, tags, before, steps, focus=(changed, controls))
    out = _run(parts, tags, before, steps)
    if before is None:
        return out
    already = {r.name for r in _run(before, tags, None, steps) if not r.ok}
    for r in out:
        if not r.ok and r.name in already and (r.control is None or r.control != target) and not r.name.startswith("fix "):
            r.ok, r.known = True, True
            r.detail = f"already failing in the tested revision, not this fix's doing: {r.detail}"
    return out


def _run(parts: dict[str, cq.Shape], tags: Tags, before: dict[str, cq.Shape] | None, steps: int,
         focus: tuple[set[str], set[str]] | None = None) -> list[Result]:
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
    pairs = combinations(sorted(parts), 2)
    if focus is not None:
        pairs = [(a, b) for a, b in pairs if a in focus[0] or b in focus[0]]
    hits = [f"{a} / {b}" for a, b in pairs if _overlaps(parts[a], parts[b])]
    add("parts don't overlap at rest", not hits, "; ".join(hits))

    for c in tags.controls.values():
        if focus is not None and c.id not in focus[1]:
            continue
        moving = _fused(parts, c.moving)
        others = {n: s for n, s in parts.items() if n not in c.moving}
        obstacles = {n: s for n, s in others.items() if n not in c.actuates}   # pressing the switch isn't a collision

        # fit: sliding clearance at mid-travel
        if c.fit and c.motion and c.motion.type == "slide":
            a, b = c.fit
            sa = _pose(parts[a], c, 0.5) if a in c.moving else parts[a]
            sb = _pose(parts[b], c, 0.5) if b in c.moving else parts[b]
            gap = distance(sa, sb)
            add(f"{c.id}: sliding clearance", gap >= tags.min_clearance - 1e-3,
                f"{gap:.2f} mm between {a} and {b}, needs {tags.min_clearance:g}", c.id)

        # motion: stepped through its travel or swing; a placed part is lowered until it reaches its seat
        if moving is not None and c.motion is not None:
            travel = place_travel(moving, c) if c.motion.type == "place" else None
            hit = []
            for k in range(1, steps + 1):
                posed = _pose(moving, c, k / steps, travel)
                hit += [f"{n} at {k / steps:.0%}" for n, s in obstacles.items() if _overlaps(posed, s)]
            if c.motion.type == "place":
                name = f"{c.id}: goes into its seat"
                what = "already seated" if not travel else f"clear through the last {travel:.1f} mm to its seat"
                detail = f"hits {', '.join(hit)} {travel:.1f} mm short of its seat" if hit else what
            else:
                name = f"{c.id}: moves freely"
                what = f"{c.motion.travel:g} mm" if c.motion.type == "slide" else f"{c.motion.degrees:g} degrees"
                detail = f"hits {', '.join(hit)}" if hit else f"clear through {what}"
            add(name, not hit, detail, c.id)

        # reach, and for a pull control, a hook to pull against
        if c.contact is None or c.approach is None:
            continue
        contact, d = cq.Vector(*c.contact), cq.Vector(*c.approach)
        probe = c.probe_d or tags.fingertip_d
        tool = "fingertip" if c.probe_d is None else f"{probe:g} mm hook"
        if c.skill == "pull" and c.slide_in:
            # the robot's hook: start at `contact`, slide along `approach` until it touches something, back off a
            # little, then pull. It has to stop against the control (not the body), and the pull has to catch it.
            pull = cq.Vector(*c.pull)
            at, touched = None, None
            for k in range(int(REACH_MM / SLIDE_STEP_MM) + 1):
                tip = cq.Solid.makeSphere(probe / 2, contact + d * (k * SLIDE_STEP_MM), angleDegrees1=-90, angleDegrees2=90)
                touched = next((n for n, s in parts.items() if _overlaps(tip, s)), None)
                if touched:
                    at = contact + d * max(0.0, k * SLIDE_STEP_MM - BACK_OFF_MM)
                    break
            ok_reach = touched is not None and touched in c.moving
            detail = ("" if ok_reach else f"the {probe:g} mm {tool} slides in and hits {touched} first" if touched
                      else f"the {probe:g} mm {tool} slides {REACH_MM:g} mm in and touches nothing")
            add(f"{c.id}: {tool} reaches the handle", ok_reach, detail, c.id)
            caught = False
            if ok_reach:
                # a hook only when the control is right over the fingertip's centre, in the pull direction: lifting
                # against a front edge slides off, so brushing the handle with the side of the fingertip doesn't count
                column = _finger(at, pull, probe / 2 + PULL_MM, HOOK_CORE_MM)
                caught = _overlaps(column, moving)
            why = (f"the {tool} can't get into place first" if not ok_reach
                   else f"pulling {PULL_MM:g} mm catches nothing: it would need a pinch or a grip")
            add(f"{c.id}: opens with a hooked {tool}", caught, "" if caught else why, c.id)
        elif c.skill == "pull":
            path = _finger(contact - d * REACH_MM, d, REACH_MM, probe)
            blocked = [n for n, s in parts.items() if _overlaps(path, s)]
            add(f"{c.id}: {tool} reaches the handle", not blocked,
                f"a {probe:g} mm {'fingertip' if c.probe_d is None else 'hook'} hits {', '.join(blocked)} on the way in" if blocked else "", c.id)
            # pulled from where it got to: the swept probe has to catch the moving part, or nothing opens it
            pull = cq.Vector(*c.pull)
            sweep = _finger(contact, pull, PULL_MM, probe).fuse(
                cq.Solid.makeSphere(probe / 2, contact + pull * PULL_MM, angleDegrees1=-90, angleDegrees2=90))
            caught = not blocked and moving is not None and _overlaps(sweep, moving)
            why = (f"the {tool} can't get into place first" if blocked
                   else f"pulling {PULL_MM:g} mm catches nothing: it would need a pinch or a grip")
            add(f"{c.id}: opens with a hooked {tool}", caught, "" if caught else why, c.id)
        else:
            length = REACH_MM - STOP_SHORT_MM
            path = _finger(contact - d * REACH_MM, d, length, probe)
            blocked = [n for n, s in others.items() if _overlaps(path, s)]
            add(f"{c.id}: {tool} reaches it", not blocked,
                f"a {probe:g} mm {tool} hits {', '.join(blocked)} on the way in" if blocked else "", c.id)
    return out
