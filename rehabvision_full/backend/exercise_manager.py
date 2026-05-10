"""
╔══════════════════════════════════════════════════════════════════════╗
║                  backend/exercise_manager.py                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  PURPOSE:                                                           ║
║    - Define all physiotherapy exercise protocols                    ║
║    - Generate real-time coaching feedback messages                  ║
║    - Provide clinical descriptions for the UI                       ║
║                                                                     ║
║  HOW TO ADD A NEW EXERCISE:                                         ║
║    1. Add an entry to EXERCISES dict below (follow the template)    ║
║    2. Add the joint triplet to AngleCalculator.JOINT_TRIPLETS       ║
║    3. Add an entry to AngleCalculator.EXERCISE_PRIMARY              ║
║    4. Add to the getJointKey() map in frontend/static/js/app.js     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Exercise Protocol Definitions
# ─────────────────────────────────────────────────────────────────────────────
#
# FIELD REFERENCE:
#   id           → machine key used in API calls and URL params
#   name         → display name shown in the sidebar
#   joint        → human label for the primary joint being measured
#   target_min   → lower bound of therapeutic ROM in degrees
#   target_max   → upper bound of therapeutic ROM in degrees
#   rep_trigger  → "peak" (count at return from max) | "cycle" (every crossing)
#   instruction  → patient-facing plain-language description
#   phases       → dict mapping "up"/"down" → phase label
#   color        → hex accent colour for UI theming
#   category     → "upper" | "lower" | "trunk" | "neck"
#   muscles      → primary muscles being exercised (informational)
#   goal_reps    → default rep target per set
#   notes        → optional clinical notes
# ─────────────────────────────────────────────────────────────────────────────

EXERCISES = {

    # ── Upper Limb ────────────────────────────────────────────────────────────

    "shoulder_flex": {
        "id":          "shoulder_flex",
        "name":        "Shoulder Flexion",
        "joint":       "Right Shoulder",
        "target_min":  60,
        "target_max":  170,
        "rep_trigger": "peak",
        "instruction": "Stand upright. Raise your right arm forward from "
                       "your side to above your head, then lower it back down.",
        "phases":      {"up": "Raising arm", "down": "Lowering arm"},
        "color":       "#00f5d4",
        "category":    "upper",
        "muscles":     "Anterior deltoid, pectoralis major (clavicular head)",
        "goal_reps":   10,
        "notes":       "Normal ROM: 0–180°. Post-surgery target often 90–150°.",
    },

    "shoulder_abd": {
        "id":          "shoulder_abd",
        "name":        "Shoulder Abduction",
        "joint":       "Right Shoulder",
        "target_min":  60,
        "target_max":  160,
        "rep_trigger": "peak",
        "instruction": "Stand upright. Raise your right arm out to the side "
                       "until horizontal or overhead, then return.",
        "phases":      {"up": "Abducting", "down": "Adducting"},
        "color":       "#f7b731",
        "category":    "upper",
        "muscles":     "Middle deltoid, supraspinatus (rotator cuff)",
        "goal_reps":   10,
        "notes":       "Painful arc 60–120° may indicate impingement.",
    },

    "elbow_flex": {
        "id":          "elbow_flex",
        "name":        "Elbow Flexion",
        "joint":       "Right Elbow",
        "target_min":  20,
        "target_max":  145,
        "rep_trigger": "peak",
        "instruction": "Keeping your upper arm still, curl your forearm "
                       "up toward your shoulder, then lower it fully.",
        "phases":      {"up": "Curling up", "down": "Lowering down"},
        "color":       "#7209b7",
        "category":    "upper",
        "muscles":     "Biceps brachii, brachialis, brachioradialis",
        "goal_reps":   12,
        "notes":       "Full extension target: <10°. Full flexion: >140°.",
    },

    # ── Lower Limb ────────────────────────────────────────────────────────────

    "knee_ext": {
        "id":          "knee_ext",
        "name":        "Knee Extension",
        "joint":       "Right Knee",
        "target_min":  90,
        "target_max":  175,
        "rep_trigger": "peak",
        "instruction": "Sit on a chair. Slowly straighten your right knee "
                       "until fully extended, hold 2 seconds, then lower.",
        "phases":      {"up": "Extending", "down": "Flexing"},
        "color":       "#f72585",
        "category":    "lower",
        "muscles":     "Quadriceps: rectus femoris, vastus lateralis, "
                       "vastus medialis, vastus intermedius",
        "goal_reps":   15,
        "notes":       "Critical post-ACL / TKR exercise. Target: >160° extension.",
    },

    "knee_flex": {
        "id":          "knee_flex",
        "name":        "Knee Flexion",
        "joint":       "Right Knee",
        "target_min":  20,
        "target_max":  130,
        "rep_trigger": "peak",
        "instruction": "Stand holding a support. Bend your right knee, "
                       "bringing your heel toward your buttock, then lower.",
        "phases":      {"up": "Flexing", "down": "Extending"},
        "color":       "#ff6b6b",
        "category":    "lower",
        "muscles":     "Hamstrings: biceps femoris, semitendinosus, semimembranosus",
        "goal_reps":   12,
        "notes":       "Normal ROM: 0–135°. Post-TKR target: >120° by 6 weeks.",
    },

    "hip_abd": {
        "id":          "hip_abd",
        "name":        "Hip Abduction",
        "joint":       "Right Hip",
        "target_min":  10,
        "target_max":  45,
        "rep_trigger": "peak",
        "instruction": "Stand upright. Keeping your torso still, raise your "
                       "right leg out to the side, then return.",
        "phases":      {"up": "Abducting", "down": "Adducting"},
        "color":       "#4cc9f0",
        "category":    "lower",
        "muscles":     "Gluteus medius, gluteus minimus, tensor fasciae latae",
        "goal_reps":   12,
        "notes":       "Normal ROM: 0–45°. Essential post-hip replacement rehab.",
    },

    "hip_flex": {
        "id":          "hip_flex",
        "name":        "Hip Flexion",
        "joint":       "Right Hip",
        "target_min":  45,
        "target_max":  120,
        "rep_trigger": "peak",
        "instruction": "Stand upright. Lift your right knee toward your chest, "
                       "hold briefly, then lower.",
        "phases":      {"up": "Flexing", "down": "Extending"},
        "color":       "#fb5607",
        "category":    "lower",
        "muscles":     "Iliopsoas (iliacus + psoas major), rectus femoris",
        "goal_reps":   12,
        "notes":       "Normal ROM: 0–120°. Avoid >90° post-hip replacement.",
    },

    "ankle_df": {
        "id":          "ankle_df",
        "name":        "Ankle Dorsiflexion",
        "joint":       "Right Ankle",
        "target_min":  70,
        "target_max":  110,
        "rep_trigger": "cycle",
        "instruction": "Sitting or standing. Flex your foot up (toes toward shin), "
                       "then point it down. Repeat rhythmically.",
        "phases":      {"up": "Dorsiflexing", "down": "Plantarflexing"},
        "color":       "#06d6a0",
        "category":    "lower",
        "muscles":     "Tibialis anterior (dorsiflexion); "
                       "gastrocnemius + soleus (plantarflexion)",
        "goal_reps":   20,
        "notes":       "Normal dorsiflexion: 20°. Plantarflexion: 50°.",
    },

    # ── Trunk ─────────────────────────────────────────────────────────────────

    "trunk_flex": {
        "id":          "trunk_flex",
        "name":        "Trunk Flexion",
        "joint":       "Lumbar Spine",
        "target_min":  30,
        "target_max":  90,
        "rep_trigger": "peak",
        "instruction": "Stand with feet shoulder-width apart. Bend forward "
                       "at the waist, reaching toward the floor, then return.",
        "phases":      {"up": "Bending forward", "down": "Returning upright"},
        "color":       "#e9c46a",
        "category":    "trunk",
        "muscles":     "Erector spinae (eccentric), abdominals, hamstrings",
        "goal_reps":   10,
        "notes":       "Normal ROM: 0–90°. Instruct neutral spine on return.",
    },

    # ── Neck ──────────────────────────────────────────────────────────────────

    "neck_flex": {
        "id":          "neck_flex",
        "name":        "Cervical Flexion",
        "joint":       "Cervical Spine",
        "target_min":  20,
        "target_max":  80,
        "rep_trigger": "peak",
        "instruction": "Sit upright. Tuck your chin and bend your head forward "
                       "toward your chest, then return to neutral.",
        "phases":      {"up": "Flexing", "down": "Extending"},
        "color":       "#a8dadc",
        "category":    "neck",
        "muscles":     "Sternocleidomastoid, scalenes, deep cervical flexors",
        "goal_reps":   10,
        "notes":       "Normal flexion: 0–80°. Perform slowly without pain.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Feedback engine
# ─────────────────────────────────────────────────────────────────────────────

def _build_feedback_tiers(target_min: int, target_max: int):
    """
    Build graduated feedback rules for a given ROM range.

    Returns a list of (predicate_fn, message_str) tuples.
    Evaluated in order — first matching predicate wins.

    Tiers
    ─────
    1. Far below minimum   (< min – 30% span) → strong encourage
    2. Slightly below min  (< min)             → gentle push
    3. In target range     [min, max]          → positive reinforcement
    4. Slightly above max  (> max)             → ease back

    Why graduated?
    Abrupt binary feedback ("good / bad") is less motivating than
    messages that proportionally reflect the patient's effort.
    """
    span  = max(target_max - target_min, 1)
    far   = target_min - span * 0.3          # "far below" threshold

    return [
        (lambda a: a < far,                         "⬆  Push further — increase your range"),
        (lambda a: a < target_min,                  "↑  Almost there — a little more"),
        (lambda a: target_min <= a <= target_max,   "✓  Perfect — hold that range!"),
        (lambda a: a > target_max,                  "↓  Ease back slightly"),
    ]


class ExerciseManager:
    """
    Manages exercise selection and generates real-time feedback.

    Usage
    ─────
    mgr = ExerciseManager()
    ex  = mgr.set_exercise("elbow_flex")
    msg = mgr.get_feedback(current_angle, ex)
    """

    def __init__(self):
        self._active_id = "shoulder_flex"

    def set_exercise(self, exercise_id: str) -> dict:
        """
        Switch the active exercise.

        Parameters
        ----------
        exercise_id : str
            Must match a key in EXERCISES.

        Returns
        -------
        dict — the full exercise protocol object.

        Raises
        ------
        KeyError if exercise_id is unknown.
        """
        if exercise_id not in EXERCISES:
            valid = list(EXERCISES.keys())
            raise KeyError(
                f"Unknown exercise '{exercise_id}'. Valid IDs: {valid}"
            )
        self._active_id = exercise_id
        return EXERCISES[exercise_id]

    def get_exercise(self, exercise_id: Optional[str] = None) -> dict:
        """Return a protocol dict. Defaults to currently active exercise."""
        eid = exercise_id or self._active_id
        return EXERCISES.get(eid, EXERCISES["shoulder_flex"])

    def get_all_exercises(self) -> list:
        """Return list of all protocol dicts (for the frontend selector)."""
        return list(EXERCISES.values())

    def get_feedback(self, angle: float, exercise: dict) -> str:
        """
        Generate a coaching feedback string.

        Parameters
        ----------
        angle    : Current measured joint angle in degrees.
        exercise : Exercise protocol dict (must have target_min, target_max).

        Returns
        -------
        str — human-readable feedback message.
        """
        if angle <= 0:
            return "—  Waiting for landmark detection"

        tiers = _build_feedback_tiers(
            exercise["target_min"],
            exercise["target_max"],
        )
        for predicate, message in tiers:
            if predicate(angle):
                return message

        return "✓  Good form"

    def get_phase_label(self, exercise_id: str, phase: str) -> str:
        """Return human-readable label for a movement phase."""
        ex = self.get_exercise(exercise_id)
        return ex.get("phases", {}).get(phase, phase.upper())
