"""Scene camera: where the camera is, where the appliance is, where each control is.

Follows the plan's perception design:
1. The ChArUco board printed on the desk plate sits at a known pose in the arm frame,
   so seeing it gives the camera's pose. No hand-eye calibration, and a bumped camera
   is fixed on the next look.
2. One ArUco tag on the fixture plate gives the fixture's pose. Each control's CAD
   offset then puts it in the arm frame. These are the positions the skills use.
3. A detector finds the button caps in the image. Each detection is cast onto the CAD
   surface and compared with step 2, and anything over 5 mm apart is flagged. Here the
   detector is a colour threshold standing in for Grounding DINO.

    python vision.py 20      localization error over 20 random placements
"""
import os
import sys

import cv2
import mujoco
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))  # rig.py, as a script
import appliance as A  # noqa: E402

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
BOARD = cv2.aruco.CharucoBoard(A.BOARD_SQUARES, A.BOARD_SQUARE_M, A.BOARD_MARKER_M, DICT)
_params = cv2.aruco.DetectorParameters()
_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
MARKERS = cv2.aruco.ArucoDetector(DICT, _params)
CHARUCO = cv2.aruco.CharucoDetector(BOARD)
TEX_PX_PER_M = 7200  # 60 px per tag cell
FLAG_MM = 5.0


class LookFailed(Exception):
    pass


def _T(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def _rays(px, T_base_cam, K):
    """Camera origin and the arm-frame direction through each pixel."""
    d = (T_base_cam[:3, :3] @ np.linalg.inv(K) @ np.c_[px, np.ones(len(px))].T).T
    return T_base_cam[:3, 3], d


def _pnp(obj, img, K):
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    return _T(cv2.Rodrigues(rvec)[0], tvec.ravel())


# Printed patterns use OpenCV's frame: origin at the image's top-left, x right, y down,
# z into the surface. MuJoCo stretches a texture over a box's top face with image
# right along +x and image down along -y.
_FACE = np.diag([1.0, -1.0, -1.0])
_bw, _bh = A.BOARD_SQUARES[0] * A.BOARD_SQUARE_M / 2, A.BOARD_SQUARES[1] * A.BOARD_SQUARE_M / 2
T_BASE_BOARD = _T(_FACE, A.BOARD_CENTER + [-_bw, _bh, 0])
T_FIXTURE_TAG = _T(_FACE, A.FIXTURE_TAG_AT)
_s = A.FIXTURE_TAG_M / 2
TAG_CORNERS = np.array([[-_s, -_s, 0], [_s, -_s, 0], [_s, _s, 0], [-_s, _s, 0]])  # TL TR BR BL


def write_textures(folder):
    sq = round(A.BOARD_SQUARE_M * TEX_PX_PER_M)
    board = BOARD.generateImage((A.BOARD_SQUARES[0] * sq, A.BOARD_SQUARES[1] * sq))
    _save_png(os.path.join(folder, "_charuco.png"), board)
    border = round(0.01 * TEX_PX_PER_M)
    tag = cv2.aruco.generateImageMarker(DICT, A.FIXTURE_TAG_ID, round(A.FIXTURE_TAG_M * TEX_PX_PER_M))
    tag = cv2.copyMakeBorder(tag, border, border, border, border, cv2.BORDER_CONSTANT, value=255)
    _save_png(os.path.join(folder, "_fixture_tag.png"), tag)


def _save_png(path, img):
    """Write the PNG unless the file already holds it: another sim may be loading it right now."""
    data = cv2.imencode(".png", img)[1].tobytes()
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return
    with open(path, "wb") as f:
        f.write(data)


class Camera:
    """The scene camera. On the rig this is the iPhone read through OpenCV."""

    def __init__(self, model, noise=3.0, seed=0):
        self.w, self.h = A.CAMERA_RES
        self.r = mujoco.Renderer(model, self.h, self.w)
        self.m = model
        f = self.h / 2 / np.tan(np.radians(A.CAMERA_FOVY) / 2)
        self.K = np.array([[f, 0, self.w / 2], [0, f, self.h / 2], [0, 0, 1]])  # real rig: from ChArUco calibration
        self.noise = noise
        self.rng = np.random.default_rng(seed)
        self.target_geom = model.body("target").geomadr[0]

    def grab(self, data):
        alpha = self.m.geom_rgba[self.target_geom, 3]
        self.m.geom_rgba[self.target_geom, 3] = 0  # the follow-mode sphere isn't on the real rig
        self.r.update_scene(data, camera="scene_cam")
        img = self.r.render()[:, :, ::-1].astype(np.float32)
        self.m.geom_rgba[self.target_geom, 3] = alpha
        img += self.rng.normal(0, self.noise, img.shape)
        return np.clip(img, 0, 255).astype(np.uint8)

    def close(self):
        self.r.close()  # a second Renderer renders black while the first is open


def board_pose(gray, K):
    """Camera pose in the arm frame from the desk board, and the board corners it used."""
    cc, ci, _, _ = CHARUCO.detectBoard(gray)
    if ci is None or len(ci) < 6:
        raise LookFailed("desk board not visible (need 6 corners)")
    T_cam_board = _pnp(BOARD.getChessboardCorners()[ci.ravel()], cc, K)
    return T_BASE_BOARD @ np.linalg.inv(T_cam_board), cc


def look(img, K, cad_controls):
    """Image in, controls in the arm frame out (plus what was seen, for the overlay)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. camera pose from the desk board
    T_base_cam, cc = board_pose(gray, K)

    # 2. fixture pose from its tag. The plate sits on the same desk as the arm, so its
    # height is known: cast the tag's corners onto that plane and fit x, y and heading.
    # Solving the tag's full pose from its own 4 corners instead was about 3.6 mm off.
    corners, ids, _ = MARKERS.detectMarkers(gray)
    hit = [] if ids is None else [c for c, i in zip(corners, ids.ravel()) if i == A.FIXTURE_TAG_ID]
    if not hit:
        raise LookFailed(f"fixture tag {A.FIXTURE_TAG_ID} not visible")
    o, rays = _rays(hit[0].reshape(4, 2), T_base_cam, K)
    z = A.FIXTURE_ORIGIN[2] + A.FIXTURE_TAG_AT[2]
    seen = (o + rays * ((z - o[2]) / rays[:, 2])[:, None])[:, :2]
    cad = (T_FIXTURE_TAG[:3, :3] @ TAG_CORNERS.T).T[:, :2] + A.FIXTURE_TAG_AT[:2]
    a, b = cad - cad.mean(0), seen - seen.mean(0)  # 2D rigid fit
    yaw = np.arctan2((a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum(), (a * b).sum())
    R = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    T_base_fixture = _T(R, [*(seen.mean(0) - R[:2, :2] @ cad.mean(0)), A.FIXTURE_ORIGIN[2]])
    controls = A.moved(cad_controls, T_base_fixture)

    # 3. detector cross-check
    checks = cross_check(img, controls, T_base_cam, K)
    return {"controls": controls, "T_base_cam": T_base_cam, "T_base_fixture": T_base_fixture,
            "checks": checks, "board_corners": cc, "tag_corners": hit[0]}


def find_caps(img):
    """Stand-in detector: pixel centres of saturated blobs (the button caps)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] > 150) & (hsv[..., 2] > 60)).astype(np.uint8)
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask)
    return [cent[i] for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 30]


