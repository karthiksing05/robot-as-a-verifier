# Correcting noisy arm poses from the photos (no board markers)

`pose_refine.py coins|remote` (cwd system-1/arm/camera, PYTHONPATH=.). Raw numbers in `results_*.json`, logs in `log_*.txt`.

Method: take the ChArUco board poses as truth, move every camera centre by 1 or 2 mm and turn it by 0.5 or 1 deg in a
random direction (seed 1) to stand in for arm readings. Then SIFT (4000 per photo) on every photo, match every pair
(ratio test, RANSAC fundamental matrix), chain matches into tracks seen in 3+ photos, triangulate with the noisy poses,
and run a bundle adjustment (scipy `least_squares`, intrinsics fixed, every pose tied to its noisy reading by a prior
with the noise's size; that prior sets scale and the absolute plane, as the arm would). "Masked" hides the ArUco
markers (found by the marker detector, grown 7 px) from SIFT; the plain chessboard squares stay visible.
"vs board" compares each height map with the board-pose map over cells confident in both, after removing the median
offset: median |difference| and the share within 0.5 mm.

## Coins (20 views, 720p). Truth stack minus single 3.50 mm

| poses | pose error | confident cells | coins (mm) | stack - single | vs board | BA time |
|---|---|---|---|---|---|---|
| board | 0 | 169716 | 2.04, 5.45 | 3.40 | - | - |
| noisy 1 mm / 0.5 deg | 1.0 mm, 0.50 deg | 7185 | none found | - | - | - |
| refined, masked | 3.4 mm, 1.55 deg | 26012 | 2.09 only | - | 0.07 mm, 84 % | 23 s |
| refined, markers kept | 0.67 mm, 0.25 deg | 165599 | 2.00, 5.62 | 3.63 | 0.10 mm, 98 % | 36 s |
| noisy 2 mm / 1 deg | 2.0 mm, 1.0 deg | 2507 | none found | - | - | - |
| refined, masked | 4.2 mm, 1.81 deg | 23128 | 0.40, 2.05 | 1.65 (wrong) | 0.10 mm, 79 % | 25 s |
| refined, markers kept | 1.03 mm, 0.26 deg | 166607 | 2.03, 5.60 | 3.57 | 0.09 mm, 98 % | 105 s |

With markers masked only 385 points survive (the board is mostly flat white and black squares, which SIFT matches
poorly), and the adjustment drifts away from the truth: worse poses than it started with.

## Remote (11 views, 1080p). Top surface minus board, board poses: 24.32 mm

| poses | pose error | confident cells | top - board | vs board | BA time |
|---|---|---|---|---|---|
| board | 0 | 118312 | 24.32 | - | - |
| noisy 1 mm / 0.5 deg | 1.0 mm, 0.50 deg | 5477 | 25.41 | (too few cells) | - |
| refined, masked | 0.78 mm, 0.29 deg | 90775 | 24.15 | 0.12 mm, 93 % | 76 s |
| refined, markers kept | 0.61 mm, 0.24 deg | 117606 | 24.12 | 0.15 mm, 97 % | 35 s |
| noisy 2 mm / 1 deg | 2.0 mm, 1.0 deg | 3350 | 23.28 | (too few cells) | - |
| refined, masked | 1.35 mm, 0.30 deg | 88871 | 23.84 | 0.20 mm, 83 % | 83 s |
| refined, markers kept | 1.09 mm, 0.36 deg | 120436 | 24.00 | 0.24 mm, 95 % | 48 s |

The remote is textured (printing, key edges), so the masked case gets 2200 points and works.

## Takeaways

- Noisy poses alone break the sweep: confident cells fall 20-40x and the coins vanish.
- Refinement brings back 75-100 % of the confident cells and relative heights to within about 0.1-0.2 mm of the
  board-pose map, whenever the scene has enough texture to match (remote masked, or coins with markers).
- The absolute pose error stays at 0.6-1.1 mm / 0.25-0.36 deg after refinement. That is the shared offset of all
  cameras, which photos cannot see; it comes from the arm prior and tilts the reference plane slightly.
- It fails on a mostly plain scene (coins with markers masked): too few points, and the solution drifts.
- Cost: 20-35 s of matching plus 25-105 s of adjustment on the CPU, versus a 2-5 s sweep. Not tuned (dense pairwise
  matching, finite-difference Jacobian).
