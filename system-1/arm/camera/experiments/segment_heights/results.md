# Segment-based heights: results

Question: instead of taking each 0.25 mm cell's own best height and then a median, does choosing one height (or one
tilted plane) per SAM region, by summing the sweep's matching cost over the region, make the ten number keys agree?

Script: `segment_heights.py` (`remote` / `coins`). Its sweep is a copy of `height_test.sweep` that also returns the
cost volume; on scan_1080 it reproduces the pipeline's cached height map exactly (max difference 0.0 mm). Masks are the
pipeline's own (`scan_test.part_masks`), cached in `remote_masks.npz`. Each key's "top" is the eroded mask and its
"ring" is the same ~12 mm surround `classify` uses (object only, outside every part).

Variants:
- current: median confident height on the top minus the 30th percentile of confident ring heights (`classify`).
- median conf cells: same cells, plain median on both sides (cheap variant, no cost volume).
- cost sum: one height per region where the summed cost is lowest, parabola-refined; unweighted, or weighted by
  confidence or by image texture.
- plane: a tilted plane (+-0.15 mm/mm, 0.05 steps) fitted to the ring's summed cost (and optionally the top's),
  read at the key's centre.

## Number keys (should all be equal), scan_1080

Keys 1-9 and 0 are rows 2,4,5,7,8,9,10,11,13,14 in `remote_rows.json` (matched against `ortho.jpg`).

| variant | mean rise | range | spread | sd |
|---|---|---|---|---|
| current (p30 ring) | 1.36 | 1.12-1.63 | 0.50 | 0.16 |
| median conf cells | 0.98 | 0.58-1.38 | 0.80 | 0.29 |
| cost sum | 1.13 | 0.83-1.45 | 0.62 | 0.20 |
| cost sum, conf-weighted | 0.88 | 0.49-1.32 | 0.83 | 0.31 |
| cost sum, texture-weighted | 0.70 | 0.30-1.16 | 0.86 | 0.28 |
| flat top, plane ring | 0.76 | 0.45-1.27 | 0.82 | 0.26 |
| plane top + plane ring | 0.74 | 0.45-1.42 | 0.98 | 0.28 |

Full per-part list for all 37 parts and all variants: `remote_log.txt`. Below the number pad (rows 15-36, the larger
and more textured keys) every variant agrees with current to within about 0.3 mm.

## Coins (truth: single 1.75 above board + glass bias, stack minus single 3.50)

| variant | single | stack | stack - single |
|---|---|---|---|
| current | 2.09 | 5.54 | 3.45 |
| median conf cells | 2.06 | 5.51 | 3.45 |
| cost sum | 2.05 | 5.49 | 3.44 |
| cost sum, conf-wt | 2.05 | 5.50 | 3.44 |
| cost sum, texture-wt | 2.05 | 5.49 | 3.44 |
| flat top, plane ring | 2.05 | 5.48 | 3.43 |
| plane top + plane ring | 2.03 | 5.49 | 3.46 |

On a textured surface all methods agree within 0.03 mm, so the coins can't separate them.

## Verdict

None of the segment methods beats the current p30 rule on the number keys; all of them spread more (0.62-0.98 mm vs
0.50 mm). Summing cost doesn't rescue the plain plastic: those cells have nearly flat cost curves, so they add almost
nothing to the sum, and the region's answer is decided by the same few textured cells (key edges, printed digits) that
already decide the per-cell median. Weighting by texture or confidence makes that worse, not better, and the tilted
plane adds freedom the data can't pin down. Of the cost-volume variants, plain unweighted cost sum is closest to
current. The cheap "plain median" variant is the worst of the simple ones, which says the p30 in `classify` is doing
real work (it keeps the ring off neighbouring keys' raised edges).

Recommendation: integrate nothing from this; keep `classify` as is. The limit is the missing texture on the panel
between keys, not how the per-cell costs are combined, so the fix has to add signal (e.g. projected texture or touch).