def project(points, T_base_cam, K):
    T = np.linalg.inv(T_base_cam)
    px, _ = cv2.projectPoints(np.array(points, float), cv2.Rodrigues(T[:3, :3])[0], T[:3, 3], K, None)
    return px.reshape(-1, 2)


def cross_check(img, controls, T_base_cam, K, match_px=30):
    """Match each detection to the nearest predicted control, cast it onto that control's
    surface plane, and report how far it lands from the CAD position."""
    buttons = [c for c in controls.values() if c.kind == "button"]
    predicted = project([c.pos for c in buttons], T_base_cam, K)
    blobs = find_caps(img)
    out = {}
    for c, p in zip(buttons, predicted):
        near = [b for b in blobs if np.linalg.norm(b - p) < match_px]
        if not near:
            out[c.name] = {"seen": False, "flag": True}
            continue
        b = min(near, key=lambda b: np.linalg.norm(b - p))
        o, (ray,) = _rays([b], T_base_cam, K)
        hit = o + ray * ((c.pos - o) @ c.normal) / (ray @ c.normal)
        off = float(np.linalg.norm(hit - c.pos)) * 1000
        out[c.name] = {"seen": True, "px": b, "off_mm": round(off, 1), "flag": off > FLAG_MM}
    return out


def draw(img, seen, K):
    out = img.copy()
    cv2.aruco.drawDetectedCornersCharuco(out, seen["board_corners"].reshape(-1, 1, 2).astype(np.float32))
    cv2.aruco.drawDetectedMarkers(out, [seen["tag_corners"].reshape(1, 4, 2).astype(np.float32)])
    cs = list(seen["controls"].values())
    for c, p in zip(cs, project([c.pos for c in cs], seen["T_base_cam"], K)):
        p = tuple(int(v) for v in p)
        cv2.circle(out, p, 6, (0, 255, 255), 2)
        chk = seen["checks"].get(c.name, {})
        label = c.name + (f" det {chk['off_mm']}mm" if chk.get("seen") else " (not detected)" if chk else "")
        cv2.putText(out, label, (p[0] + 9, p[1] - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 255) if chk.get("flag") else (0, 255, 255), 1, cv2.LINE_AA)
        if chk.get("seen"):
            q = tuple(int(v) for v in chk["px"])
            cv2.drawMarker(out, q, (255, 0, 255), cv2.MARKER_CROSS, 10, 1)
    return out


def errors(perceived, truth):
    """Sim only: per control, (lateral, along-normal) error in mm."""
    out = {}
    for k, c in perceived.items():
        d = c.pos - truth[k].pos
        along = d @ truth[k].normal
        out[k] = (round(float(np.linalg.norm(d - along * truth[k].normal)) * 1000, 2), round(float(along) * 1000, 2))
    return out


if __name__ == "__main__":
    from robot import SimArm

    rng = np.random.default_rng(1)
    lat, nrm, det = [], [], []
    for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 20):
        arm = SimArm("B", placement=A.random_placement(rng))
        cam = Camera(arm.m, seed=i)
        seen = look(cam.grab(arm.d), cam.K, A.controls(arm.params))
        e = errors(seen["controls"], arm.true_controls())
        lat += [v[0] for v in e.values()]
        nrm += [abs(v[1]) for v in e.values()]
        det += [c["off_mm"] for c in seen["checks"].values() if c["seen"]]
        cam.close()
        print(f"{i:2d} fixture {np.round(arm.placement['fixture'], 3).tolist()}  lateral mm {[v[0] for v in e.values()]}"
              f"  detector mm {[c.get('off_mm') for c in seen['checks'].values()]}")
    for name, v in (("lateral", lat), ("normal", nrm), ("detector vs CAD", det)):
        print(f"{name:>16}: median {np.median(v):.2f} mm, max {np.max(v):.2f} mm")
