# Active texture on plain dark plastic (simulated)

Question: plain black plastic gives `height_test.sweep` nothing to match. Does projecting texture fix that?

## How it was tested

`active_texture.py` renders an 80 x 60 mm matte black panel (albedo 0.06, 2% low-frequency albedo variation) with four
raised buttons, 1 and 2 mm tall, the same black as the panel. Rendering is a small numpy ray caster, not MuJoCo: MuJoCo
lights cannot project an image, so the pattern brightness is computed per surface point from a pinhole projector model.
The camera uses the real calibrated focal length (`camera_out/calib.json`, 1920x1080, no lens distortion). Each frame
gets shot and read noise, 8-bit quantising and JPEG quality 85. 20 views from 15-20 cm, +-3 cm sideways, aimed near
the panel centre, with exact poses.

The three sweep variants run through `height_test.sweep` unchanged (grid resized to the panel, heights -1 to 4 mm).
A cell counts as covered when confidence > 0.5, the threshold `find_coins` uses. Cells within 1 mm of a button edge
are left out of the scoring.

- **plain**: room light only.
- **fixed**: random-dot slide (~0.3 mm dots) from a projector fixed 25 cm over the panel, 2x the room light on the dots.
- **wrist**: the same projector 4 cm beside the camera, moving with it.
- **laser**: a laser sheet 5 cm beside the camera, crossing the optical axis at 17 cm. The camera steps across the
  panel in 0.5 mm moves (220 frames); per image column, the brightest row (sub-pixel parabola fit) is intersected with
  the known laser plane. No sweep involved.

## Results

| variant | button coverage | button error (median / p90) | panel coverage | panel error (median / p90) |
|---|---|---|---|---|
| plain | 0% | - | 0% | - |
| fixed projector | 37% | 0.014 / 0.041 mm | 38% | 0.011 / 0.028 mm |
| wrist projector | 0% | - | 0% | - |
| wrist laser line | 100% | 0.005 / 0.011 mm | 100% | 0.005 / 0.011 mm |

## What it means

- Plain black plastic is invisible to the sweep, as on the real rig: every height matches equally well.
- A fixed pattern works. Wherever the sweep trusts a cell, the height is right to a few hundredths of a mm. Coverage is
  only ~38% because the dots on black plastic are dim (about 15 to 45 of 255), so many cells fall below the confidence
  cut. A brighter projector or a lighter surface would raise it; not tested.
- A projector on the wrist breaks the sweep completely. The sweep assumes a surface point looks the same in every photo;
  with the pattern moving with the camera, the same point is lit differently in each view, so no height agrees. Making
  it work needs a different algorithm (treat the projector as a second camera and calibrate it, one view at a time),
  not a tweak to ours.
- The laser line is the most accurate and covers everything. These numbers are optimistic: poses are exact and the
  laser plane is known exactly. On the real arm, pose error (SO-101 slop) and laser-plane calibration error add
  straight onto the height, so expect tenths of a mm, not 5 microns. It also needs ~200 frames per panel versus 20.

## Recommendation

Use a wrist-mounted line laser: it is the only option that rides on the arm and still works, and it does not depend
on surface texture at all. Hardware: a 5 mW red line-laser module (650 nm, ~$5-10, often sold as a "line laser
diode" for level tools), mounted 4-6 cm from the camera and tilted to cross the view at scan distance. Calibrate the
laser plane once by imaging the line on the flat calibration board at two heights.

If a fixed projector is available (any small projector or phone showing a random-dot image), it drops into the
existing sweep with no code changes, but it must stay still relative to the panel.

Not verified: real laser speckle and ambient light on glossy plastic, shadowing behind buttons, and pose noise. The
renderer has no occlusion or shadows from the projector or laser.
