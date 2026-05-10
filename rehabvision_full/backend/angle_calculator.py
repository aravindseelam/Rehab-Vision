"""
╔══════════════════════════════════════════════════════════════════════╗
║                  backend/angle_calculator.py                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  PURPOSE:                                                           ║
║    Compute joint angles from MediaPipe pose landmarks.              ║
║    All geometry lives here — no angle math anywhere else.           ║
║                                                                     ║
║  MATHEMATICS — 3-POINT ANGLE FORMULA                                ║
║  ─────────────────────────────────────────────────────────────────  ║
║  Given three points A, B (vertex), C we want the angle θ at B.     ║
║                                                                     ║
║  Classic approach: arccos( (BA·BC) / (|BA||BC|) )                  ║
║  Problem: arccos is numerically unstable near 0° and 180°.         ║
║                                                                     ║
║  Better approach: arctan2(|BA×BC|, BA·BC)                          ║
║                                                                     ║
║    BA = A – B        (vector from vertex to point A)               ║
║    BC = C – B        (vector from vertex to point C)               ║
║                                                                     ║
║    dot   = BA·BC   = BA.x*BC.x + BA.y*BC.y   → |BA||BC|cos(θ)     ║
║    cross = |BA×BC| = |BA.x*BC.y – BA.y*BC.x| → |BA||BC|sin(θ)    ║
║                                                                     ║
║    θ = atan2(cross, dot)  ← stable for all θ ∈ [0°, 180°]         ║
║                                                                     ║
║  WHY NOT USE z?                                                     ║
║    MediaPipe's z is a depth estimate, less reliable than x,y.      ║
║    2D angles are clinically sufficient for most ROM measurements.  ║
║    Future extension: pass use_3d=True to include z component.      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import math
from typing import Dict, List, Optional


class AngleCalculator:
    """
    Compute joint angles from MediaPipe landmark lists.

    Each landmark is a dict:
        { "x": float, "y": float, "z": float, "visibility": float }
    with x, y normalised to [0, 1].

    All returned angles are in degrees, rounded to 1 decimal place.
    A value of -1 means the angle could not be computed (low visibility).
    """

    # ─────────────────────────────────────────────────────────────────────────
    # Joint Triplets
    # ─────────────────────────────────────────────────────────────────────────
    # Format:  "joint_name": (idx_A, idx_B_vertex, idx_C)
    # Angle is measured AT idx_B.
    #
    # Landmark index reference (MediaPipe Pose 33-point model):
    #   11=L_shoulder  12=R_shoulder
    #   13=L_elbow     14=R_elbow
    #   15=L_wrist     16=R_wrist
    #   23=L_hip       24=R_hip
    #   25=L_knee      26=R_knee
    #   27=L_ankle     28=R_ankle
    #   29=L_heel      30=R_heel
    #   31=L_foot_idx  32=R_foot_idx
    # ─────────────────────────────────────────────────────────────────────────
    JOINT_TRIPLETS: Dict[str, tuple] = {
        # ── Shoulder (flexion / abduction share the same triplet)
        #    Measures: angle between upper arm and torso at shoulder joint
        "left_shoulder":   (13, 11, 23),   # L_elbow → L_shoulder → L_hip
        "right_shoulder":  (14, 12, 24),   # R_elbow → R_shoulder → R_hip

        # ── Elbow (flexion / extension)
        #    Measures: angle between upper arm and forearm
        "left_elbow":      (11, 13, 15),   # L_shoulder → L_elbow → L_wrist
        "right_elbow":     (12, 14, 16),   # R_shoulder → R_elbow → R_wrist

        # ── Hip (flexion / abduction)
        #    Measures: angle between torso and thigh
        "left_hip":        (11, 23, 25),   # L_shoulder → L_hip → L_knee
        "right_hip":       (12, 24, 26),   # R_shoulder → R_hip → R_knee

        # ── Knee (extension / flexion)
        #    Measures: angle between thigh and shank
        "left_knee":       (23, 25, 27),   # L_hip → L_knee → L_ankle
        "right_knee":      (24, 26, 28),   # R_hip → R_knee → R_ankle

        # ── Ankle (dorsiflexion / plantarflexion)
        #    Measures: angle between shank and foot
        "left_ankle":      (25, 27, 31),   # L_knee → L_ankle → L_foot_idx
        "right_ankle":     (26, 28, 32),   # R_knee → R_ankle → R_foot_idx

        # ── Trunk (lateral flexion / forward bending)
        #    Measures: angle at hip between shoulder and knee lines
        "trunk":           (12, 24, 26),   # R_shoulder → R_hip → R_knee

        # ── Neck (cervical ROM — forward/backward tilt)
        "neck":            (12, 0, 11),    # R_shoulder → Nose → L_shoulder
    }

    # ─────────────────────────────────────────────────────────────────────────
    # Primary joint for each exercise
    # ─────────────────────────────────────────────────────────────────────────
    # Maps exercise_id → which entry in JOINT_TRIPLETS to use as the
    # prominently-displayed angle on the dashboard.
    EXERCISE_PRIMARY: Dict[str, str] = {
        "shoulder_flex":  "right_shoulder",
        "shoulder_abd":   "right_shoulder",
        "elbow_flex":     "right_elbow",
        "knee_ext":       "right_knee",
        "hip_abd":        "right_hip",
        "hip_flex":       "right_hip",
        "ankle_df":       "right_ankle",
        "trunk_flex":     "trunk",
        "neck_flex":      "neck",
    }

    # Minimum visibility threshold — landmarks below this are ignored
    MIN_VISIBILITY = 0.30

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def compute_all_angles(self, landmarks: List[dict]) -> Dict[str, float]:
        """
        Compute angles at every joint defined in JOINT_TRIPLETS.

        Parameters
        ----------
        landmarks : list[dict]
            33-element list from MediaPipe, each dict has x, y, z, visibility.

        Returns
        -------
        dict[str, float]
            Map of joint_name → angle in degrees.
            Value is -1 if the joint could not be reliably measured.
        """
        if not landmarks or len(landmarks) < 29:
            return {}

        result = {}
        for joint_name, (ia, ib, ic) in self.JOINT_TRIPLETS.items():
            # Guard index bounds
            if ic >= len(landmarks):
                result[joint_name] = -1
                continue

            a = landmarks[ia]
            b = landmarks[ib]
            c = landmarks[ic]

            # Skip low-confidence landmarks
            vis = min(
                a.get("visibility", 1.0),
                b.get("visibility", 1.0),
                c.get("visibility", 1.0),
            )
            if vis < self.MIN_VISIBILITY:
                result[joint_name] = -1
                continue

            result[joint_name] = self._angle_at_b(a, b, c)

        return result

    def get_primary_angle(self, landmarks: List[dict], exercise_id: str) -> float:
        """
        Return the single most-relevant joint angle for the active exercise.

        Parameters
        ----------
        landmarks   : MediaPipe landmarks list (33 elements)
        exercise_id : Active exercise identifier, e.g. "knee_ext"

        Returns
        -------
        float — angle in degrees, or 0.0 if landmarks insufficient.
        """
        joint_name = self.EXERCISE_PRIMARY.get(exercise_id, "right_elbow")
        triplet    = self.JOINT_TRIPLETS.get(joint_name)

        if triplet is None or not landmarks or len(landmarks) < 29:
            return 0.0

        ia, ib, ic = triplet
        if ic >= len(landmarks):
            return 0.0

        a = landmarks[ia]
        b = landmarks[ib]
        c = landmarks[ic]

        vis = min(
            a.get("visibility", 1.0),
            b.get("visibility", 1.0),
            c.get("visibility", 1.0),
        )
        if vis < self.MIN_VISIBILITY:
            return 0.0

        return self._angle_at_b(a, b, c)

    # ─────────────────────────────────────────────────────────────────────────
    # Geometry helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _angle_at_b(a: dict, b: dict, c: dict) -> float:
        """
        Compute the interior angle θ at point B, formed by segments B→A and B→C.

        Uses arctan2(|cross|, dot) for numerical stability across the full
        range [0°, 180°].  Standard arccos fails near 0° and 180° due to
        floating-point precision.

        Parameters
        ----------
        a, b, c : dicts with at minimum "x" and "y" keys (normalised coords)

        Returns
        -------
        float — angle in degrees [0, 180], rounded to 1 decimal place.
        """
        # Build 2D vectors from vertex B
        bax = a["x"] - b["x"]
        bay = a["y"] - b["y"]
        bcx = c["x"] - b["x"]
        bcy = c["y"] - b["y"]

        # Dot product  BA · BC  =  |BA||BC| cos θ
        dot = bax * bcx + bay * bcy

        # 2D cross-product magnitude  |BA × BC|  =  |BA||BC| sin θ
        cross = abs(bax * bcy - bay * bcx)

        # arctan2 is defined for all (cross, dot) and gives θ ∈ [0, π]
        theta_rad = math.atan2(cross, dot)
        return round(math.degrees(theta_rad), 1)

    @staticmethod
    def rom_percent(angle: float, target_min: float, target_max: float) -> int:
        """
        Map a joint angle to a percentage of the target ROM.

        Example
        -------
        rom_percent(90, 0, 180)   → 50
        rom_percent(145, 20, 145) → 100
        rom_percent(10, 20, 145)  → 0   (clamped — below minimum)

        Returns
        -------
        int in [0, 100]
        """
        span = max(target_max - target_min, 1)
        pct  = (angle - target_min) / span * 100
        return max(0, min(100, int(pct)))

    @staticmethod
    def ema_smooth(prev: float, current: float, alpha: float = 0.7) -> float:
        """
        Exponential Moving Average for temporal angle smoothing.

        alpha = 0.7  →  responsive (weights current frame at 70%)
        alpha = 0.3  →  smooth    (weights history at 70%, lags slightly)

        Use in the processing loop to reduce per-frame jitter:
            smoothed = ema_smooth(smoothed, raw_angle)
        """
        return alpha * current + (1.0 - alpha) * prev
