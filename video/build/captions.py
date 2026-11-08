"""Caption chunks from the voiceover's word timings (words.json, Whisper small.en), with names spelled right.

    python captions.py  ->  captions.json (for the composition) and ../out/captions.srt
"""
import json, os, re

import os
VO_OFFSET = float(os.environ.get("VO_OFFSET", 6.0))  # the first take started after a six-second cold open; guide words are absolute
FIX = {"RAV": "RAAV", "RAV,": "RAAV,", "RAV.": "RAAV.", "SmallVLA": "SmolVLA", "Gruten": "GR00T", "1": "N1",
       "SEL4": "seL4", "in": "in", "start": "START", "tube.": "TUBE.", "hooked": "hook", "fail": "failed"}

words = json.load(open("words.json"))
out = []
for i, w in enumerate(words):
    t = w["w"]
    if t == "Gruten": t = "GR00T"
    elif t == "1" and i and words[i - 1]["w"] == "Gruten": t = "N1"
    elif t in ("RAV", "RAV,", "RAV."): t = t.replace("RAV", "RAAV")
    elif t == "SmallVLA": t = "SmolVLA"
    elif t == "SEL4": t = "seL4"
    elif t == "start" and words[i - 1]["w"] == "so": t = "START"
    elif t == "tube." and words[i - 1]["w"] == "shows": t = "TUBE."
    out.append({**w, "w": t})
# "manual in spec" was "manual and spec"
for i, w in enumerate(out):
    if w["w"] == "in" and out[i - 1]["w"] == "manual" and out[i + 1]["w"].startswith("spec"): w["w"] = "and"

# Whisper splits "AI-claimed" and "5,000" into pieces: glue them back.
glued = []
for w in out:
    if glued and (w["w"][:1] in "-," and len(w["w"]) > 1 and not w["w"].startswith(", ")):
        glued[-1] = {**glued[-1], "w": glued[-1]["w"] + w["w"], "e": w["e"]}
    else:
        glued.append(dict(w))
out = glued
for w in out:
    w["w"] = w["w"].replace("16-newtons", "16 newtons")

# Sentences, then each sentence split into balanced pieces of at most two lines (about 84 characters).
MAX = 84
sentences, cur = [], []
for i, w in enumerate(out):
    cur.append(w)
    nxt = out[i + 1] if i + 1 < len(out) else None
    if re.search(r"[.?!][\"”’]?$", w["w"]) or nxt is None or nxt["s"] - w["e"] > 1.2:
        sentences.append(cur); cur = []
text = lambda ws: " ".join(x["w"] for x in ws)
chunks = []
for sen in sentences:
    n = max(1, -(-len(text(sen)) // MAX))
    target = len(text(sen)) / n
    piece = []
    for j, w in enumerate(sen):
        piece.append(w)
        rest = sen[j + 1:]
        if rest and len(chunks) >= 0 and (len(text(piece)) >= target * 0.9 and (re.search(r"[,;:]$", w["w"]) or len(text(piece)) >= target)) and len(text(rest)) > 12:
            chunks.append({"s": round(piece[0]["s"] + VO_OFFSET, 2), "e": round(piece[-1]["e"] + VO_OFFSET, 2), "t": text(piece)}); piece = []
    if piece:
        chunks.append({"s": round(piece[0]["s"] + VO_OFFSET, 2), "e": round(piece[-1]["e"] + VO_OFFSET, 2), "t": text(piece)})
for a, b in zip(chunks, chunks[1:]):  # hold each caption until the next, up to 0.6 s
    a["e"] = round(min(b["s"], a["e"] + 0.6), 2)
chunks[-1]["e"] += 0.8
json.dump(chunks, open("captions.json", "w"), indent=1)
os.makedirs("../out", exist_ok=True)
ts = lambda x: f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{int(x % 60):02},{int(round(x % 1 * 1000)):03}"
open("../out/captions.srt", "w").write("\n".join(f"{i + 1}\n{ts(c['s'])} --> {ts(c['e'])}\n{c['t']}\n" for i, c in enumerate(chunks)))
print(len(chunks), "captions")
for c in chunks: print(f"{c['s']:7.2f} {c['t']}")
