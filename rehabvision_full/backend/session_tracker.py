"""
╔══════════════════════════════════════════════════════════════════════╗
║                  backend/session_tracker.py                         ║
╠══════════════════════════════════════════════════════════════════════╣
║  PURPOSE:                                                           ║
║    - Count exercise repetitions from a joint angle time-series      ║
║    - Maintain a session log (milestones, angle history, statistics) ║
║                                                                     ║
║  REP DETECTION ALGORITHM — HYSTERESIS STATE MACHINE                 ║
║  ─────────────────────────────────────────────────────────────────  ║
║  Problem: A naive threshold (count every crossing of target_min)   ║
║           triggers phantom reps when the angle wobbles near the     ║
║           threshold value.                                          ║
║                                                                     ║
║  Solution: Two thresholds with a gap ("hysteresis band"):           ║
║                                                                     ║
║    UP_THRESH   = target_min + 65% * span                           ║
║    DOWN_THRESH = target_min + 35% * span                           ║
║                                                                     ║
║  States:                                                            ║
║    idle       → angle below DOWN_THRESH, no rep in progress        ║
║    ascending  → angle rose above UP_THRESH, tracking peak          ║
║                                                                     ║
║  Rep counted when:                                                  ║
║    state == ascending  AND  angle drops below DOWN_THRESH          ║
║                                                                     ║
║  Angle time-series example for one rep:                             ║
║                                                                     ║
║    angle:   _____/‾‾‾‾‾‾‾‾\______                                  ║
║                  ↑UP       ↓DN                                      ║
║    state:   idle  ascending  idle←rep!                             ║
║                                                                     ║
║  The gap between UP and DOWN thresholds prevents double-counting.  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import time
from typing import List, Dict, Tuple, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Rep State Machine
# ─────────────────────────────────────────────────────────────────────────────

class RepStateMachine:
    """
    Single-joint, single-exercise rep counter.

    Feed angle values one at a time via update().
    A rep is counted when a full up-and-back cycle completes.

    Parameters
    ----------
    up_pct  : float  — UP threshold as fraction of target span (default 0.65)
    dn_pct  : float  — DOWN threshold as fraction of target span (default 0.35)

    The gap (up_pct – dn_pct) = 0.30 is the hysteresis band.
    Wider gap → fewer false positives, but requires larger ROM to trigger.
    Narrower gap → more responsive, but noisier for shaky movements.
    """

    def __init__(self, up_pct: float = 0.65, dn_pct: float = 0.35):
        assert up_pct > dn_pct, "up_pct must be greater than dn_pct"
        self.up_pct = up_pct
        self.dn_pct = dn_pct
        self._state = "idle"    # "idle" | "ascending"
        self._peak  = 0.0       # Highest angle seen in current ascending phase

    def update(self, angle: float, exercise: dict) -> Tuple[str, bool]:
        """
        Process one angle sample.

        Parameters
        ----------
        angle    : Current joint angle in degrees.
        exercise : Exercise dict (needs target_min, target_max).

        Returns
        -------
        (phase_label, is_rep)
        phase_label : "idle" | "up" | "down"
        is_rep      : True on the exact frame the rep is completed.
        """
        t_min = exercise["target_min"]
        t_max = exercise["target_max"]
        span  = max(t_max - t_min, 1)

        up_thresh = t_min + self.up_pct * span
        dn_thresh = t_min + self.dn_pct * span

        is_rep = False

        if self._state == "idle":
            # Waiting for angle to rise above upper threshold
            if angle >= up_thresh:
                self._state = "ascending"
                self._peak  = angle

        elif self._state == "ascending":
            # Track maximum
            if angle > self._peak:
                self._peak = angle

            # Rep completes when angle falls back below lower threshold
            if angle <= dn_thresh:
                self._state = "idle"
                is_rep      = True

        # Map internal state to UI phase label
        phase_map = {"idle": "idle", "ascending": "up"}
        phase     = phase_map.get(self._state, "idle")

        return phase, is_rep

    def reset(self):
        """Reset to initial state."""
        self._state = "idle"
        self._peak  = 0.0

    @property
    def current_state(self) -> str:
        return self._state


# ─────────────────────────────────────────────────────────────────────────────
# Session Tracker
# ─────────────────────────────────────────────────────────────────────────────

class SessionTracker:
    """
    Tracks the complete physiotherapy session:
      - Delegates rep counting to RepStateMachine
      - Maintains rolling angle history (last 60 s at 30 fps)
      - Records milestone events
      - Computes summary statistics on demand

    Usage
    ─────
        tracker = SessionTracker()
        tracker.set_active(True)

        # In your processing loop:
        phase, is_rep = tracker.update(angle, exercise)
        if is_rep:
            tracker.log_milestone(total_reps, angle)

        log = tracker.get_log()   # For the progress tab
        tracker.reset()           # Start fresh
    """

    # Keep angle history for at most this many samples
    # 30fps × 60s = 1800 samples ≈ last 60 seconds
    MAX_HISTORY = 1800

    def __init__(self):
        self._state_machine     = RepStateMachine()
        self._is_active         = False
        self._start_time        = time.time()
        self._active_start      = None     # When current session began
        self._angle_history:    List[float] = []
        self._milestones:       List[dict]  = []
        self._rep_timestamps:   List[float] = []

    # ─────────────────────────────────────────────────────────────────────────

    def set_active(self, active: bool):
        """Enable or disable rep counting."""
        self._is_active = active
        if active and self._active_start is None:
            self._active_start = time.time()

    # ─────────────────────────────────────────────────────────────────────────

    def update(self, angle: float, exercise: dict) -> Tuple[str, bool]:
        """
        Process one angle sample from the processing loop.

        Always records the angle into history (for chart display).
        Only counts reps when is_active == True.

        Parameters
        ----------
        angle    : Latest joint angle in degrees.
        exercise : Active exercise protocol dict.

        Returns
        -------
        (phase_label, is_rep)  — same semantics as RepStateMachine.update()
        """
        # Always record history for chart/analytics
        self._angle_history.append(angle)
        if len(self._angle_history) > self.MAX_HISTORY:
            self._angle_history.pop(0)

        if not self._is_active:
            return "idle", False

        phase, is_rep = self._state_machine.update(angle, exercise)

        if is_rep:
            self._rep_timestamps.append(time.time())

        return phase, is_rep

    # ─────────────────────────────────────────────────────────────────────────

    def log_milestone(self, rep_count: int, angle: float):
        """
        Record a milestone event (called by app.py when a rep completes).

        Milestones power the "Progress" tab table.
        """
        elapsed = round(time.time() - (self._active_start or self._start_time), 1)
        self._milestones.append({
            "rep":       rep_count,
            "angle":     round(angle, 1),
            "time":      time.strftime("%H:%M:%S"),
            "elapsed_s": elapsed,
        })

    # ─────────────────────────────────────────────────────────────────────────

    def get_log(self) -> dict:
        """
        Return the complete session log.

        Returns
        -------
        {
          "milestones":     list of {rep, angle, time, elapsed_s},
          "angle_history":  list of floats (last 60 s),
          "summary": {
            "total_reps":   int,
            "session_time": float (seconds),
            "max_angle":    float,
            "min_angle":    float,
            "rom_achieved": float (max – min),
            "avg_rep_time": float (seconds per rep, or 0),
          }
        }
        """
        h       = self._angle_history
        elapsed = round(
            time.time() - (self._active_start or self._start_time), 1
        )

        max_angle = round(max(h), 1) if h else 0.0
        min_angle = round(min(h), 1) if h else 0.0
        rom       = round(max_angle - min_angle, 1)

        # Average time between consecutive reps
        avg_rep_time = 0.0
        ts = self._rep_timestamps
        if len(ts) >= 2:
            gaps         = [ts[i+1] - ts[i] for i in range(len(ts) - 1)]
            avg_rep_time = round(sum(gaps) / len(gaps), 2)

        return {
            "milestones":    self._milestones,
            "angle_history": list(h[-180:]),   # Last 6 seconds at 30fps
            "summary": {
                "total_reps":   len(ts),
                "session_time": elapsed,
                "max_angle":    max_angle,
                "min_angle":    min_angle,
                "rom_achieved": rom,
                "avg_rep_time": avg_rep_time,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────

    def get_rom_percent(self, target_min: float, target_max: float) -> int:
        """
        Compute the percentage of target ROM the patient has achieved.

            rom_pct = achieved_rom / target_rom × 100  (capped at 100)

        Used by the "ROM Coverage" metric card on the dashboard.
        """
        h = self._angle_history
        if not h:
            return 0
        achieved = max(h) - min(h)
        target   = max(target_max - target_min, 1)
        return min(100, int(achieved / target * 100))

    def get_angle_history(self) -> List[float]:
        """Return a copy of the angle time-series."""
        return list(self._angle_history)

    # ─────────────────────────────────────────────────────────────────────────

    def reset(self):
        """
        Clear all session data and restart clocks.
        Called by /api/session/reset and when switching exercises.
        """
        self._state_machine.reset()
        self._is_active      = False
        self._start_time     = time.time()
        self._active_start   = None
        self._angle_history  = []
        self._milestones     = []
        self._rep_timestamps = []
