"""Lays the footage against the voiceover (Draft 9 order), and extracts just the frames it needs.

    python footage.py  ->  segments.json (read by comp.js) and ../out/frames/<clip>/NNNNN.jpg + clips.json

Robot footage: the Rev A run agent-centrifuge-043919 and the Rev B run agent-centrifuge-045535 (MuJoCo, Claude Sonnet
5.5), recorded from the Console on Nov 8. Clip times of events come from the footage manifest.
"""
import json, os, re, subprocess
FOOT = os.environ.get("FOOTAGE", "/private/tmp/claude-501/-Users-karthiksing05-Documents-Independent-Projects-MakeCU-2026-robot-as-a-verifier/733820d9-614a-4cfd-bbcc-7ed1a0e9af98/scratchpad/vid/footage")
words = json.load(open("words.json"))  # absolute times
norm = lambda w: re.sub(r"[^\w-]", "", w).lower()
def T(word, after=0.0):
    for w in words:
        if w["s"] >= after - 0.01 and norm(w["w"]).startswith(word): return w["s"]
    raise KeyError(f"{word} after {after}")

s3 = T("first"); s4 = T("under"); s5 = T("why")
S = dict(s2=T("this"), never=T("never"), s3=s3, s4=s4, s5=s5,
         wrist=T("wrist", s3), finds=T("finds", s3), touches=T("pins", s3), model=T("model", s3), then=T("then", s3),
         display=T("when", s3), lid=T("when", T("amended", s3)), there=T("there", s3), test=T("test", T("approve", s3)),
         software=T("software", s5), hardware=T("hardware", s5), as_=T("as", T("prototypes", s5)), end=T("relies", s5) + 1.4)
S["lidui"] = T("refused", S["lid"])
S["today"] = T("today", s5); S["twelve"] = T("twelve", S["today"]); S["realc"] = T("real", S["today"]); S["cloud"] = T("cloud", S["today"]); S["anylab"] = T("any", S["today"])
t1x = lambda clean_t: clean_t * 2 - 300  # clean_3d_test_1x covers sim 300–485 s at 1x; clean_3d is sim ÷ 2
SEG = []  # [from, to, clip, clip_start, speed, hold, zoom]
def seg(a, b, clip, c0, speed=1.0, hold=None, zoom=None): SEG.append([round(a, 3), round(b, 3), clip, round(c0, 3), round(speed, 4), hold, zoom])
def warp(clip, pts):
    for (a, ca), (b, cb) in zip(pts, pts[1:]): seg(a, b, clip, ca, (cb - ca) / (b - a))

# The take is split in two. §1 opens on the erasing and stops as the chalk touches the board (WRITE_AT); comp.js pushes
# in on that point and the drawn board opens out of it. The close comes back to the same point and lets him write RAAV,
# zooming out, then walk off before the fade to black.
WRITE_AT = 11.5   # source second the chalk first touches the board
COLD = [(0.0, 6.0, 0.0, 1.75), (6.0, 6.6, 10.5, (WRITE_AT - 10.5) / 0.6), (6.6, 9.4, WRITE_AT, 0.0)]
for a, b, c0, sp in COLD: seg(a, b, "intro", c0, sp)
# the closing sentence: the last one in the script
ends = [i for i, w in enumerate(words) if re.search(r"[.?!]$", w["w"])]
S["close"] = words[ends[-2] + 1]["s"]
o = S["close"] - 0.5
S["outro"] = o
OUTRO = [(o, o + 5.0, WRITE_AT, 1.5), (o + 5.0, o + 7.0, 19.0, 1.0), (o + 7.0, o + 9.0, 20.9, 0.0)]
for a, b, c0, sp in OUTRO: seg(a, b, "intro", c0, sp)
S["fin"] = o + 9.0
# Tours: scripted Console sessions (tour.mjs), each click logged. Each is time-warped so its clicks land on their cues.
def tour(name):
    return json.load(open(f"{FOOT}/tour/{name}.json"))
