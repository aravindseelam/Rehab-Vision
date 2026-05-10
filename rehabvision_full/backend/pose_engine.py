"""
╔══════════════════════════════════════════════════════════════════════╗
║                    backend/pose_engine.py                           ║
╠══════════════════════════════════════════════════════════════════════╣
║  PURPOSE:                                                           ║
║    Wraps OpenCV camera I/O and MediaPipe Pose into one clean class. ║
║    This is the ONLY file that touches the physical camera or the    ║
║    MediaPipe library — all other modules work on plain Python dicts.║
║                                                                     ║
║  MEDIAPIPE POSE — 33 LANDMARKS:                                     ║
║    Each landmark: { x, y, z, visibility }                           ║
║    x, y ∈ [0,1]  (normalised, origin = top-left of frame)          ║
║    z    ∈ ~[–0.5, 0.5]  (depth relative to hip, not used here)     ║
║    visibility ∈ [0,1]  (confidence this landmark is visible)       ║
║                                                                     ║
║  KEY LANDMARK INDICES:                                              ║
║     0  nose           1  left eye (inner)                           ║
║    11  left shoulder  12  right shoulder                            ║
║    13  left elbow     14  right elbow                               ║
║    15  left wrist     16  right wrist                               ║
║    23  left hip       24  right hip                                 ║
║    25  left knee      26  right knee                                ║
║    27  left ankle     28  right ankle                               ║
║    29  left heel      30  right heel                                ║
║    31  left foot idx  32  right foot idx                            ║
║                                                                     ║
║  DEMO MODE:                                                         ║
║    If no camera is found, PoseEngine generates a synthetic animated ║
║    skeleton so the UI/analytics still work without hardware.        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import cv2
import math
import time
import numpy as np

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    print("[PoseEngine] WARNING: mediapipe not installed — demo mode only")


# ─────────────────────────────────────────────────────────────────────────────
class PoseEngine:
    """
    Manages webcam capture and runs MediaPipe Pose on each frame.

    Public interface
    ────────────────
    process_next_frame() → (landmarks_raw, landmarks_norm) | None
        Read one frame, detect pose, store annotated JPEG.
        Returns None if no frame or no person detected.

    get_annotated_frame() → bytes | None
        Return latest JPEG bytes (for MJPEG stream).

    is_camera_open() → bool
    """

    # ── MediaPipe landmark indices as named constants ─────────────────────────
    NOSE           = 0
    L_SHOULDER     = 11;  R_SHOULDER = 12
    L_ELBOW        = 13;  R_ELBOW    = 14
    L_WRIST        = 15;  R_WRIST    = 16
    L_HIP          = 23;  R_HIP      = 24
    L_KNEE         = 25;  R_KNEE     = 26
    L_ANKLE        = 27;  R_ANKLE    = 28
    L_HEEL         = 29;  R_HEEL     = 30
    L_FOOT_IDX     = 31;  R_FOOT_IDX = 32

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self._cap:   cv2.VideoCapture | None = None
        self._jpeg:  bytes | None            = None   # Latest annotated frame
        self._demo_t: float                  = 0.0    # Demo animation clock

        # ── Initialise MediaPipe ──────────────────────────────────────────────
        if MEDIAPIPE_AVAILABLE:
            self._mp_pose   = mp.solutions.pose
            self._mp_draw   = mp.solutions.drawing_utils
            self._mp_styles = mp.solutions.drawing_styles

            # model_complexity  0=fast/mobile  1=balanced  2=accurate
            self._pose = self._mp_pose.Pose(
                static_image_mode        = False,
                model_complexity         = 1,
                smooth_landmarks         = True,
                enable_segmentation      = False,
                min_detection_confidence = 0.5,
                min_tracking_confidence  = 0.5,
            )

            # Custom overlay colours  (BGR for OpenCV)
            self._lm_spec   = self._mp_draw.DrawingSpec(
                color=(0, 245, 200), thickness=3, circle_radius=4)
            self._conn_spec = self._mp_draw.DrawingSpec(
                color=(240, 200, 76), thickness=2)
        else:
            self._pose = None

        self._open_camera()

    # ─────────────────────────────────────────────────────────────────────────
    # Camera management
    # ─────────────────────────────────────────────────────────────────────────

    def _open_camera(self):
        """Try to open the webcam; silently fall back to demo mode."""
        self._cap = cv2.VideoCapture(self.camera_index)
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FPS,           30)
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"[PoseEngine] Camera {self.camera_index} opened  {w}×{h} ✓")
        else:
            print(f"[PoseEngine] Camera {self.camera_index} unavailable — DEMO MODE")
            self._cap = None

    def is_camera_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    # ─────────────────────────────────────────────────────────────────────────
    # Main processing
    # ─────────────────────────────────────────────────────────────────────────

    def process_next_frame(self):
        """
        Capture one frame, run MediaPipe Pose, encode annotated JPEG.

        Returns
        ───────
        (landmarks_raw, landmarks_norm) on success
          landmarks_raw  — pixel coords  [{x_px, y_px, z, visibility}, ×33]
          landmarks_norm — normalised     [{x, y, z, visibility},       ×33]
        None — if no frame available or no person detected
        """
        if not self.is_camera_open() or not MEDIAPIPE_AVAILABLE:
            return self._demo_frame()

        ret, frame = self._cap.read()
        if not ret:
            return self._demo_frame()

        frame = cv2.flip(frame, 1)          # Mirror for intuitive interaction
        h, w  = frame.shape[:2]

        # MediaPipe requires RGB; mark non-writable for performance
        rgb               = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results           = self._pose.process(rgb)
        rgb.flags.writeable = True

        if results.pose_landmarks is None:
            self._draw_hud(frame, 0)
            self._encode_jpeg(frame)
            return None

        # ── Extract landmarks ─────────────────────────────────────────────────
        landmarks_norm = []
        landmarks_raw  = []
        for lm in results.pose_landmarks.landmark:
            landmarks_norm.append({
                "x": lm.x, "y": lm.y, "z": lm.z,
                "visibility": lm.visibility,
            })
            landmarks_raw.append({
                "x_px": int(lm.x * w),
                "y_px": int(lm.y * h),
                "z":    lm.z,
                "visibility": lm.visibility,
            })

        # ── Draw skeleton overlay ─────────────────────────────────────────────
        self._mp_draw.draw_landmarks(
            frame,
            results.pose_landmarks,
            self._mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec  = self._lm_spec,
            connection_drawing_spec= self._conn_spec,
        )
        self._draw_hud(frame, len(landmarks_norm))
        self._encode_jpeg(frame)
        return landmarks_raw, landmarks_norm

    # ─────────────────────────────────────────────────────────────────────────
    # Frame helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_hud(self, frame, joint_count: int):
        """Minimal HUD overlay — top bar with joint count and branding."""
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 34), (8, 11, 20), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        cv2.putText(frame,
                    f"JOINTS: {joint_count}",
                    (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 245, 200), 1, cv2.LINE_AA)
        cv2.putText(frame, "REHABVISION",
                    (w - 120, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (240, 200, 76), 1, cv2.LINE_AA)

    def _encode_jpeg(self, frame):
        """JPEG-encode frame and cache for MJPEG stream."""
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            self._jpeg = buf.tobytes()

    def get_annotated_frame(self) -> bytes | None:
        """Return latest annotated JPEG bytes (called by /video_feed route)."""
        return self._jpeg

    # ─────────────────────────────────────────────────────────────────────────
    # Demo mode  (no camera or MediaPipe)
    # ─────────────────────────────────────────────────────────────────────────

    def _demo_frame(self):
        """
        Generate a synthetic animated stick-figure frame.

        Simulates shoulder-flexion motion so every downstream module
        (angle calculation, rep counting, feedback) still works.
        The joints are placed at anatomically plausible positions.
        """
        W, H = 640, 480
        frame = np.full((H, W, 3), (8, 11, 20), dtype=np.uint8)

        self._demo_t += 0.035
        cycle = (math.sin(self._demo_t) + 1) / 2   # 0 → 1 smooth oscillation

        def px(nx, ny):
            return int(nx * W), int(ny * H)

        # Joint positions (normalised x,y) — shoulder flexion animation
        ang = 0.15 + cycle * 1.5
        joints_norm = {
            "nose":    (0.50, 0.07), "neck":   (0.50, 0.17),
            "sh_l":    (0.35, 0.21), "sh_r":   (0.65, 0.21),
            "el_l":    (0.29, 0.37),
            "el_r":    (0.65 + math.sin(ang)*0.14, 0.21 + math.cos(ang)*0.14),
            "wr_l":    (0.27, 0.52),
            "wr_r":    (0.65 + math.sin(ang)*0.27, 0.21 + math.cos(ang)*0.27),
            "hip_l":   (0.42, 0.49), "hip_r":  (0.58, 0.49),
            "knee_l":  (0.40, 0.67), "knee_r": (0.60, 0.67),
            "ank_l":   (0.39, 0.84), "ank_r":  (0.61, 0.84),
        }
        connections = [
            ("nose","neck"), ("neck","sh_l"), ("neck","sh_r"),
            ("sh_l","el_l"), ("el_l","wr_l"),
            ("sh_r","el_r"), ("el_r","wr_r"),
            ("sh_l","hip_l"), ("sh_r","hip_r"), ("hip_l","hip_r"),
            ("hip_l","knee_l"), ("knee_l","ank_l"),
            ("hip_r","knee_r"), ("knee_r","ank_r"),
        ]

        # Draw connections
        for a, b in connections:
            cv2.line(frame, px(*joints_norm[a]), px(*joints_norm[b]),
                     (240, 200, 76), 2, cv2.LINE_AA)

        # Draw joints
        key_joints = {"sh_r", "el_r", "wr_r", "knee_r", "hip_r"}
        for name, pos in joints_norm.items():
            colour = (133, 37, 247) if name in key_joints else (200, 245, 0)
            radius = 6 if name in key_joints else 4
            cv2.circle(frame, px(*pos), radius, colour, -1, cv2.LINE_AA)

        # Demo label
        cv2.rectangle(frame, (0, H - 28), (W, H), (8, 11, 20), -1)
        cv2.putText(frame, "DEMO MODE — connect a camera for live detection",
                    (10, H - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (200, 200, 100), 1, cv2.LINE_AA)

        self._draw_hud(frame, len(joints_norm))
        self._encode_jpeg(frame)

        # Build fake 33-landmark list (fill unused slots with centre point)
        centre = {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0}
        lm = [dict(centre) for _ in range(33)]

        # Map our named joints → MediaPipe indices
        idx_map = {
            "nose":   0,  "sh_l":  11, "sh_r": 12,
            "el_l":  13,  "el_r":  14, "wr_l": 15, "wr_r": 16,
            "hip_l": 23,  "hip_r": 24,
            "knee_l":25,  "knee_r":26,
            "ank_l": 27,  "ank_r": 28,
        }
        for name, idx in idx_map.items():
            nx, ny = joints_norm[name]
            lm[idx] = {"x": nx, "y": ny, "z": 0.0, "visibility": 1.0}

        return lm, lm   # raw == norm in demo mode (no pixel coords needed)

    # ─────────────────────────────────────────────────────────────────────────

    def __del__(self):
        if self._cap and self._cap.isOpened():
            self._cap.release()
