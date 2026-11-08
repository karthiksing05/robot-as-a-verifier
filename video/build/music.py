"""A soft, original placeholder score: slow piano chords over a warm pad, swelling at the turn (0:55).

    python music.py  ->  ../out/music.wav (48 kHz stereo, DUR seconds)
"""
import numpy as np, wave, sys

SR, DUR = 48000, float(sys.argv[1]) if len(sys.argv) > 1 else 196.0
t_all = np.arange(int(SR * DUR)) / SR
L = np.zeros_like(t_all); R = np.zeros_like(t_all)
midi = lambda n: 440 * 2 ** ((n - 69) / 12)
# I – V – vi – IV in D major, two bars each at 72 bpm
CHORDS = [[50, 57, 62, 66], [45, 52, 57, 61], [47, 54, 59, 62], [43, 50, 55, 59]]
BEAT = 60 / 72
rng = np.random.default_rng(7)

def piano(f, start, dur, vel, pan):
    n = int(SR * dur); i0 = int(SR * start)
    if i0 >= len(L): return
    n = min(n, len(L) - i0); t = np.arange(n) / SR
    env = (1 - np.exp(-t * 180)) * np.exp(-t * 1.25)
    tone = sum(a * np.sin(2 * np.pi * f * k * t * (1 + 0.0004 * k)) * np.exp(-t * 0.6 * k) for k, a in [(1, 1), (2, .42), (3, .18), (4, .09), (5, .04)])
    s = tone * env * vel
    L[i0:i0 + n] += s * (1 - pan); R[i0:i0 + n] += s * pan

def pad(notes, start, dur, vel):
    i0 = int(SR * start); n = min(int(SR * dur), len(L) - i0)
    if n <= 0: return
    t = np.arange(n) / SR
    env = np.minimum(1, t / 2.5) * np.minimum(1, (dur - t) / 2.5)
    for k, note in enumerate(notes):
        f = midi(note - 12)
        for d in (-0.12, 0.0, 0.11):
            s = np.sin(2 * np.pi * f * (1 + d / 100) * t + rng.uniform(0, 6)) * env * vel / 9
            L[i0:i0 + n] += s * (0.6 if k % 2 else 0.4); R[i0:i0 + n] += s * (0.4 if k % 2 else 0.6)

bar = 4 * BEAT
for b in range(int(DUR / bar) + 1):
    t0 = b * bar
    if t0 < 5.0: continue  # the music starts on the cold open's last stroke
    chord = CHORDS[(b // 2) % 4]
    lift = 1.0 if t0 > 55 else 0.7
    if b % 2 == 0: pad(chord, t0, bar * 2 + 2.5, 0.55 * lift if t0 > 55 else 0.25)
    pattern = [0, 2, 1, 3, 2, 1, 3, 2]  # gentle arpeggio, eighth notes
    for k, idx in enumerate(pattern):
        note = chord[idx] + (12 if idx > 1 else 0)
        piano(midi(note), t0 + k * BEAT / 2 + rng.uniform(0, 0.012), 3.5, (0.16 if k % 2 else 0.22) * lift, 0.35 + 0.3 * (idx / 3))
    piano(midi(chord[0] - 12), t0, 5, 0.22 * lift, 0.5)

# a room: a few quiet, filtered echoes
for d, g in [(0.083, .28), (0.141, .2), (0.233, .14), (0.377, .09)]:
    k = int(SR * d)
    L[k:] += g * R[:-k] * 0.9; R[k:] += g * L[:-k] * 0.9
fade = np.minimum(1, np.minimum((t_all - 5.0).clip(0) / 1.5, (DUR - t_all) / 4))
L *= fade; R *= fade
peak = max(np.abs(L).max(), np.abs(R).max())
st = (np.stack([L, R], 1) / peak * 0.8 * 32767).astype("<i2")
with wave.open("../out/music.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())
print("music.wav", DUR, "s")