def click_t(log, label): return next(e["t"] for e in log if e.get("label") == label)
CAM, CURSOR, CLICKS = [], [], []
def lay_tour(clip, log, pts):
    """pts: (video time, tour time) pairs, increasing. Footage, camera, cursor and clicks all go through the same warp."""
    warp(clip, pts)
    def v_of(tt):
        for (a, ta), (b, tb) in zip(pts, pts[1:]):
            if ta <= tt <= tb: return a + (tt - ta) * (b - a) / (tb - ta)
        return None
    prev_box, moving = [0, 0, 1920, 1080], False
    CAM.append([round(pts[0][0], 3), prev_box])
    for e in log:
        v = v_of(e["t"])
        if v is None: continue
        if e["kind"] == "move":
            CURSOR.append([round(v, 3), round(e["x"]), round(e["y"])])
            if not moving:  # moving to the next target: widen to keep the cursor in view
                moving = True
                nxt = next((x for x in log if x["kind"] == "click" and x["t"] > e["t"]), None)
                if nxt:
                    x0, y0, w0, h0 = prev_box; cx, cy = nxt["x"], nxt["y"]
                    l, t_, r, bt = min(x0, cx - 120), min(y0, cy - 80), max(x0 + w0, cx + 120), max(y0 + h0, cy + 80)
                    CAM.append([round(v, 3), [l, t_, r - l, bt - t_]])
        elif e["kind"] == "click":
            moving = False
            CLICKS.append([round(v, 3), round(e["x"]), round(e["y"])])
            prev_box = e["box"]
            CAM.append([round(v + 0.15, 3), prev_box])
        elif e["kind"] == "mark":
            prev_box = e["box"]; CAM.append([round(v, 3), prev_box])

# §3 the demo, on the Rev A run page, then Design Analysis, then the Rev B run
D = tour("demo")
c = lambda l: click_t(D, l) - 0.35
lay_tour("tour/demo", D, [(S["never"] - 0.3, 1.0), (s3, c("speed 4x")), (S["wrist"], c("stage scan")), (S["finds"], c("stage segment")),
    (T("pins", s3) - 0.8, c("node map")), (S["touches"], c("stage touch")), (S["model"], c("node plan")), (T("person", s3), c("node approved")),
    (S["then"], c("stage test")), (T("force", s3), c("node s1")), (S["display"], c("node F1")), (S["lid"], c("fit")), (T("pinch", S["lid"]), c("node s7")),
    (S["there"], c("tab CAD")), (T("propose", S["there"]), c("rev B")), (T("approve", S["there"]), c("fix F2")), (S["test"], click_t(D, "rev B run") + 0.6),
    (T("fix", S["test"]), c("stage test B")), (s4, c("stage test B") + 4.0)])
# §5 behind the scenes, under the case studies
B = tour("scenes")
lay_tour("tour/scenes", B, [(s5, 0.5), (S["outro"] + 0.7, B[-1]["t"] + 1.5)])

json.dump({"segments": SEG, "steps": S, "cam": CAM, "cursor": CURSOR, "clicks": CLICKS}, open("segments.json", "w"))

need = {}
for a, b, clip, c0, sp, hold, _ in SEG:
    lo, hi = c0, c0 + (b - a) * sp
    if hold is not None: lo, hi = min(lo, hold), max(hi, hold)
    l, h = need.get(clip, (1e9, -1e9)); need[clip] = (min(l, lo), max(h, hi))
clips = {}
for clip, (lo, hi) in need.items():
    src = "../real-world-assets/intro.MOV" if clip == "intro" else f"{FOOT}/{clip}.mp4"
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]))
    lo, hi = max(0, lo - 0.2), min(dur, hi + 0.3)
    name = clip.replace("/", "_"); out = f"../out/frames/{name}"; os.makedirs(out, exist_ok=True)
    first = int(lo * 30) + 1
    if not os.path.exists(f"{out}/{first:05d}.jpg"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-i", src, "-t", f"{hi - lo:.3f}", "-vf", "fps=30,scale=1920:1080", "-q:v", "3", "-start_number", str(first), f"{out}/%05d.jpg"], check=True)
    clips[clip] = {"frames": int(dur * 30), "dir": name}
    print(f"{clip}: {lo:.1f}–{hi:.1f} s")
json.dump(clips, open("../out/frames/clips.json", "w"), indent=1)
print({k: round(v, 1) for k, v in S.items()})
