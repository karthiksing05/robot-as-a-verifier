"""The Draft 12 voiceover's words (Whisper medium.en), fixed up and placed on the video's clock.

    python vo_words.py RAW.json  ->  words.json (absolute video seconds; the voice starts after the cold open)
Spellings follow what Karthik said; only Whisper's mishearings change.
"""
import json, sys
OFF = 7.0  # the cold open runs 7 s before the voice
raw = json.load(open(sys.argv[1]))
# glue Whisper's split tokens ("low -cost", "5 ,127", "R -split")
w = []
for x in raw:
    if w and x["w"][:1] in "-," and len(x["w"]) > 1:
        w[-1] = {**w[-1], "w": w[-1]["w"] + x["w"], "e": x["e"]}
    else: w.append(dict(x))
out = []
for i, x in enumerate(w):
    t, prev = x["w"], (w[i - 1]["w"] if i else "")
    nxt = w[i + 1]["w"] if i + 1 < len(w) else ""
    if t.startswith("RAV"): t = t.replace("RAV", "RAAV")
    if t == "robot" and prev == "RAAV,": t = "Robot"
    if t == "as" and prev == "Robot" or (t == "a" and prev == "As"): pass
    if t == "R-split": # "our split"
        m = (x["s"] + x["e"]) / 2
        out.append({"w": "our", "s": x["s"], "e": m}); out.append({"w": "split", "s": m, "e": x["e"]}); continue
    if t == "app" and nxt == "appliance": continue  # a stumble
    if t == "and" and nxt == "simulation": t = "in"
    if prev == "System" and t in ("one", "two"): t = {"one": "1", "two": "2"}[t]
    if t == "microwaves": t = "microwave's"
    if t in ("time,", "start,", "stop.", "time") and prev in ("presses", "and", "then", "after") and i > 0:
        t = t.upper()
    if t == "Time" and nxt == "didn't": t = "TIME"
    if t == "start" and prev == "after": t = "START"
    if t == "lid" and prev == "read": t = "LID"
    if t == "I" and prev == "words,": t = "“I"
    if t == "failures." and prev == "5,126": t = "failures.”"
    out.append({**x, "w": t})
for x in out: x["s"] = round(x["s"] + OFF, 2); x["e"] = round(x["e"] + OFF, 2)
# Robot As A Verifier
for i, x in enumerate(out):
    if x["w"] == "robot" and out[i - 1]["w"] == "RAAV,": x["w"] = "Robot"
    if x["w"] == "as" and out[i - 1]["w"] == "Robot": x["w"] = "As"
    if x["w"] == "a" and out[i - 1]["w"] == "As": x["w"] = "A"
    if x["w"] == "verifier." and out[i - 1]["w"] == "A": x["w"] = "Verifier."
    if x["w"] == "Vision" and out[i + 1]["w"] == "language": x["w"] = "Vision-language"; out[i + 1]["w"] = "\x00"
    if x["w"] == "auto-research": x["w"] = "auto-research"
out = [x for x in out if x["w"] != "\x00"]
json.dump(out, open("words.json", "w"), indent=0)
print(len(out), "words;", out[0]["s"], "→", out[-1]["e"])
