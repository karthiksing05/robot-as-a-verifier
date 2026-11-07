# MASt3R poses vs ChArUco board poses

MASt3R is a learned model that estimates camera poses and depth from photos. `run.py` gives it 10 of the 20 views,
undistorted with our calibration, fits its camera centres to the board's with a similarity transform, and runs
`height_test.sweep` with the board poses and with MASt3R's on the same views. Full output is in `log_height.txt`
(the coins) and `log_scan.txt` (the 1080p TV remote).

| Photos | Rotation error, mean (max) | Centre error, mean (max) | Sweep with MASt3R poses |
|---|---|---|---|
| Coins | 0.51° (1.34°) | 0.59 mm (1.15 mm) | 11% of cells confident (32% with board poses), no coins found |
| TV remote | 1.49° (2.24°) | 0.48 mm (0.71 mm) | 4% of cells confident (17%), heights spread -1.0 to 2.0 mm (-0.26 to 0.18) |

The sweep needs each pose to about 0.05-0.1° (`../pose_tolerance/results.md`), so these poses are 5-15 times too
coarse. MASt3R's own dense depth for view 0 is millimetre-level: -1.4 to 0.5 mm (5th to 95th percentile) above the
board on the coins.

## Setup

Not committed: `mast3r/` (a clone of naver/mast3r with its submodules), `.venv/` (torch plus roma, einops, trimesh,
scikit-learn) and `hf/` (the 2.75 GB checkpoint `naver/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric`). It
needs about 4 GB of free VRAM for 10 images at 512 px.

    cd system-1/arm/camera/experiments/mast3r
    .venv/Scripts/python.exe run.py height 10
    .venv/Scripts/python.exe run.py scan_1080 10
