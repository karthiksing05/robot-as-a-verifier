"""Lays the footage against Karthik's Draft 12 voiceover, and extracts just the frames it needs.

    python footage.py  ->  segments.json (read by comp.js) and ../out/frames/<clip>/NNNNN.jpg + clips.json

The real run is agent-centrifuge-113400 (Nov 8, 11:34, Claude Haiku 5.5), filmed three ways:
  over: overhead phone (IMG_5920), the clock everything else is synced to
  hand: handheld side phone (portrait); hand ≈ over + 3 s
  cons: the Console's Live screen recording; cons ≈ over + 18 s
Synced on the POWER flip (the ring lights) and START (the display reads LID). sim: the same eight steps in MuJoCo.
"""
import json, os, re, subprocess
FOOT = os.environ.get("FOOTAGE", "/private/tmp/claude-501/-Users-karthiksing05-Documents-Independent-Projects-MakeCU-2026-robot-as-a-verifier/733820d9-614a-4cfd-bbcc-7ed1a0e9af98/scratchpad/vid/footage")
IV = "../initial-vids"
SRC = {"intro": "../real-world-assets/intro.MOV", "over": f"{IV}/IMG_5920.MOV", "hand": f"{IV}/WhatsApp Video 2026-11-08 at 11.37.21.mp4",
       "cons": f"{IV}/WhatsApp Video 2026-11-08 at 11.41.33.mp4", "sim": f"{FOOT}/simdemo/sim_demo.mp4", "hinge": "../out/cad/hinge.mp4"}
SIZE = {"hand": "478:850", "cons": "1600:954"}  # native sizes; the rest are 1920 × 1080
words = json.load(open("words.json"))  # absolute video seconds
norm = lambda w: re.sub(r"[^\w-]", "", w).lower()
def T(word, after=0.0):
    for w in words:
        if w["s"] >= after - 0.01 and norm(w["w"]).startswith(word): return w["s"]
    raise KeyError(f"{word} after {after}")
def E(word, after=0.0):
    for w in words:
        if w["s"] >= after - 0.01 and norm(w["w"]).startswith(word): return w["e"]
    raise KeyError(word)

s2 = T("this"); s3 = T("scans"); s4 = T("under"); s5 = T("why")
ends = [i for i, w in enumerate(words) if re.search(r"[.?!][\"”’]?$", w["w"])]
S = dict(s2=s2, never=T("centrifuge", s2) + 0.2, s3=s3, s4=s4, s5=s5,
         six=T("six", s3), plan=T("we", s3), approves=T("approves", s3), works=T("then", s3), board=T("board", s3), verdict=T("verdict", s3),
         five=T("all", s3), timeq=T("time", T("up", s3)), lid=T("lid", T("display", s3)), suspected=T("raav", T("lid", T("display", s3))),
         cad=T("tube", T("guessing", s3)), widened=T("widened", s3), seated=T("seated", s3), hinge=T("our", T("seated", s3)), next=T("next", s3),
         software=T("software", s5), dyson=T("dyson", s5), fields=T("important", s5), hardware=T("hardware", s5),
         today=T("today", s5), twelve=T("12", s5), realc=T("real", T("today", s5)), cloud=T("cloud", s5), anylab=T("any", T("cloud", s5)),
         close=words[ends[-3] + 1]["s"], end=words[-1]["e"])
S["as_"] = S["close"]
SEG, PANE = [], []  # SEG: the full-frame footage [from, to, clip, c0, speed, hold, zoom]; PANE: [from, to, pane, clip, c0, speed]
def seg(a, b, clip, c0, speed=1.0, hold=None, zoom=None): SEG.append([round(a, 3), round(b, 3), clip, round(c0, 3), round(speed, 4), hold, zoom])
def pane(name, clip, pts):
    """pts: (video time, clip time) pairs, increasing in video time."""
    for (a, ca), (b, cb) in zip(pts, pts[1:]):  # a repeated video time is a cut
        if b - a > 1e-6: PANE.append([round(a, 3), round(b, 3), name, clip, round(ca, 3), round((cb - ca) / (b - a), 4)])

# §1 cold open: erase, step up, and the camera's jump into the chalk's tip (comp.js) as he gets into position
WRITE_AT = 11.5   # source second the chalk first touches the board
COLD = [(0.0, 5.0, 0.0, 9.5 / 5.0), (5.0, 6.3, 9.5, 2.0 / 1.3)]
for a, b, c0, sp in COLD: seg(a, b, "intro", c0, sp)
S["snap"] = [5.75, 6.3]

