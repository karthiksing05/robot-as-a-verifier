"""Simulated cameras: the iPhone on its tripod (RGB plus LiDAR) and the wrist depth camera.

    wrist = WristCamera(arm)          # RealSense D405 class, on the gripper
    wrist = WristCamera(arm, usb=True)  # or the $19 USB RGB module the team plans: no depth
    f = wrist.capture()               # Frame: rgb (BGR), depth (m), K, T_base_cam, t
    pts, rgb, px = rig.backproject(f) # valid depth pixels as arm-frame points
    phone = PhoneCamera(arm)          # scene_cam: 1280x720 RGB, LiDAR depth upsampled to it
    g = phone.capture()               # g.raw_depth is the LiDAR's native 256x192 map
    wrist.close(); phone.close()

Poses use OpenCV's camera axes (x right, y down, z forward) and are what the controller
believes: the wrist camera's comes from the joint readings (so joint offsets carry through)
plus a small hand-eye calibration error, the phone's from the desk board. Images are rendered
from where the cameras really are. ideal=True turns off every error and all noise, for checks
against sim truth. A capture takes about 0.1 to 0.15 s (the phone's first about 1 s more, as it
also solves the board), so a video loop should show the last frame instead of capturing on
every video frame.
"""
import cv2
import mujoco
import numpy as np

import vision
from rig import Frame, _cv_pose

# RealSense D405: 18 mm stereo baseline, 0.08 px matching error, 7 to 50 cm, 0.1 mm depth steps
D405_BASELINE_M = 0.018
D405_SUBPIXEL_PX = 0.08
D405_RANGE_M = (0.07, 0.50)
D405_EDGE_PX = 4.0       # a disparity jump this big within 3x3 pixels is an occlusion edge (6 mm at 11 cm)
D405_DROPOUT = 0.003     # fraction of pixels lost at random
D405_DISPARITIES = 128   # stereo=True: the D4 chip searches 128 disparities (6.1 cm and out at 848x480)
D405_BLOCK = 5           # stereo=True: matching window (px), a guess; the chip's 9x9 is a census window, not a block
HAND_EYE_ERR = (0.0007, 0.3)  # (m, deg) left after calibrating the wrist camera mount
# usb=True: a $19 Innomaker U20CAM-1080P-S1, the 32x32 mm module the SO-ARM100 wrist mount README recommends. Its
# datasheet: 1/3" rolling-shutter 1920x1080 sensor, M12 lens f 2.8 mm F2.3, 103-106 deg across with -17% TV
# distortion, MJPEG 1280x720 at 30 fps (uncompressed YUY2 manages 10 fps at that size). The bench measured it
# (system-1/arm/camera/results.md): a 3.7 mm lens, 97 x 51 deg raw, MJPEG 1920x1080 at 30 fps. The constants below
# are the bench's
USB_RES = (1920, 1080)
USB_LENS = (1242.7, 0.8823, (960.15, 558.23))  # the real lens in 1080p px: f, b and centre of r = f sin(b theta) / b,
                                               # fitted to the bench calibration to 0.19 px RMS out to 52 deg
# The bench calibration at 1920x1080 (system-1/arm/camera/camera_out/calib.json: OpenCV's rational model, 73 views,
# 0.31 px). The host undistorts with it, so a frame claims this K and its view is 75 x 47 deg
USB_CAL_K = np.array([[1241.697, 0, 960.151], [0, 1242.352, 558.234], [0, 0, 1]])
USB_CAL_DIST = np.array([0.105864, -0.406186, -0.00046025, -0.000208345, -0.0319177, 0.563696, -0.47543,
                         -0.167647, 0, 0, 0, 0, 0, 0])
USB_RENDER_FOVY = 49.0   # the render the lens samples: a little wider than the 47 deg undistorted frame, the only
                         # part of the raw frame the host keeps
# thin-lens defocus: f, an effective F-number and one 1080p pixel on the sensor, fitted with USB_FOCUS_M and
# USB_SOFT_PX to the bench focus sweep (720p blur x 1.5: about 0.95 px at 9 cm, 0.74 at 13, 0.36 from 25 to 55 cm)
USB_F_MM, USB_FNUM, USB_PX_MM = 3.7, 11.0, 0.00298
USB_FOCUS_M = 0.35       # as shipped, focus is broad and somewhere around 25 to 45 cm
USB_SOFT_PX = 0.35       # in-focus blur sigma (px at 1080p): lens, Bayer demosaic, the ISP
USB_WHITE_E = 2900       # electrons in a white 1080p pixel: the bench's mid-tone noise (30% above the earlier 11000
                         # at 720p, so about 6500 there) over 2.25 times smaller pixels
