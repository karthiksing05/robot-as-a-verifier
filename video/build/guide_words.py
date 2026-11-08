"""Placeholder word timings for a silent preview: the Draft 9 script read at a natural pace, each section from its target start.

    python guide_words.py  ->  words.json (absolute times; captions.py and comp.js then use VO = 0)
"""
import json, re
s = open("../script.md").read()
START = {"2.": 15.4, "3.": 30.6, "4.": 87.0, "5.": 132.0}
END = {"2.": 30.2, "3.": 86.4, "4.": 131.4, "5.": 149.0}  # each section is fitted into its window
RATE = 2.35  # words a second, before pauses
words = []
for sec in re.split(r"\n## ", s):
    key = sec[:2]
    if key not in START: continue
    t = START[key]
    for para in [l[2:] for l in sec.split("\n") if l.startswith("> ")]:
        for w in para.split():
            d = (len(w) + 3) / 7.2 / RATE
            words.append({"w": w, "s": round(t, 2), "e": round(t + d * 0.9, 2)})
            t += d
            if re.search(r"[.?!]$", w): t += 0.45
            elif re.search(r"[,:;]$", w): t += 0.18
        t += 0.4
    first = next(i for i, w in enumerate(words) if w["s"] >= START[key] - 0.001)
    k = (END[key] - START[key]) / (t - START[key])
    for w in words[first:]:
        w["s"] = round(START[key] + (w["s"] - START[key]) * k, 2); w["e"] = round(START[key] + (w["e"] - START[key]) * k, 2)
    print(key, "fitted ×", round(k, 2))
json.dump(words, open("words.json", "w"), indent=0)
