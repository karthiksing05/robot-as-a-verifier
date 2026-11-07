import itertools, math, json
import numpy as np, cadquery as cq
import appliance as ap

def bbox_overlap(a, b, tol=0.0):
    A, B = a.BoundingBox(), b.BoundingBox()
    return not (A.xmax < B.xmin - tol or B.xmax < A.xmin - tol or A.ymax < B.ymin - tol or
                B.ymax < A.ymin - tol or A.zmax < B.zmin - tol or B.zmax < A.zmin - tol)

def overlaps(items, min_vol=0.05):
    out = []
    names = list(items)
    for a, b in itertools.combinations(names, 2):
        sa, sb = items[a], items[b]
        if not bbox_overlap(sa, sb):
            continue
        try:
            v = sa.intersect(sb).Volume()
        except Exception as e:
            v = -1
        if v > min_vol or v < 0:
            out.append((a, b, round(v, 3)))
    return out

if __name__ == "__main__":
    import sys
    parts, E, D = ap.build()
    items = {k: p.solid for k, p in parts.items()}
    items.update({"E:" + k: v for k, v in E.items()})
    for r in overlaps(items):
        print(r)


def dist(a, b):
    return a.distance(b)


def lid_sweep(P=None, step=5.0):
    P = P or ap.PARAMS
    parts, E, D = ap.build(P, with_tubes=True)
    moving = D["lid_group"]
    static = {k: p.solid for k, p in parts.items() if k not in moving and p.group == "centrifuge"}
    static.update({"E:" + k: v for k, v in E.items()})
    worst = []
    ang = 0.0
    while ang <= P["lid_open_deg"] + 1e-6:
        R = ap.rot_about_y_axis(D["axis"], ang)
        hits = []
        for m in moving:
            s = ap.xf(parts[m].solid, R)
            for k, st in static.items():
                if bbox_overlap(s, st, 0.5) and s.intersect(st).Volume() > 1e-6:
                    hits.append((m, k))
        worst.append((ang, hits))
        ang += step
    R = ap.rot_about_y_axis(D["axis"], P["lid_open_deg"])
    gap = ap.xf(parts["lid_hinge_leaf"].solid, R).distance(parts["lid_hinge_base"].solid)
    R2 = ap.rot_about_y_axis(D["axis"], P["lid_open_deg"] + 2)
    over = ap.xf(parts["lid_hinge_leaf"].solid, R2).intersect(parts["lid_hinge_base"].solid).Volume()
    return worst, gap, over


def cover_sweep(P=None, step=5.0):
    P = P or ap.PARAMS
    parts, E, D = ap.build(P)
    moving = D["cover_group"]
    static = {k: p.solid for k, p in parts.items() if k not in moving and p.group == "rack"}
    Mr = D["Mrack"]; av, az = D["rack_axis"]
    res = []
    ang = 0.0
    while ang <= P["lid_open_deg"] + 1e-6:
        R = Mr @ ap.rot_about_y_axis_v(av, az, ang) @ np.linalg.inv(Mr)
        hits = []
        for m in moving:
            s = ap.xf(parts[m].solid, R)
            for k, st in static.items():
                if bbox_overlap(s, st, 0.5) and s.intersect(st).Volume() > 1e-6:
                    hits.append((m, k))
        res.append((ang, hits))
        ang += step
    R = Mr @ ap.rot_about_y_axis_v(av, az, P["lid_open_deg"]) @ np.linalg.inv(Mr)
    gap = ap.xf(parts["rack_hinge_leaf"].solid, R).distance(parts["rack_hinge_base"].solid)
    return res, gap
