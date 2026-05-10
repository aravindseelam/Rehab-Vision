"""
╔══════════════════════════════════════════════════════════════════════╗
║                   tests/test_core.py                                ║
╠══════════════════════════════════════════════════════════════════════╣
║  Unit tests for the two pure-Python modules that contain all        ║
║  the calculation logic.                                             ║
║                                                                     ║
║  Run:  python -m pytest tests/ -v                                   ║
║  Or:   python tests/test_core.py                                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import math
import unittest

from angle_calculator import AngleCalculator
from session_tracker  import RepStateMachine, SessionTracker
from exercise_manager import ExerciseManager


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def lm(x, y, vis=1.0):
    """Shorthand to create a MediaPipe-style landmark dict."""
    return {"x": x, "y": y, "z": 0.0, "visibility": vis}


def make_landmarks_33(overrides: dict = None):
    """
    Build a 33-element landmark list filled with a neutral standing pose.
    overrides: dict of {index: lm(...)} to replace specific landmarks.
    """
    # Neutral standing pose (all on x=0.5 spine with anatomical spacing)
    defaults = {
        0:  lm(0.50, 0.08),   # nose
        11: lm(0.36, 0.22),   # left shoulder
        12: lm(0.64, 0.22),   # right shoulder
        13: lm(0.30, 0.38),   # left elbow
        14: lm(0.70, 0.38),   # right elbow
        15: lm(0.28, 0.52),   # left wrist
        16: lm(0.72, 0.52),   # right wrist
        23: lm(0.42, 0.50),   # left hip
        24: lm(0.58, 0.50),   # right hip
        25: lm(0.40, 0.68),   # left knee
        26: lm(0.60, 0.68),   # right knee
        27: lm(0.39, 0.85),   # left ankle
        28: lm(0.61, 0.85),   # right ankle
        29: lm(0.39, 0.88),   # left heel
        30: lm(0.61, 0.88),   # right heel
        31: lm(0.37, 0.90),   # left foot index
        32: lm(0.63, 0.90),   # right foot index
    }
    lms = [lm(0.5, 0.5) for _ in range(33)]  # fill unused
    for idx, pt in defaults.items():
        lms[idx] = pt
    if overrides:
        for idx, pt in overrides.items():
            lms[idx] = pt
    return lms


# ─────────────────────────────────────────────────────────────────────────────
# AngleCalculator Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAngleCalculator(unittest.TestCase):

    def setUp(self):
        self.calc = AngleCalculator()

    # ── _angle_at_b ───────────────────────────────────────────────────────────

    def test_right_angle(self):
        """Three points forming a perfect 90° angle."""
        a = lm(0.0, 0.0)
        b = lm(1.0, 0.0)    # vertex
        c = lm(1.0, 1.0)
        self.assertAlmostEqual(
            self.calc._angle_at_b(a, b, c), 90.0, delta=0.5
        )

    def test_straight_line(self):
        """Three collinear points → 180°."""
        a = lm(0.0, 0.5)
        b = lm(0.5, 0.5)    # vertex
        c = lm(1.0, 0.5)
        self.assertAlmostEqual(
            self.calc._angle_at_b(a, b, c), 180.0, delta=0.5
        )

    def test_zero_angle(self):
        """Two vectors pointing same direction → 0°."""
        a = lm(0.0, 0.5)
        b = lm(0.5, 0.5)    # vertex
        c = lm(0.2, 0.5)    # same direction as A
        angle = self.calc._angle_at_b(a, b, c)
        self.assertAlmostEqual(angle, 0.0, delta=1.0)

    def test_45_degree(self):
        """45° angle."""
        a = lm(0.0, 0.0)
        b = lm(0.0, 1.0)    # vertex
        c = lm(1.0, 1.0)
        self.assertAlmostEqual(
            self.calc._angle_at_b(a, b, c), 45.0, delta=1.0
        )

    # ── compute_all_angles ────────────────────────────────────────────────────

    def test_compute_all_angles_returns_dict(self):
        lms = make_landmarks_33()
        angles = self.calc.compute_all_angles(lms)
        self.assertIsInstance(angles, dict)
        self.assertIn("right_elbow", angles)
        self.assertIn("right_knee",  angles)

    def test_all_angles_in_valid_range(self):
        """All computed angles must be -1 (invalid) or in [0, 180]."""
        lms = make_landmarks_33()
        for name, val in self.calc.compute_all_angles(lms).items():
            self.assertTrue(
                val == -1 or 0 <= val <= 180,
                f"Angle {name}={val} out of range"
            )

    def test_empty_landmarks_returns_empty(self):
        self.assertEqual(self.calc.compute_all_angles([]), {})

    def test_low_visibility_returns_minus_one(self):
        """Landmarks with visibility < 0.3 should give -1."""
        lms = make_landmarks_33()
        # Set right elbow landmarks to low visibility
        for idx in [12, 14, 16]:
            lms[idx]["visibility"] = 0.1
        angles = self.calc.compute_all_angles(lms)
        self.assertEqual(angles.get("right_elbow"), -1)

    # ── get_primary_angle ─────────────────────────────────────────────────────

    def test_primary_angle_shoulder_flex(self):
        lms = make_landmarks_33()
        angle = self.calc.get_primary_angle(lms, "shoulder_flex")
        self.assertGreater(angle, 0)
        self.assertLessEqual(angle, 180)

    def test_primary_angle_unknown_exercise(self):
        """Unknown exercise should default gracefully (not crash)."""
        lms   = make_landmarks_33()
        angle = self.calc.get_primary_angle(lms, "nonexistent_exercise")
        self.assertGreaterEqual(angle, 0)

    # ── rom_percent ───────────────────────────────────────────────────────────

    def test_rom_percent_midpoint(self):
        self.assertEqual(self.calc.rom_percent(90, 0, 180), 50)

    def test_rom_percent_at_minimum(self):
        self.assertEqual(self.calc.rom_percent(20, 20, 145), 0)

    def test_rom_percent_at_maximum(self):
        self.assertEqual(self.calc.rom_percent(145, 20, 145), 100)

    def test_rom_percent_clamped(self):
        self.assertEqual(self.calc.rom_percent(200, 0, 180), 100)
        self.assertEqual(self.calc.rom_percent(-10, 0, 180),   0)

    # ── ema_smooth ────────────────────────────────────────────────────────────

    def test_ema_smooth_alpha_1_returns_current(self):
        """alpha=1.0 should return current exactly."""
        self.assertAlmostEqual(self.calc.ema_smooth(50, 90, alpha=1.0), 90.0)

    def test_ema_smooth_alpha_0_returns_previous(self):
        """alpha=0.0 should return previous exactly."""
        self.assertAlmostEqual(self.calc.ema_smooth(50, 90, alpha=0.0), 50.0)

    def test_ema_smooth_default(self):
        """Default alpha=0.7: result should be between prev and current."""
        result = self.calc.ema_smooth(50, 100, alpha=0.7)
        self.assertGreater(result, 50)
        self.assertLess(result, 100)


# ─────────────────────────────────────────────────────────────────────────────
# RepStateMachine Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRepStateMachine(unittest.TestCase):

    def _ex(self, tmin=20, tmax=145):
        return {"target_min": tmin, "target_max": tmax}

    def test_no_rep_below_threshold(self):
        """Angle that never reaches UP threshold should not count a rep."""
        sm = RepStateMachine()
        ex = self._ex()
        is_rep_any = any(sm.update(30, ex)[1] for _ in range(10))
        self.assertFalse(is_rep_any)

    def test_one_rep_counts(self):
        """Simulate one full up-and-back cycle."""
        sm = RepStateMachine()
        ex = self._ex(20, 145)
        # span=125, up_thresh=20+81=101, dn_thresh=20+44=64

        reps = 0
        angles = [30, 50, 70, 90, 110, 130, 145,   # ascending
                  130, 110, 90, 70, 50, 30, 20]    # descending
        for a in angles:
            _, is_rep = sm.update(a, ex)
            if is_rep:
                reps += 1

        self.assertEqual(reps, 1)

    def test_two_reps(self):
        """Two complete cycles should count two reps."""
        sm = RepStateMachine()
        ex = self._ex(20, 145)

        reps   = 0
        cycle  = [30, 110, 145, 110, 30]   # one rep
        for a in cycle * 2:
            _, is_rep = sm.update(a, ex)
            if is_rep:
                reps += 1

        self.assertEqual(reps, 2)

    def test_noisy_threshold_no_double_count(self):
        """Jitter around threshold should NOT produce extra reps."""
        sm = RepStateMachine()
        ex = self._ex(20, 145)

        reps = 0
        # Rise above UP, wobble a bit, then descend
        angles = [20, 60, 100, 110, 108, 112, 110,   # noisy peak
                  90, 70, 50, 30, 20]
        for a in angles:
            _, is_rep = sm.update(a, ex)
            if is_rep:
                reps += 1

        self.assertEqual(reps, 1)

    def test_phase_labels(self):
        """Phase should be 'up' while ascending, 'idle' otherwise."""
        sm = RepStateMachine()
        ex = self._ex(20, 145)

        phase, _ = sm.update(20, ex)
        self.assertEqual(phase, "idle")

        phase, _ = sm.update(110, ex)
        self.assertEqual(phase, "up")

        phase, _ = sm.update(20, ex)
        self.assertEqual(phase, "idle")

    def test_reset_clears_state(self):
        sm  = RepStateMachine()
        ex  = self._ex()
        sm.update(110, ex)   # ascending
        sm.reset()
        self.assertEqual(sm.current_state, "idle")


# ─────────────────────────────────────────────────────────────────────────────
# SessionTracker Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionTracker(unittest.TestCase):

    def _ex(self):
        return {"target_min": 20, "target_max": 145}

    def test_angle_history_appended(self):
        t = SessionTracker()
        t.set_active(True)
        ex = self._ex()
        for a in [30, 60, 90, 120]:
            t.update(a, ex)
        self.assertEqual(t.get_angle_history(), [30, 60, 90, 120])

    def test_history_capped(self):
        """History should not grow beyond MAX_HISTORY entries."""
        t  = SessionTracker()
        t.set_active(True)
        ex = self._ex()
        for _ in range(SessionTracker.MAX_HISTORY + 100):
            t.update(90, ex)
        self.assertLessEqual(len(t.get_angle_history()), SessionTracker.MAX_HISTORY)

    def test_rep_not_counted_when_inactive(self):
        t  = SessionTracker()
        ex = self._ex()
        # Do not call set_active(True)
        for a in [20, 110, 145, 110, 20]:
            _, is_rep = t.update(a, ex)
            self.assertFalse(is_rep, "Should not count rep when inactive")

    def test_rep_counted_when_active(self):
        t  = SessionTracker()
        t.set_active(True)
        ex = self._ex()
        reps = 0
        for a in [20, 110, 145, 110, 20]:
            _, is_rep = t.update(a, ex)
            if is_rep:
                reps += 1
        self.assertEqual(reps, 1)

    def test_log_milestones(self):
        t = SessionTracker()
        t.log_milestone(5, 130.0)
        log = t.get_log()
        self.assertEqual(len(log["milestones"]), 1)
        self.assertEqual(log["milestones"][0]["rep"], 5)

    def test_summary_stats(self):
        t  = SessionTracker()
        t.set_active(True)
        ex = self._ex()
        for a in [30, 60, 90, 120, 140]:
            t.update(a, ex)
        s = t.get_log()["summary"]
        self.assertEqual(s["max_angle"], 140.0)
        self.assertEqual(s["min_angle"], 30.0)
        self.assertEqual(s["rom_achieved"], 110.0)

    def test_reset_clears_everything(self):
        t  = SessionTracker()
        t.set_active(True)
        ex = self._ex()
        for a in [30, 110, 20]:
            t.update(a, ex)
        t.log_milestone(1, 110.0)
        t.reset()
        log = t.get_log()
        self.assertEqual(log["milestones"], [])
        self.assertEqual(log["angle_history"], [])
        self.assertEqual(log["summary"]["total_reps"], 0)

    def test_rom_percent(self):
        t  = SessionTracker()
        t.set_active(True)
        ex = self._ex()
        for a in [20, 82, 145]:   # full range
            t.update(a, ex)
        pct = t.get_rom_percent(20, 145)
        self.assertEqual(pct, 100)


# ─────────────────────────────────────────────────────────────────────────────
# ExerciseManager Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExerciseManager(unittest.TestCase):

    def setUp(self):
        self.mgr = ExerciseManager()

    def test_get_all_returns_list(self):
        exs = self.mgr.get_all_exercises()
        self.assertIsInstance(exs, list)
        self.assertGreater(len(exs), 0)

    def test_set_exercise_returns_dict(self):
        ex = self.mgr.set_exercise("knee_ext")
        self.assertEqual(ex["id"], "knee_ext")

    def test_set_invalid_exercise_raises(self):
        with self.assertRaises(KeyError):
            self.mgr.set_exercise("does_not_exist")

    def test_feedback_in_range(self):
        ex  = self.mgr.get_exercise("shoulder_flex")
        msg = self.mgr.get_feedback(100, ex)
        self.assertIn("✓", msg)

    def test_feedback_below_range(self):
        ex  = self.mgr.get_exercise("shoulder_flex")   # min=60
        msg = self.mgr.get_feedback(40, ex)
        self.assertIn("↑", msg)

    def test_feedback_above_range(self):
        ex  = self.mgr.get_exercise("shoulder_flex")   # max=170
        msg = self.mgr.get_feedback(175, ex)
        self.assertIn("↓", msg)

    def test_feedback_zero_angle(self):
        ex  = self.mgr.get_exercise("shoulder_flex")
        msg = self.mgr.get_feedback(0, ex)
        self.assertIn("Waiting", msg)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
