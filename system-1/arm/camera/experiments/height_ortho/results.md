# Height-aware straight-on picture (scan_1080, TV remote)

`run.py` builds three versions of the straight-on picture at 0.1 mm/px. Each one is the median over the 20 photos:

- **c plane**: every pixel projected at the top height (24.32 mm), as `scan_test.orthophoto` does.
- **a per-pixel**: every pixel projected at its own height from the cached height map. Holes are filled by normalised convolution, a 5x5 median filter is applied, and heights are clipped to top-6..top+4 mm.
- **b per-region**: c, then every SAM region from c re-rendered at its own median height and pasted back. 25 regions moved, by -2.4 to +1.2 mm, mostly +0.25 to +0.7 mm (key tops).

Each version then went through the same OWLv2+SAM and `classify` as scan_test.

| | c plane | a per-pixel | b per-region |
|---|---|---|---|
| edge strength, top 5% gradients (object) | 332 | **389** (+17%) | 374 (+12%) |
| edge strength on keys | 355 | **415** | 403 |
| photo disagreement, mean grey MAD (object) | 7.55 | **6.16** (-18%) | 6.88 |
| photo disagreement on keys | 8.48 | **6.74** | 7.46 |
| photo disagreement, 90th pct | 15.7 | **11.9** | 13.4 |
| SAM regions / classified | 38 / 37 | 38 / 37 | 37 / 35 |
| keys outlined (button + rocker) | 34 + 0 | 34 + 1 | 33 + 1 |
| key rise, min / median | 0.78 / 1.6 mm | 1.12 / 1.6 mm (+ one 11.6 mm outlier) | 1.11 / 1.48 mm |

Laplacian variance went slightly down for a and b (217 to 181 and 194). That is expected: the plane picture's doubled, smeared edges add high-frequency noise.

## What the images show

`crops_side_by_side.jpg` shows c, a and b left to right. Labels (EXIT, INFO, CONTENT, arrows) are visibly crisper in a and b. In c they are doubled or soft.

a also adds artifacts where the height map is wrong:

- The power button is torn.
- A dark hole sits on the "1" key.
- A fragment is outlined beside SOURCE (see `map_a_perpixel.jpg`).

Wrong heights near key edges and the remote's rim pull in pixels from the wrong place. b has none of these, because each region gets a single robust height.

The key rises that classify reports come from the height map, not the picture, so they barely change. The lowest readings (0.78 and 0.80 mm in c) went up to about 1.1 mm in a and b. That is consistent with tighter outlines that keep the panel out of the key. a's 11.6 mm "rocker" is a bad outline from those tears.

## Verdict

Per-pixel (a) is the sharpest and has the best photo agreement, but it is only as good as the height map, and it produced visible tears and one bogus part. Per-region (b) gets about 70% of the gain with no artifacts, at the cost of a second render per region (about 25 small warps).

Downstream (region count, keys found, rise values) the three are essentially tied on this remote. Neither change is needed for detection here. The benefit is a cleaner picture for labels and OCR.

If one is integrated, take **(b)**. a would need a more conservative height map first, for example falling back to the plane wherever confidence is low or the height map's local gradient is steep.

Not verified: other objects and scans, and whether the sharper labels improve OWLv2 text queries. Separately, the plane render here differs from `scan_test.orthophoto` by a mean of 5 grey levels. The cause is an implementation difference in the experiment's own renderer: it projects through the lens distortion directly instead of undistorting first, and torch's nanmedian takes the lower middle value rather than the average of the two. All three variants use the same renderer, so the comparison is fair.

Files: `ortho_*.jpg`, `map_*.jpg` (outlines), `crops_side_by_side.jpg`, `spread_c_a_b.jpg` (per-pixel disagreement, brighter means worse), `height_used.png`, `results.json`.
