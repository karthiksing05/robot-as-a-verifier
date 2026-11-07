"""Image models for RGB perception: OWLv2 finds candidate boxes, SAM 2.1 tiny outlines them.

    boxes, scores, labels = owl()(bgr)            # text-prompted boxes; use the boxes, not the labels
    masks, scores = sam_boxes()(bgr, boxes)       # one outline per box
    masks, scores, boxes = sam_auto()(bgr)        # every confident region (sub-parts: lever, pad, knob)

OWLv2 (google/owlv2-base-patch16-ensemble) and SAM 2.1 tiny (facebook/sam2.1-hiera-tiny, via transformers'
Sam2Model). sam_auto re-implements sam2's automatic mask generator defaults: a 32x32 point grid, 3 masks per
point, keep predicted IoU >= 0.8 and stability >= 0.95, box NMS at 0.7. Taken from the reviewed prototype in
scratchpad rgb\\seg\\models.py. Each model loads once; weights come from the Hugging Face cache, downloaded
on first use. About 1-2 s per image on a laptop GPU; OWLv2 takes about 45 s on a CPU.
"""
import functools

import numpy as np
import torch
import torch.nn.functional as F

QUERIES = ["button", "knob", "dial", "slider", "toggle switch", "lcd display", "door"]
OWL_REPO = "google/owlv2-base-patch16-ensemble"
SAM_REPO = "facebook/sam2.1-hiera-tiny"
DEVICE = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"


def _load(cls, repo):
    try:
        return cls.from_pretrained(repo, local_files_only=True)
    except OSError:  # not cached yet
        return cls.from_pretrained(repo)


class Owl:
    def __init__(self, queries=QUERIES):
        from transformers import Owlv2ForObjectDetection, Owlv2Processor
        self.queries = queries
        self.proc = _load(Owlv2Processor, OWL_REPO)
        self.model = _load(Owlv2ForObjectDetection, OWL_REPO).to(DEVICE).eval()

    @torch.no_grad()
    def __call__(self, bgr, threshold=0.05, nms=0.5):
        """Boxes (x0, y0, x1, y1) scoring at least threshold, overlapping boxes merged at IoU nms."""
        from torchvision.ops import nms as box_nms
        rgb = np.ascontiguousarray(bgr[..., ::-1])
        H, W = rgb.shape[:2]
        out = self.model(**self.proc(text=[self.queries], images=rgb, return_tensors="pt").to(DEVICE))
        side = max(H, W)  # OWLv2 pads to a square at the bottom right; boxes are relative to that square
        r = self.proc.image_processor.post_process_object_detection(out, threshold=threshold,
                                                                    target_sizes=[(side, side)])[0]
        keep = box_nms(r["boxes"].float(), r["scores"].float(), nms).cpu().numpy()
        boxes = r["boxes"].cpu().numpy()[keep]
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, W - 1)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, H - 1)
        return boxes, r["scores"].cpu().numpy()[keep], [self.queries[i] for i in r["labels"].cpu().numpy()[keep]]


class _Sam:
    def __init__(self):
        from transformers import Sam2Model, Sam2Processor
        self.proc = _load(Sam2Processor, SAM_REPO)
        self.model = _load(Sam2Model, SAM_REPO).to(DEVICE).eval()

    @torch.no_grad()
    def embed(self, bgr):
        rgb = np.ascontiguousarray(bgr[..., ::-1])
        inp = self.proc(images=rgb, return_tensors="pt").to(DEVICE)
        return self.model.get_image_embeddings(inp["pixel_values"]), rgb.shape[:2]

    @torch.no_grad()
    def decode(self, emb, hw, points=None, boxes=None, multimask=True):
        """Low-res logits (N, M, 256, 256) and IoU predictions (N, M) for N prompts."""
        kw = dict(original_sizes=[list(hw)], return_tensors="pt")
        if points is not None:
            kw.update(input_points=[[[list(map(float, p))] for p in points]], input_labels=[[[1] for _ in points]])
        else:
            kw.update(input_boxes=[[list(map(float, b)) for b in boxes]])
        enc = self.proc(**kw)
        args = {k: enc[k].to(DEVICE) for k in ("input_points", "input_labels", "input_boxes") if k in enc}
        out = self.model(image_embeddings=emb, multimask_output=multimask, **args)
        return out.pred_masks[0], out.iou_scores[0]


class SamBoxes(_Sam):
    @torch.no_grad()
    def __call__(self, bgr, boxes):
        if len(boxes) == 0:
            return [], np.zeros(0)
        emb, (H, W) = self.embed(bgr)
        ms, ss = [], []
        for b in range(0, len(boxes), 64):
            logits, iou = self.decode(emb, (H, W), boxes=boxes[b:b + 64], multimask=False)
            up = F.interpolate(logits[:, :1].float(), (H, W), mode="bilinear", align_corners=False)[:, 0]
            ms.append((up > 0).cpu().numpy())
            ss.append(iou[:, 0].cpu().numpy())
        return list(np.concatenate(ms)), np.concatenate(ss)


class SamAuto(_Sam):
    def __init__(self, points_per_side=32, batch=32, pred_iou=0.8, stability=0.95, nms=0.7):
        super().__init__()
        self.pps, self.batch, self.pred_iou, self.stability, self.nms = points_per_side, batch, pred_iou, stability, nms

    @torch.no_grad()
    def __call__(self, bgr):
        from torchvision.ops import batched_nms, masks_to_boxes
        emb, (H, W) = self.embed(bgr)
        xs = (np.arange(self.pps) + 0.5) / self.pps
        pts = np.stack(np.meshgrid(xs * W, xs * H), -1).reshape(-1, 2)
        keep_m, keep_s = [], []
        for b in range(0, len(pts), self.batch):
            logits, iou = self.decode(emb, (H, W), points=pts[b:b + self.batch])
            logits, iou = logits.flatten(0, 1), iou.flatten()
            sel = iou >= self.pred_iou
            if not sel.any():
                continue
            up = F.interpolate(logits[sel][:, None].float(), (H, W), mode="bilinear", align_corners=False)[:, 0]
            stab = (up > 1.0).sum((1, 2)).float() / (up > -1.0).sum((1, 2)).float().clamp(min=1)
            ok = (stab >= self.stability) & ((up > 0).sum((1, 2)) > 0)
            keep_m.append(up[ok] > 0)
            keep_s.append(iou[sel][ok])
        if not keep_m:
            return [], np.zeros(0), np.zeros((0, 4))
        m, s = torch.cat(keep_m), torch.cat(keep_s)
        boxes = masks_to_boxes(m).float()
        k = batched_nms(boxes, s, torch.zeros_like(s, dtype=torch.long), self.nms)
        return list(m[k].cpu().numpy()), s[k].cpu().numpy(), boxes[k].cpu().numpy()


owl = functools.cache(Owl)
sam_boxes = functools.cache(SamBoxes)
sam_auto = functools.cache(SamAuto)