# §3 the real run. Phase A: the scan (overhead | Console wrist feed)
pane("L", "over", [(s3 - 0.6, 18.0), (S["plan"], 36.0)])
pane("R", "cons", [(s3 - 0.6, 40.0), (S["plan"], 62.0)])
# Phase B: the plan and its approval (handheld side view | Console plan, Approve clicked on "approves")
pane("L", "hand", [(S["plan"], 30.0), (S["works"] - 0.2, 58.0)])
pane("R", "cons", [(S["plan"], 62.0), (S["approves"], 74.6), (S["works"] - 0.2, 77.0)])
# Phase C: the eight steps, sim beside reality, each step's footage landing in its own slot
STEPS = ["tube_pick", "tube_place", "lid_close", "POWER", "TIME+", "SPEED", "START", "STOP"]
OVER = [60, 76, 86, 99, 103, 111, 120, 128, 136]          # overhead clip seconds at each step's boundaries
a0, a1 = S["works"] - 0.2, S["five"]
w = [3.0, 2.0, 2.2, 1.2, 1.6, 2.0, 2.0, 2.0]; k = (a1 - a0) / sum(w)
V = [a0]
for x in w: V.append(V[-1] + x * k)
S["steps"] = [round(v, 3) for v in V]
pane("L", "over", list(zip(V, OVER)))
sim = json.load(open(f"{FOOT}/simdemo/sim_demo.json")) if os.path.exists(f"{FOOT}/simdemo/sim_demo.json") else None
if sim:
    ss = [sim["steps"][f"s{i}"] for i in range(1, 9)]
    simpts = [(V[i], ss[i][0]) for i in range(8)] + [(V[8], ss[7][1])]
    pane("R", "sim", simpts)
    S["sim"] = {"speed": sim.get("speed"), "revision": sim.get("revision")}
else:
    pane("R", "cons", [(a0, 96.0), (a1, 160.0)])  # until the sim recording exists: the Console following along
# Phase D: what it found
pane("R", "cons", [(S["five"], 166.0), (S["timeq"], 170.0), (S["suspected"], 172.0), (S["cad"] - 0.3, 174.0)])
pane("L", "over", [(S["five"], 128.0), (S["timeq"], 136.0)])
pane("L", "hand", [(S["timeq"], 105.5), (S["lid"] - 0.9, 110.0), (S["lid"] - 0.9, 124.3), (S["suspected"], 127.3), (S["suspected"], 82.0), (S["cad"] - 0.3, 96.0)])
# §4: the hinge comparison (rendered by cad_render.mjs)
if os.path.exists(SRC["hinge"]): pane("F", "hinge", [(S["hinge"] - 0.4, 0.0), (s4 - 0.3, s4 - 0.3 - S["hinge"] + 0.4)])
# §6 the Console in its window, under the case studies
B = json.load(open(f"{FOOT}/tour/scenes.json"))
CAM, CURSOR, CLICKS = [], [], []
def warp(clip, pts):
    for (a, ca), (b, cb) in zip(pts, pts[1:]): seg(a, b, clip, ca, (cb - ca) / (b - a))
warp("tour/scenes", [(s5, 0.5), (S["close"] + 0.4, B[-1]["t"] + 1.5)])
# the close: the same jump back into the take, then he writes RAAV over the last line, walks off, black
o = S["close"] - 0.3
S["outro"] = o
wr_end = S["end"] + 0.2
OUTRO = [(o, o + 0.7, WRITE_AT, 0.0), (o + 0.7, wr_end, WRITE_AT, (19.0 - WRITE_AT) / (wr_end - o - 0.7)), (wr_end, wr_end + 2.0, 19.0, 1.0), (wr_end + 2.0, wr_end + 3.6, 20.9, 0.0)]
for a, b, c0, sp in OUTRO: seg(a, b, "intro", c0, sp)
S["fin"] = round(wr_end + 3.6, 2)

json.dump({"segments": SEG, "panes": PANE, "steps": S, "stepNames": STEPS, "cam": CAM, "cursor": CURSOR, "clicks": CLICKS}, open("segments.json", "w"))

need = {}
for a, b, clip, c0, sp, hold, _ in SEG: need.setdefault(clip, []).append((c0, c0 + (b - a) * sp))
for a, b, _, clip, c0, sp in PANE: need.setdefault(clip, []).append((c0, c0 + (b - a) * sp))
clips = {}
for clip, rs in need.items():
    lo, hi = min(min(r) for r in rs), max(max(r) for r in rs)
    src = SRC.get(clip, f"{FOOT}/{clip}.mp4")
    if not os.path.exists(src): print("missing", src); continue
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]))
    lo, hi = max(0, lo - 0.2), min(dur, hi + 0.3)
    name = clip.replace("/", "_"); out = f"../out/frames/{name}"; os.makedirs(out, exist_ok=True)
    first = int(lo * 30) + 1
    have = os.path.exists(f"{out}/{first:05d}.jpg") and os.path.exists(f"{out}/{int(hi * 30) - 1:05d}.jpg")
    if not have:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-i", src, "-t", f"{hi - lo:.3f}", "-vf", f"fps=30,scale={SIZE.get(clip, '1920:1080')}", "-q:v", "3", "-start_number", str(first), f"{out}/%05d.jpg"], check=True)
    w_, h_ = map(int, SIZE.get(clip, "1920:1080").split(":"))
    clips[clip] = {"frames": int(dur * 30), "dir": name, "w": w_, "h": h_}
    print(f"{clip}: {lo:.1f}–{hi:.1f} s")
json.dump(clips, open("../out/frames/clips.json", "w"), indent=1)
print({k: (round(v, 1) if isinstance(v, float) else v) for k, v in S.items()})