USB_READ_E = 4.0         # read noise (electrons), an assumption
USB_JPEG_Q = 51          # the module's MJPEG quality, from a captured frame's quantization table
USB_AUTO = False         # True: UVC's default auto exposure and white balance; False: both locked
PHONE_RES = (1280, 720)  # 16:9 video, the middle of the camera's 4:3 frame
STILL_RES = (1920, 1440)  # ARKit's full 4:3 frame, used to solve the board
LIDAR_RES = (256, 192)   # ARKit's sceneDepth, over the full 4:3 frame
LIDAR_BLUR_PX = 2.0      # about 7 mm at the device, so features under about 1 cm blur away
LIDAR_NOISE_M = 0.003


def _K(fovy_deg, w, h):
    """Intrinsics of a MuJoCo camera: square pixels, centred, pixel centres at whole numbers."""
    f = h / 2 / np.tan(np.radians(fovy_deg) / 2)
    return np.array([[f, 0, (w - 1) / 2], [0, f, (h - 1) / 2], [0, 0, 1]])


def usb_lens_rays(size=USB_RES):
    """Where each raw pixel of the USB module really looks: x/z and y/z of its ray, two HxW arrays."""
    f, b, (cx, cy) = USB_LENS
    u, v = np.meshgrid(np.arange(size[0], dtype=np.float64), np.arange(size[1], dtype=np.float64))
    x, y = (u - cx) / f, (v - cy) / f
    r = np.hypot(x, y)
    s = np.tan(np.arcsin(np.minimum(b * r, 1.0)) / b) / np.maximum(r, 1e-12)  # r = sin(b theta) / b
    return x * s, y * s


def usb_raw(lin, z, rng, gain=1.0):
    """What the USB module sends, from linear light (HxWx3, 1 = white) and depth (m, 0 = far) per raw pixel:
    defocus and lens blur, shot and read noise, exposure gain (per channel for white balance), MJPEG. BGR."""
    d = np.where(z > 0, z, np.float32(100)) * 1000
    s, f = USB_FOCUS_M * 1000, USB_F_MM
    c = f * f * np.abs(s - d) / (USB_FNUM * d * (s - f)) / USB_PX_MM  # thin lens: blur disc diameter, px
    levels = [0, 1, 2, 3, 4, 6, 8, 11, 16, 23]
    levels = levels[:max(2, int(np.searchsorted(levels, c.max())) + 1)]
    i = np.float32(np.interp(c, levels, np.arange(len(levels))))[..., None]  # each pixel between two blur levels
    img = sum(np.maximum(0, 1 - np.abs(i - k)) * (cv2.filter2D(lin, -1, _disc(dia)) if dia else lin)
              for k, dia in enumerate(levels))
    e = cv2.GaussianBlur(img, (0, 0), USB_SOFT_PX) * USB_WHITE_E
    e += rng.standard_normal(e.shape, np.float32) * np.sqrt(np.maximum(e, 0) + USB_READ_E**2)
    out = (np.clip(e * (np.asarray(gain) / USB_WHITE_E), 0, 1) ** (1 / 2.2) * 255).round().astype(np.uint8)
    jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, USB_JPEG_Q,
                                     cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_422])[1]
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR)


def _disc(dia):
    """Normalised disc kernel dia px across, its rim anti-aliased."""
    r = dia / 2
    n = int(np.ceil(r))
    y, x = np.mgrid[-n:n + 1, -n:n + 1]
    k = np.clip(r + 0.5 - np.hypot(x, y), 0, 1)
    return (k / k.sum()).astype(np.float32)


