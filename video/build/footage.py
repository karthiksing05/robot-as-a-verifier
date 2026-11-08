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
         wrist=T("wrist", s3), finds=T("finds", s3), touches=T("touches", s3), model=T("model", s3), then=T("then", s3),
         display=T("when", s3), lid=T("when", T("amended", s3)), there=T("there", s3), test=T("test", T("approve", s3)),
         software=T("software", s5), hardware=T("hardware", s5), as_=T("as", T("thousands", s5)), end=T("relies", s5) + 1.4)
S["lidui"] = T("refused", S["lid"])
t1x = lambda clean_t: clean_t * 2 - 300  # clean_3d_test_1x covers sim 300–485 s at 1x; clean_3d is sim ÷ 2
SEG = []  # [from, to, clip, clip_start, speed, hold, zoom]
def seg(a, b, clip, c0, speed=1.0, hold=None, zoom=None): SEG.append([round(a, 3), round(b, 3), clip, round(c0, 3), round(speed, 4), hold, zoom])
def warp(clip, pts):
    for (a, ca), (b, cb) in zip(pts, pts[1:]): seg(a, b, clip, ca, (cb - ca) / (b - a))

# §1 the cold open: erase at 1.75×, write RAAV at 2×, then the take's own push-in at 2×
COLD = [(0.0, 6.0, 0.0, 1.75), (6.0, 10.25, 10.5, 2.0), (10.25, 13.4, 21.0, 1.6)]
for a, b, c0, sp in COLD: seg(a, b, "intro", c0, sp)
# §3 the demo
seg(S["never"] - 0.2, s3, "clean_3d", 0.0, 0.6)
warp("clean_3d", [(s3, 1.0), (S["wrist"], 25.9), (S["finds"], 59.06), (S["touches"], 63.9), (S["model"], 110.0)])
seg(S["model"], S["then"], "ui_plan_approval", 3.6, (11.4 - 3.6) / (S["then"] - S["model"]), zoom=[1.7, 0, 880])
seg(S["then"], S["display"], "clean_3d_test_1x", 0.0, 1.0)
seg(S["display"], S["lid"], "clean_3d_test_1x", t1x(169.01) - 1.5, 0.6, hold=t1x(169.01))
seg(S["lid"], S["lidui"], "clean_3d_test_1x", t1x(211.49) - 1.0, 0.6, hold=t1x(211.49))
seg(S["lidui"], S["there"], "ui_live_lid_skip", 2.6, 1.0, zoom=[1.8, 0, 860])
seg(S["there"], S["test"], "ui_design_analysis", 3.6, (10.8 - 3.6) / (S["test"] - S["there"]))
seg(S["test"], s4, "clean_3d_revB_test_2x", 4.0, 1.0)
# §5 behind the scenes
seg(s5, S["software"] + 2.0, "broll/studies_scroll", 0.0, 1.0)
seg(S["software"] + 2.0, S["hardware"], "broll/run_log", 0.5, 1.0)
seg(S["hardware"], S["hardware"] + (S["as_"] - S["hardware"]) / 2, "ui_design_analysis", 0.0, 1.0)
seg(S["hardware"] + (S["as_"] - S["hardware"]) / 2, S["as_"], "ui_report", 0.0, 1.0)
seg(S["as_"], S["end"], "clean_3d_test_1x", 120.0, 0.5)
json.dump({"segments": SEG, "steps": S}, open("segments.json", "w"), indent=1)

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
