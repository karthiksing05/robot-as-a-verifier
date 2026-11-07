# Plan additions from the scan review (2026-11-06)

## Touch steps chosen by the map (idea 4)

The height map gives a confidence for every 0.25 mm cell. Plain plastic between buttons has low confidence, so the camera can't tell where the panel surface is there.

- After the scan, pick 2-4 tap points on bare panel next to the controls we care about, preferring low-confidence spots that are not inside any SAM outline.
- Tap each one. The contact height fixes the surface there.
- Fit the panel surface to the taps plus the confident camera readings (a plane, or a gently tilted one), and measure each control's rise above that fitted surface instead of the current 30th-percentile estimate.
- Demo line: the camera finds the controls, touch confirms the surface.

## Choosing camera positions (idea 5)

The arm's moves will take longer than the processing (now about 25 s), so fewer, better photos is the lever.

- Heights come from parallax, so the views should be spread out: a ring or grid of positions over the target, a few cm apart, with some tilt, all keeping the target in frame at 15-20 cm.
- Start with a fixed pattern (for example 12 positions on two rings) and measure coin accuracy against the number of views. Drop views until accuracy starts to fall.
- Later: pick extra views where the height map is least confident.

Both depend on the pose-error results in `experiments/pose_tolerance/`, since arm slop decides how far apart views can usefully be.
