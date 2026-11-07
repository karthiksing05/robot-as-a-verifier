"""Feasibility checks: every A/B swap combination, every motion, every swap path, tube insertion paths.
Pass = no two solids share volume (threshold 1e-6 mm^3) at any step."""
import itertools, json, math
import numpy as np
import appliance as ap
from checks import bbox_overlap

TOL = 1e-6
PA = ap.PARAMS
PB = ap.apply_patch(PA, {"bezel_clearance_mm": {"stop": 0.40}, "handle_type": "hook_lip", "well_id_mm": {"A": 16.8}})


def T(dx=0, dy=0, dz=0):
    M = np.eye(4); M[:3, 3] = (dx, dy, dz); return M


def hits(moving, static):
    out = []
    for mk, ms in moving.items():
        for sk, ss in static.items():
            if bbox_overlap(ms, ss, 0.05):
                v = ms.intersect(ss).Volume()
                if v > TOL:
                    out.append((mk, sk, round(v, 4)))
    return out


def env(parts, E, group=None, drop=()):
    s = {k: p.solid for k, p in parts.items() if k not in drop and (group is None or p.group == group)}
    s.update({"E:" + k: v for k, v in E.items() if ("E:" + k) not in drop})
    return s


def sweep(name, parts, E, moving_keys, transforms, group=None, extra_drop=(), base=None):
    """transforms: list of (label, 4x4 applied to the moving parts' current solids)."""
    static = env(parts, E, group, drop=set(moving_keys) | set(extra_drop))
    bad = []
    for label, M in transforms:
        mv = {k: ap.xf(base[k] if base else parts[k].solid, M) for k in moving_keys}
        h = hits(mv, static)
        if h:
            bad.append((label, h))
    return dict(check=name, steps=len(transforms), collisions=bad, ok=not bad)


R = []

# 1. every combination of Rev A / Rev B fault inserts --------------------------------------------
pA, EA, DA = ap.build(PA)
pB, EB, DB = ap.build(PB)
swap = {"F1": ["bezel_stop", "cap_stop"], "F2": ["lid_handle"], "F3": ["well_insert_A", "tube_1"]}
for combo in itertools.product("AB", repeat=3):
    parts = {k: v.solid for k, v in pA.items()}
    changed = []
    for (f, keys), rv in zip(swap.items(), combo):
        if rv == "B":
            for k in keys:
                parts[k] = pB[k].solid; changed.append(k)
    st = dict(parts); st.update({"E:" + k: v for k, v in EA.items()})
    keys = [k for ks in swap.values() for k in ks]
    mv = {k: st[k] for k in keys}
    rest = {k: v for k, v in st.items() if k not in keys}
    h = hits(mv, rest) + hits({k: mv[k] for k in keys[:2]}, {k: mv[k] for k in keys[2:]})
    R.append(dict(check="swap combo F1/F2/F3 = " + "".join(combo), collisions=h, ok=not h))
print("combos done")

# 2. motions ----------------------------------------------------------------------------------------
for tag, (pp, EE, DD, PP) in (("A", (pA, EA, DA, PA)), ("B", (pB, EB, DB, PB))):
    lidk = DD["lid_group"]
    tr = [(f"{a} deg", ap.rot_about_y_axis(DD["axis"], a)) for a in np.arange(0, PP["lid_open_deg"] + 0.1, 2.5)]
    R.append(sweep(f"lid swing 0-105 deg, Rev {tag}", pp, EE, lidk, tr, group="centrifuge"))
    # pushed 2 deg past the stop must collide (the stop works)
    over = sweep("x", pp, EE, ["lid_hinge_leaf"], [("107", ap.rot_about_y_axis(DD["axis"], PP["lid_open_deg"] + 2))], group="centrifuge")
    R.append(dict(check=f"lid stop blocks travel past 105 deg, Rev {tag}", ok=not over["ok"], detail=over["collisions"][:1]))
Mr = DA["Mrack"]; av, az = DA["rack_axis"]
tr = [(f"{a} deg", Mr @ ap.rot_about_y_axis_v(av, az, a) @ np.linalg.inv(Mr)) for a in np.arange(0, 105.1, 2.5)]
R.append(sweep("rack cover swing 0-105 deg", pA, EA, DA["cover_group"], tr, group="rack"))
# dial: knob turns 270 deg clockwise (seen from outside) with the pot shaft
kn = pA["dial_knob"]
Mk0 = kn.M @ ap.rotz(-PA["dial_sweep_deg"] / 2)       # knob frame with zero rotation
tr = []
for th in np.arange(0, PA["dial_sweep_deg"] + 0.1, 7.5):
    M = Mk0 @ ap.rotz(PA["dial_sweep_deg"] / 2 - th) @ np.linalg.inv(kn.M)
    tr.append((f"{th} deg", M))