class _SimCamera:
    """One of the model's cameras, rendered offscreen."""

    def __init__(self, arm, cam, size, ideal, seed):
        self.arm, self.m = arm, arm.m
        self.cam = arm.m.camera(cam).id
        self.ideal = ideal
        self.rng = np.random.default_rng(seed)
        self.r = self._renderer(size)
        self.target = self.m.body("target").geomadr[0]

    def _renderer(self, size):
        vis = self.m.vis.global_  # make room in the offscreen buffer, whatever the scene asked for
        vis.offwidth, vis.offheight = max(vis.offwidth, size[0]), max(vis.offheight, size[1])
        return mujoco.Renderer(self.m, size[1], size[0])

    def _render(self, fovy=None, r=None, depth=True):
        """BGR image and depth (m along the optical axis, 0 where nothing was hit; None if not depth)."""
        m = self.m
        r = self.r if r is None else r
        alpha, old_fovy = m.geom_rgba[self.target, 3], m.cam_fovy[self.cam]
        m.geom_rgba[self.target, 3] = 0  # the follow-mode sphere isn't on the rig
        if fovy is not None:
            m.cam_fovy[self.cam] = fovy
        r.update_scene(self.arm.d, camera=self.cam)
        m.geom_rgba[self.target, 3], m.cam_fovy[self.cam] = alpha, old_fovy
        if hasattr(self.arm.app, "refresh_lcd"):  # a generated device's LCD texture changes as it runs
            self.arm.app.refresh_lcd(r)
        rgb = r.render()[:, :, ::-1].copy()
        if not depth:
            return rgb, None
        r.enable_depth_rendering()
        z = r.render()
        r.disable_depth_rendering()
        z[z > 0.99 * m.vis.map.zfar * m.stat.extent] = 0
        return rgb, z

    def true_pose(self):
        """Sim truth: where the camera really is (4x4, OpenCV axes)."""
        return _cv_pose(self.arm.d, self.cam)

    def close(self):
        self.r.close()


