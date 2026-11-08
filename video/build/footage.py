"""Lays the walkthrough's footage against the voiceover, and extracts just the frames it needs.

    python footage.py  ->  segments.json (read by walk.js) and ../out/frames/<clip>/NNNNN.jpg + clips.json

Footage: the Rev A run agent-centrifuge-043919 and the Rev B run agent-centrifuge-045535 (MuJoCo, Claude Sonnet 5.5),
recorded from the Console. Clip times of events come from the footage manifest.
"""
import json, os, re, subprocess
VO = 6.0
FOOT = os.environ.get("FOOTAGE", "/private/tmp/claude-501/-Users-karthiksing05-Documents-Independent-Projects-MakeCU-2026-robot-as-a-verifier/733820d9-614a-4cfd-bbcc-7ed1a0e9af98/scratchpad/vid/footage")
words = json.load(open("words.json"))
norm = lambda w: re.sub(r"[^\w-]", "", w).lower()
def T(word, after=0.0):
    for w in words:
        if w["s"] + VO >= after - 0.01 and norm(w["w"]).startswith(word): return w["s"] + VO
    raise KeyError(word)

s6 = T("here", 100)
S = dict(surveys=T("surveys", s6), scans=T("scans", s6), segments=T("segments", s6), maps=T("maps", s6), touches=T("touches", s6),
         fail=T("fail", s6), plans=T("plans", s6), runs=T("runs", s6))
S["flip"] = T("when", T("rules", s6)); S["display"] = T("display", S["flip"]); S["lid"] = T("then", T("change", s6))
S["lidui"] = T("its", S["lid"]); S["traces"] = T("traces", s6); S["unmasks"] = T("unmasks", s6); S["revb"] = T("rev", T("tube", s6))
s7 = T("our", T("rises", s6)); S["another"] = T("another", s7); S["plans7"] = T("plans", s7); S["human"] = T("we", T("prototype", s7)); S["as"] = T("as", T("loop", s7)); S["end"] = T("rav", T("relies", s7))

# test1x covers sim 300–485 s at 1x; clean_3d is sim ÷ 2.
t1x = lambda clean_t: clean_t * 2 - 300
SEG = []  # [from, to, clip, clip_start, speed, hold]
def seg(a, b, clip, c0, speed=1.0, hold=None, zoom=None): SEG.append([round(a, 3), round(b, 3), clip, round(c0, 3), round(speed, 4), hold, zoom])
def warp(clip, pts):  # piecewise: (video time, clip time) pairs
    for (a, ca), (b, cb) in zip(pts, pts[1:]): seg(a, b, clip, ca, (cb - ca) / (b - a))

seg(s6 - 0.4, S["surveys"], "clean_3d", 0.0, 0.8)
warp("clean_3d", [(S["surveys"], 2.0), (S["scans"], 25.9), (S["segments"], 59.06), (S["maps"], 61.5), (S["touches"], 63.9), (S["fail"], 110.0)])
seg(S["fail"], S["plans"], "wrist", 60.0, 1.0, hold=62.0)                                       # the failed scan: freeze on the wrist camera
seg(S["plans"], S["runs"], "ui_plan_approval", 4.6, (11.3 - 4.6) / (S["runs"] - S["plans"]), zoom=[1.7, 0, 880])      # the approval card, and the click
seg(S["runs"], S["flip"], "clean_3d_test_1x", 0.0, 1.0)                                           # the test, at 1x
seg(S["flip"], S["display"], "clean_3d_test_1x", 6.0, 0.5, hold=8.0)                              # safety stop: from the earlier run, frozen here
seg(S["display"], S["lid"], "clean_3d_test_1x", t1x(169.01) - 1.5, 0.6, hold=t1x(169.01))        # display mismatch → amendment
seg(S["lid"], S["lidui"] + 1.6, "clean_3d_test_1x", t1x(211.49) - 1.0, 0.6, hold=t1x(211.49))     # the lid handle, skipped before the arm moved
seg(S["lidui"] + 1.6, S["traces"], "ui_live_lid_skip", 2.2, 1.0, zoom=[1.8, 0, 860])                                  # …and the Live screen's skipped row
seg(S["traces"], S["unmasks"], "ui_design_analysis", 4.0, (10.6 - 4.0) / (S["unmasks"] - S["traces"]))  # Rev B and the F2 fix
seg(S["unmasks"], S["revb"], "clean_3d_test_1x", 95.0, 0.4, hold=96.0)                            # the tight well (verification check)
seg(S["revb"], s7, "clean_3d_revB_test_2x", 4.0, 1.0)                                             # Rev B
# §7
seg(s7, S["another"], "ui_studies", 0.0, 1.0)
seg(S["another"], S["plans7"], "clean_3d", 120.0, 1.0)
seg(S["plans7"], S["human"], "ui_live_report", 1.0, 1.0)
seg(S["human"], S["as"], "ui_methodology", 0.0, 1.0)
seg(S["as"], S["end"] + 0.3, "clean_3d_test_1x", 120.0, 0.5)

json.dump({"segments": SEG, "steps": S}, open("segments.json", "w"), indent=1)

# frames: only the stretch of each clip that's used
need = {}
for a, b, clip, c0, sp, hold, *_ in SEG:
    lo, hi = c0, c0 + (b - a) * sp
    for x in ([hold] if hold is not None else []): lo, hi = min(lo, x), max(hi, x)
    l, h = need.get(clip, (1e9, -1e9)); need[clip] = (min(l, lo), max(h, hi))
clips = {}
for clip, (lo, hi) in need.items():
    src = f"{FOOT}/{clip}.mp4"
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]))
    lo, hi = max(0, lo - 0.2), min(dur, hi + 0.3)
    out = f"../out/frames/{clip}"; os.makedirs(out, exist_ok=True)
    first = int(lo * 30) + 1
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-i", src, "-t", f"{hi - lo:.3f}", "-vf", "fps=30,scale=1920:1080", "-q:v", "3", "-start_number", str(first), f"{out}/%05d.jpg"], check=True)
    clips[clip] = {"frames": int(dur * 30), "from": first}
    print(f"{clip}: {lo:.1f}–{hi:.1f} s")
json.dump(clips, open("../out/frames/clips.json", "w"), indent=1)
