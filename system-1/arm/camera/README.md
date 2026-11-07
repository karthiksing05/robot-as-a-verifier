# Wrist camera bench test

Checks the Innomaker U20CAM-1080P against what the simulation assumes about it (`system-1/sim/sensors.py`, the `USB_*` constants), and measures the numbers the sim only guessed. Each step prints the measured value next to the sim's. Results so far are in [results.md](results.md). Windows only: frames come through ffmpeg's DirectShow input, because OpenCV's DirectShow backend is stuck at uncompressed 10 fps with this module.

## Before you start

- Close every app that might hold the camera: the Windows Camera app, and Teams if it's showing a camera. If a step says it can't open the camera even then, unplug and replug it.
- Don't refocus the lens yet. The focus step measures where it focuses out of the box.
- Put `calib_board_tab_s9fe.png` on the Galaxy Tab S9 FE and open it full screen, landscape. It's exactly 2304 x 1440, the tab's resolution, so it shows pixel for pixel: 9 x 6 squares of 23.7 mm. Turn the tab's brightness up and auto-rotate off.
- In PowerShell:

```bash
cd system-1\arm\camera
```
```bash
$PY = "..\..\..\.venv\Scripts\python.exe"
```

Results land in `camera_out/` (git keeps only `calib.json`). Needs ffmpeg on the PATH, or set `FFMPEG`. `uv sync --extra sim` installs PyTorch without CUDA, so the height sweep and the image models run on the CPU, several times slower.

Everything captures at 1920x1080 by default; add `--720` to any command for 1280x720. Focus and noise always run at 720p, because they compare per-pixel numbers with the sim's 720p model. A calibration done at one size is scaled automatically for photos of the other.

## 1. Info (done)

```bash
& $PY camera_test.py info
```

Modes, real frame rate, JPEG quality from a raw frame, and which controls exist. Measured: MJPEG quality about 51 (the sim guessed 80), no focus control, exposure and white balance settable.

## 2. Crop check (10 s)

```bash
& $PY camera_test.py crop
```

Aim the camera at something detailed, like the room or a shelf, and keep it still. It takes one frame at 1280x720 and one at 1920x1080 and compares them.

This settles whether 720p shows the whole view scaled down, which is what the sim assumes and what gives its 621 px focal length, or a crop of the middle. A crop would explain attempt 1's 831 px focal length. It also decides whether the scan should use 1080p.

## 3. Lens calibration on the tablet (3 to 5 min)

```bash
& $PY camera_test.py calib
```

A live preview opens on the laptop with a 16 x 9 grid. Hold the camera 12 to 35 cm from the tablet. Move the board into every part of the picture, especially the corners and edges, at different tilts, and hold still each time. It captures when the board is steady (a beep) and colours the grid cells it covered. It finishes at 85% coverage with 30 or more views, or press q.

It measures the focal length, image centre, distortion and true field of view, with the richer 8-coefficient lens model, and saves `calib.json`. At 1080p, expect a focal length near 1236 px and centre near (961, 561): the previous 720p calibration (824 px) times 1.5. Refocusing shifts these a little. The sim's 720p lens, scaled to 1080p, is 932 px. Pixel errors are 1.5x larger at 1080p for the same quality, so a good result is under about 0.75 px. The 720p calibration from before the refocus is kept in `camera_out/calib_720p_before_refocus/`.

## 4. Calibration report

```bash
& $PY camera_test.py report
```

This writes `camera_out/calib_report.png`, four plots:
- where the board was seen, with each corner's error as an arrow;
- the error per view, where a tall bar is a blurry view;
- the lens's projection against the sim's;
- an uncertainty map: how far a point could be off in each part of the image, from redoing the calibration on resampled views (the main idea behind mrcal's uncertainty plots).

Dark everywhere means calibrated everywhere. `calib_report_laptop_attempt1.png` shows what a bad one looks like.

## 5. Focus sweep (1 min, needs step 3)

```bash
& $PY camera_test.py focus
```

Tablet board again. Start about 50 cm away and move slowly straight in to about 6 cm over 40 s, then back out.

It measures blur against distance and where the lens is sharpest. The sim assumes it's been refocused to 12 cm, with 0.6 px of blur in focus. If the sharpest point is far from 12 cm, the lens needs refocusing before it goes on the arm.

## 6. Noise (15 s)

```bash
& $PY camera_test.py noise
```

Grey bars fill the laptop screen. Prop the camera so it can't move, facing the bars and filled by them. It locks exposure and white balance, then records 60 frames, and compares the noise at each brightness with the sim's model (11,000 electrons at white, 4 electrons of read noise).

## 7. Real controls (a few minutes)

```bash
& $PY camera_test.py snap
```

Point it at a TV remote, thermostat or light switch from about 12 cm. Use the on-screen sharpness number to find the best distance, press space to save, and take 3 or 4. Then:

```bash
& $PY camera_test.py seg
```

This runs the robot's own image models (OWLv2 boxes, SAM outlines) on each photo and writes `seg_*.jpg`. Check that each button gets its own outline.

## Undistorted view (any time after step 3)

```bash
& $PY camera_test.py undistort
```

Live raw and undistorted views side by side, with a straight green grid to judge lines against. `a` switches between the whole view (curved black edges) and a crop to real image, `s` saves, `q` quits. Add photo paths after `undistort` to straighten saved photos instead.

## 8. Heights and the full scan

```bash
& $PY height_test.py capture
```
```bash
& $PY scan_test.py capture
```
```bash
& $PY scan_test.py scan
```

Both capture at 1920x1080 by default (add `--720` for 1280x720). The calibration from step 3 is at 720p and gets scaled to the photo size automatically. For the remote, lay it along the board's long side so it fits on the board. To compare resolutions from one set of photos, also run `& $PY scan_test.py scan --720`: it shrinks the photos to 720p and saves `scan_map_720.jpg` beside `scan_map.jpg`.

## 9. Pose correction on a real object

```bash
& $PY pose_test.py --dir scan_1080 --error 1,3
```

Uses the photos of a scan capture. Each photo's board-measured pose gets a random error of the size given (degrees, millimetres), then the pipeline's own correction (`rgbperceive.adjust`) re-estimates the poses from the object's features, with the board left out. It prints how far the heights land from the board-pose heights, before and after. Run it on photos of the real appliance: a panel without enough printing keeps the wrong poses.

## Then

Send the printed output and the report and seg images. I'll update the sim's camera model (JPEG quality 51, and the lens from the good calibration) and rerun its perception benchmark to see what the real camera changes.
