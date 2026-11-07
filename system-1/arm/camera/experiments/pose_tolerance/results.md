# How much camera-pose error the plane sweep tolerates

Scripts: `perturb.py coins|remote [seeds]`, `small_marker.py` (run from `system-1/arm/camera/` with `PYTHONPATH=.`).
Raw output: `results_coins.json`, `results_remote.json`, `results_small_marker.json`, `remote.log`, `small_marker.log`.

How the error is applied. Each view's camera centre moves by a uniform +-T mm per axis (board frame), and the camera
turns about its own centre by a uniform +-A deg about a random axis. "random" draws a new error for every view.
"common" uses one error for all views: the shift is a pure board-frame shift, the turn is the same turn in every
camera's own frame (what a tilted camera mount would do). Note the common turn is NOT a rigid move of the whole scene,
because the views are rolled differently, so it still changes the views' relative poses.

## Coins (truth: stack minus single 3.50 mm; unperturbed 3.40 mm, 169.7k confident cells), 3 seeds

"-" means the sweep did not find two coins.

| error | random per view: stack-single | conf. cells (k) | common: stack-single | conf. cells (k) |
|---|---|---|---|---|
| 0.25 mm | -, 5.02, 1.56 | 114-123 | 3.38, 3.39, 3.39 | 169 |
| 0.5 mm | -, -, 2.69 | 21-25 | 3.40, 3.38, 3.40 | 170 |
| 1 mm | -, -, - | 8-9 | 3.40, 3.40, 3.38 | 170 |
| 2 mm | -, -, - | 4 | 3.39, 3.40, 3.38 | 170 |
| 0.1 deg | 3.48, 3.31, 3.48 | 159-163 | 3.37, 3.41, 3.39 | 168-170 |
| 0.25 deg | 0.74, 3.17, 0.02 | 62-111 | 3.35, 3.42, 3.35 | 162-170 |
| 0.5 deg | -, -, - | 11-31 | 1.58, 3.43, 3.26 | 121-169 |
| 1 deg | -, -, - | 5-8 | -, 3.46, - | 27-168 |
| 0.25 mm + 0.1 deg | -, 3.44, - | 100-120 | 3.36, 3.40, 3.37 | 169 |
| 0.5 mm + 0.25 deg | -, -, - | 15-19 | 3.37, 3.39, 3.34 | 163-169 |
| 1 mm + 0.5 deg | -, -, - | 6-9 | 1.80, 3.43, 3.26 | 125-170 |
| 2 mm + 1 deg | -, -, - | 3-5 | 7.27, 3.45, - | 28-168 |

## TV remote (1080p), 1 seed: |height - unperturbed| on the unperturbed map's confident cells, mm

| error | random: median / p95 | conf. cells (k, base 118) | common: median / p95 | conf. cells (k) |
|---|---|---|---|---|
| 0.25 mm | 0.04 / 0.90 | 84 | 0.12 / 0.28 | 119 |
| 0.5 mm | 0.25 / 31 | 23 | 0.29 / 0.53 | 120 |
| 1 mm | 9.0 / 34 | 7 | 0.54 / 1.07 | 120 |
| 2 mm | 16.7 / 34 | 4 | 1.01 / 2.73 | 118 |
| 0.1 deg | 0.04 / 0.18 | 107 | 0.05 / 0.23 | 117 |
| 0.25 deg | 0.19 / 28 | 33 | 0.15 / 0.61 | 107 |
| 0.5 deg | 5.7 / 34 | 10 | 0.38 / 15.6 | 56 |
| 1 deg | 16.7 / 34 | 5 | 1.09 / 32 | 16 |
| 0.25 mm + 0.1 deg | 0.06 / 0.99 | 81 | 0.09 / 0.28 | 118 |
| 0.5 mm + 0.25 deg | 0.53 / 33 | 19 | 0.19 / 0.58 | 108 |
| 1 mm + 0.5 deg | 11.9 / 34 | 6 | 0.47 / 17.9 | 57 |
| 2 mm + 1 deg | 18.4 / 34 | 3 | 1.36 / 33 | 15 |

## Small marker patch instead of the full board (coins)

Only 5 markers were seen in all 20 views (the coins and framing hide the rest), so the patches are the markers
nearest the coins. Pose error is against the full-board pose.

| markers | patch span | rot. error median / max | position error median / max | coins found | stack-single |
|---|---|---|---|---|---|
| full board | | | | 2.04, 5.45 | 3.40 |
| 1 (id 10) | 1 marker | 0.89 / 7.7 deg | 2.2 / 17 mm | one | - |
| 2 (10, 14) | ~35 mm | 0.79 / 2.8 deg | 1.9 / 4.9 mm | one | - |
| 4 (10, 14, 11, 9) | ~95 mm | 0.35 / 0.48 deg | 0.83 / 1.3 mm | 2.02, 5.44 | 3.43 |
| 5 | ~95 mm | 0.36 / 0.63 deg | 0.87 / 1.4 mm | 2.04, 5.41 (+ a false 0.05 region) | 3.37 |

With 4 markers the pose is off by about 0.35 deg and 0.8 mm, yet the coins come out right: the errors from one
patch are mostly shared between views (common), which the sweep tolerates. One or two markers are too noisy.
Four markers spread over ~95 mm is a large sticker, not a small one.

## Conclusions

- Per-view random error: coin accuracy (stack-single within 0.2 mm of 3.40) holds at 0.1 deg and breaks at
  0.25 mm or 0.25 deg. So the views' relative poses must be good to about 0.1 deg and under 0.25 mm.
- A shared error barely matters for translation (2 mm common: still 3.38-3.40) and is fine for rotation up to 0.25 deg.
- Remote agrees: random 0.25 mm or 0.1 deg keeps median under 0.06 mm; 0.25 deg or 0.5 mm collapses.

## Realistic arm error

- Memory note (makecu-perception-findings.md): STS3215 backlash 0.6-0.9 deg per joint from one bench test, about
  1.5-3 mm at the tip; the sim's slop model uses 0.75 deg gear play and gives ~9 mm gravity sag before correction,
  ~0.3 mm after a re-command.
- roboticscenter.ai's SO-101 vs OpenArm page lists SO-101 repeatability as +-2-4 mm (method not given):
  https://www.roboticscenter.ai/learn/robot-arms/openarm-vs-so101 . No official LeRobot or Feetech figure found.
- So the realistic row is random 1-2 mm + 0.5-1 deg per view, 10x over the 0.1 deg / <0.25 mm tolerance. FK poses
  cannot feed the sweep directly; each view needs its pose re-estimated from the image (board/markers in view, or
  SIFT-based refinement), with FK only as a starting guess.