class WristCamera(_SimCamera):
    """RealSense D405 class RGB-D camera under the gripper's fixed jaw (wrist_cam).

    Depth noise is the stereo error model, sigma_z = z^2 * 0.08 px / (f * 18 mm baseline), with
    no depth under 7 cm or over 50 cm, none where the disparity jumps by over 4 px (occlusion
    edges, where real stereo gives flying pixels), 0.3% random dropouts, and 0.1 mm steps.
    RGB gets a slight blur and light noise.

    stereo=True matches depth from two renders instead, as a D405 does: it has no projector, so
    depth comes from the scene's own texture. wrist_cam is the left imager and a second render
    18 mm along the camera's x is the right one. OpenCV's semi-global matcher stands in for the
    D4 chip's, whose thresholds Intel doesn't publish. So plain surfaces give holes and wrong
    depths, thin parts come out 1 to 2 mm wider and narrow seams shallower, a band at the left
    edge that the right imager can't see has no depth (about 70 px at 11 cm), and textured
    surfaces match to 0.2 to 0.25 px. MuJoCo's plastic has no micro-texture, so plain surfaces
    are a worst case. A capture takes about twice as long. ideal=True still gives true depth.

    usb=True is the team's actual wrist camera instead, a cheap USB RGB module (USB_* below): 1280x720 colour
    and no depth (Frame.depth is None). Its wide lens's distortion, as left by a ChArUco calibration, defocus
    from the thin-lens formula around USB_FOCUS_M, shot and read noise, and MJPEG compression; the host then
    undistorts, so the frame is a pinhole image claiming the calibrated K. Exposure and white balance are
    locked unless USB_AUTO. Not modelled: rolling shutter and motion blur (frames are taken after the arm
    settles), the ISP's sharpening and denoising, vignetting. ideal=True gives a plain pinhole render of the same view.
    """

    def __init__(self, arm, size=(848, 480), ideal=False, seed=0, stereo=False, usb=False):
        assert not (usb and stereo)
        if usb:
            size = USB_RES
        super().__init__(arm, "wrist_cam", size, ideal, seed)
        self.K = _K(self.m.cam_fovy[self.cam], *size)
        self.fk = mujoco.MjData(self.m)  # for forward kinematics of the joint readings
        self.T_err = np.eye(4)  # fixed hand-eye calibration error, camera frame
        if not ideal:
            u = self.rng.normal(size=(2, 3))
            u /= np.linalg.norm(u, axis=1, keepdims=True)
            self.T_err[:3, :3] = cv2.Rodrigues(u[0] * np.radians(HAND_EYE_ERR[1]))[0]
            self.T_err[:3, 3] = u[1] * HAND_EYE_ERR[0]
        self.matcher = None
        if stereo:
            self.matcher = cv2.StereoSGBM_create(
                0, D405_DISPARITIES, D405_BLOCK, P1=8 * 3 * D405_BLOCK**2, P2=32 * 3 * D405_BLOCK**2, disp12MaxDiff=1,
                uniquenessRatio=10, speckleWindowSize=100, speckleRange=2, preFilterCap=63, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
        self.usb = usb
        if usb and ideal:  # a pinhole render covering what the real frame covers
            self.usb_fovy = np.degrees(2 * np.arctan(size[1] / 2 / USB_CAL_K[1, 1]))
            self.K = _K(self.usb_fovy, *size)
        if usb and not ideal:
            self.K = USB_CAL_K.copy()  # the frame is undistorted with the calibration, so it claims its K
            x, y = usb_lens_rays()
            Kr = _K(USB_RENDER_FOVY, *size)
            self.lens_map = (np.float32(Kr[0, 0] * x + Kr[0, 2]), np.float32(Kr[1, 1] * y + Kr[1, 2]))
            self.frame_map = cv2.initUndistortRectifyMap(USB_CAL_K, USB_CAL_DIST, None, USB_CAL_K, size, cv2.CV_32FC1)
            self.gain = 1.0  # locked exposure and white balance: the render's brightness and colour

    def believed_pose(self):
        """Camera pose from forward kinematics of the joint readings, plus the hand-eye error."""
        self.fk.qpos[self.arm.qadr] = self.arm.read_q()
        mujoco.mj_kinematics(self.m, self.fk)
        mujoco.mj_camlight(self.m, self.fk)
        return _cv_pose(self.fk, self.cam) @ self.T_err

    def capture(self):
        if self.usb:
            return Frame(self._usb_image(), None, self.K, self.believed_pose(), self.arm.d.time, "wrist")
        rgb, z = self._render(depth=self.ideal or self.matcher is None)
        if not self.ideal:
            rgb = self._noisy(rgb)
            z = self._noisy_depth(z) if self.matcher is None else self._stereo_depth(rgb)
        return Frame(rgb, z, self.K, self.believed_pose(), self.arm.d.time, "wrist")

    def _noisy(self, rgb):
        rgb = cv2.GaussianBlur(rgb, (0, 0), 0.7) + self.rng.normal(0, 2.0, rgb.shape)
        return np.clip(rgb, 0, 255).astype(np.uint8)

    def _usb_image(self):
        """usb=True: the module's raw frame (its lens, defocus, noise, MJPEG), then undistorted by the host."""
        if self.ideal:
            return self._render(fovy=self.usb_fovy, depth=False)[0]
        rgb, z = self._render(fovy=USB_RENDER_FOVY)
        # cubic: a bilinear warp would blur about 0.5 px on its own, a softness the real lens doesn't add
        lin = cv2.remap(np.float32(rgb / 255.0) ** 2.2, *self.lens_map, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        z = cv2.remap(z, *self.lens_map, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
        if USB_AUTO:  # metering the middle to mid grey, white balance to grey world (both converged by now)
            mean = lin[90:-90, 160:-160].reshape(-1, 3).mean(0)
            self.gain = np.clip(0.18 / (mean @ [0.07, 0.72, 0.21]), 0.25, 8) * np.clip(mean.mean() / mean, 0.8, 1.25)
        raw = usb_raw(lin, z, self.rng, self.gain)
        return cv2.remap(raw, *self.frame_map, cv2.INTER_LINEAR)

    def _noisy_depth(self, z):
        fb = self.K[0, 0] * D405_BASELINE_M  # disparity (px) = fb / z
        disp = np.where(z > 0, fb / np.maximum(z, 1e-6), 0).astype(np.float32)
        k = np.ones((3, 3), np.uint8)
        edge = cv2.dilate(disp, k) - cv2.erode(disp, k) > D405_EDGE_PX
        out = z + self.rng.normal(0, 1, z.shape) * z**2 * D405_SUBPIXEL_PX / fb
        lo, hi = D405_RANGE_M
        out[edge | (z < lo) | (z > hi) | (self.rng.random(z.shape) < D405_DROPOUT)] = 0
        return (np.round(out / 1e-4) * 1e-4).astype(np.float32)

    def _stereo_depth(self, left):
        """Depth (m) matched from the left image and a render of the right imager."""
        d, c = self.arm.d, self.cam
        pos = d.cam_xpos[c].copy()
        d.cam_xpos[c] += d.cam_xmat[c].reshape(3, 3)[:, 0] * D405_BASELINE_M
        try:
            right = self._noisy(self._render(depth=False)[0])
        finally:
            d.cam_xpos[c] = pos
        n = D405_DISPARITIES  # both padded on the left, so every column gets the full search
        disp = self.matcher.compute(*(cv2.copyMakeBorder(im, 0, 0, n, 0, cv2.BORDER_REPLICATE) for im in (left, right)))
        disp = disp[:, n:] / 16.0
        fb = self.K[0, 0] * D405_BASELINE_M
        x = np.arange(disp.shape[1])
        z = np.where((disp > 0) & (disp <= x), fb / np.maximum(disp, 1e-6), 0)  # a match off the right image: no depth
        lo, hi = D405_RANGE_M
        z[(z < lo) | (z > hi)] = 0
        return (np.round(z / 1e-4) * 1e-4).astype(np.float32)


class PhoneCamera(_SimCamera):
    """The iPhone on its tripod (scene_cam): 1280x720 RGB plus LiDAR depth.

    The LiDAR map is native 256x192 over the camera's full 4:3 frame, like ARKit's sceneDepth;
    the 16:9 video is the middle of that frame. Its noise model is an assumption, since no
    published close-range accuracy exists: each pixel averages its patch of the scene, the map
    is blurred by a 2 px Gaussian (about 7 mm at the device, so features under about 1 cm blur
    away), and 3 mm of Gaussian noise is added. Frame.depth is that map upsampled to the RGB.
    The tripod doesn't move, so the board is solved once, on the first capture, from a
    1920x1440 still: the 720p video puts the camera several mm off, because MuJoCo samples the
    board's texture poorly at that size. That capture raises vision.LookFailed if the arm hides
    the board (set T_base_cam = None to solve it again).
    """

    def __init__(self, arm, ideal=False, seed=0):
        w, h = PHONE_RES
        super().__init__(arm, "scene_cam", (w, w * 3 // 4), ideal, seed)
        fovy = self.m.cam_fovy[self.cam]
        self.K = _K(fovy, w, h)
        self.fovy_43 = np.degrees(2 * np.arctan(4 / 3 * np.tan(np.radians(fovy) / 2)))  # same focal length
        self.rows = slice((w * 3 // 4 - h) // 2, (w * 3 // 4 + h) // 2)  # the 16:9 frame inside the 4:3 one
        self.T_base_cam = None

    def capture(self):
        rgb, z = self._render(self.fovy_43)
        raw = self._lidar(z)
        rgb = self._noisy(rgb[self.rows])
        depth = z[self.rows] if self.ideal else self._upsample(raw)
        if self.T_base_cam is None:
            self.T_base_cam = self.true_pose() if self.ideal else self.pose_from_board(*self.still())
        return Frame(rgb, depth, self.K, self.T_base_cam, self.arm.d.time, "phone", raw)

    def still(self):
        """A photo of the whole 4:3 frame at ARKit's full 1920x1440, and its K."""
        r = self._renderer(STILL_RES)
        rgb = self._render(self.fovy_43, r)[0]
        r.close()
        return self._noisy(rgb), _K(self.fovy_43, *STILL_RES)

    def pose_from_board(self, rgb, K=None):
        """Camera pose in the arm frame from the desk board. K defaults to the video frame's;
        pose_from_board(*still()) is about 8x more accurate than a video frame."""
        return vision.board_pose(cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY), self.K if K is None else K)[0]

    def _noisy(self, rgb):
        return rgb if self.ideal else np.clip(rgb + self.rng.normal(0, 3.0, rgb.shape), 0, 255).astype(np.uint8)

    def _lidar(self, z):
        """Native map from the 4:3 render: patch averages, then blur and noise (none if ideal)."""
        valid = (z > 0).astype(np.float32)
        zs = cv2.resize(z * valid, LIDAR_RES, interpolation=cv2.INTER_AREA)
        vs = cv2.resize(valid, LIDAR_RES, interpolation=cv2.INTER_AREA)
        if not self.ideal:
            zs, vs = cv2.GaussianBlur(zs, (0, 0), LIDAR_BLUR_PX), cv2.GaussianBlur(vs, (0, 0), LIDAR_BLUR_PX)
        raw = np.where(vs > 0.5, zs / np.maximum(vs, 1e-6), 0)
        if not self.ideal:
            raw = np.where(raw > 0, raw + self.rng.normal(0, LIDAR_NOISE_M, raw.shape), 0)
        return raw.astype(np.float32)

    def _upsample(self, raw):
        """The map's 16:9 middle, bilinear up to the RGB frame; 0 next to missing pixels."""
        s = PHONE_RES[0] // LIDAR_RES[0]
        mid = raw[self.rows.start // s: self.rows.stop // s]
        up = cv2.resize(mid, PHONE_RES, interpolation=cv2.INTER_LINEAR)
        ok = cv2.resize((mid > 0).astype(np.float32), PHONE_RES, interpolation=cv2.INTER_LINEAR) > 0.999
        return np.where(ok, up, 0).astype(np.float32)