R.append(sweep("speed knob 0-270 deg", pA, EA, ["dial_knob"], tr, extra_drop=["E:pot"]))
print("motions done")

# 3. bayonet twist (locked -> notch) and swap paths ------------------------------------------------
lock = PA["bayo_lock_deg"]
for tag, (pp, EE, DD, PP) in (("A", (pA, EA, DA, PA)), ("B", (pB, EB, DB, PB))):
    # Stop bezel + its captive cap: twist to unlock, then pull straight out 30 mm
    b = pp["bezel_stop"]
    n = ap.vec(b.M, (0, 0, 1))
    tw = [(f"twist {a}", b.M @ ap.rotz(-a) @ np.linalg.inv(b.M)) for a in np.arange(0, lock + 0.1, 5)]
    R.append(sweep(f"Stop bezel bayonet twist, Rev {tag}", pp, EE, ["bezel_stop", "cap_stop"], tw))
    U = b.M @ ap.rotz(-lock) @ np.linalg.inv(b.M)
    pull = [(f"out {d} mm", T(*(n * d)) @ U) for d in np.arange(0, 30.1, 1.5)]
    R.append(sweep(f"Stop bezel + cap pull-out along the face normal, Rev {tag}", pp, EE, ["bezel_stop", "cap_stop"], pull))

    # Well A insert: lid open, tube removed, twist, lift 30 mm
    Rl = ap.rot_about_y_axis(DD["axis"], PP["lid_open_deg"])
    pp2 = {k: v for k, v in pp.items() if k != "tube_1"}
    opened = {k: (ap.xf(v.solid, Rl) if k in DD["lid_group"] else v.solid)
              for k, v in pp2.items() if v.group == "centrifuge"}
    w = pp["well_insert_A"]
    static = dict(opened); static.pop("well_insert_A"); static.update({"E:" + k: v for k, v in EE.items()})
    bad = []
    for a in np.arange(0, lock + 0.1, 5):
        M = w.M @ ap.rotz(-a) @ np.linalg.inv(w.M)
        h = hits({"well_insert_A": ap.xf(w.solid, M)}, static)
        if h: bad.append((f"twist {a}", h))
    U = w.M @ ap.rotz(-lock) @ np.linalg.inv(w.M)
    for d in np.arange(0, 30.1, 1.5):
        h = hits({"well_insert_A": ap.xf(w.solid, T(0, 0, d) @ U)}, static)
        if h: bad.append((f"lift {d}", h))
    R.append(dict(check=f"Well A insert twist + lift-out (lid open), Rev {tag}", collisions=bad, ok=not bad))

    # Tube into well A (lid open): lower from 50 mm above to its resting height
    tb = pp["tube_1"]
    bad = []
    static2 = dict(static); static2["well_insert_A"] = w.solid
    for d in np.arange(50, -0.01, -2.0):
        h = hits({"tube_1": ap.xf(tb.solid, T(0, 0, d))}, static2)
        if h: bad.append((f"{d} mm above rest", h))
    R.append(dict(check=f"tube lowered into well A (lid open), Rev {tag}", collisions=bad, ok=not bad))

    # Lid handle: slide forward to unlock, then lift 20 mm (lid closed)
    hd = pp["lid_handle"]
    stat = env(pp, EE, "centrifuge", drop={"lid_handle"})
    bad = []
    path = [T(dx, 0, 0) for dx in np.arange(0, PP["key_slide_mm"] + 0.01, 0.5)] + \
           [T(PP["key_slide_mm"], 0, dz) for dz in np.arange(0, 20.1, 1.0)]
    for i, M in enumerate(path):
        h = hits({"lid_handle": ap.xf(hd.solid, M)}, stat)
        if h: bad.append((i, h))
    R.append(dict(check=f"lid handle slide-unlock + lift-off (lid closed), Rev {tag}", collisions=bad, ok=not bad))
print("swap paths done")

# 4. rack: tube in/out of well 2 with the cover open; rack insert twist ------------------------------
Rc = Mr @ ap.rot_about_y_axis_v(av, az, 105) @ np.linalg.inv(Mr)
rk = {k: (ap.xf(v.solid, Rc) if k in DA["cover_group"] else v.solid)
      for k, v in pA.items() if v.group == "rack"}
t2 = rk.pop("tube_2")
bad = []
for d in np.arange(0, 60.1, 2.0):
    h = hits({"tube_2": ap.xf(t2, T(0, 0, d))}, rk)
    if h: bad.append((d, h))
R.append(dict(check="tube lifted out of rack well 2 (cover open)", collisions=bad, ok=not bad))
json.dump(R, open("out/feasibility.json", "w"), indent=1, default=str)
for r in R:
    print(("PASS " if r["ok"] else "FAIL ") + r["check"] + ("" if r["ok"] else "  " + str(r.get("collisions", r.get("detail")))[:300]))
