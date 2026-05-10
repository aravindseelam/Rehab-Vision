"""
╔══════════════════════════════════════════════════════════════════════╗
║         RehabVision — Computer Vision Physiotherapy Monitor         ║
║                        backend/app.py                               ║
╠══════════════════════════════════════════════════════════════════════╣
║  PURPOSE:                                                           ║
║    Central Flask web server. Orchestrates all backend modules and   ║
║    exposes endpoints to the browser dashboard.                      ║
║                                                                     ║
║  ENDPOINTS:                                                         ║
║    GET  /                    → HTML dashboard                       ║
║    GET  /video_feed          → MJPEG annotated camera stream        ║
║    GET  /stream              → Server-Sent Events (live JSON ~30fps)║
║    GET  /api/exercises       → List all exercise protocols          ║
║    POST /api/exercise/set    → Switch active exercise               ║
║    POST /api/session/start   → Begin rep counting                   ║
║    POST /api/session/stop    → Pause session                        ║
║    POST /api/session/reset   → Clear all session data               ║
║    GET  /api/session/log     → Full session log + summary           ║
║    GET  /api/state           → One-shot state snapshot              ║
║    GET  /api/health          → Server health check                  ║
║                                                                     ║
║  CONCURRENCY MODEL:                                                 ║
║    A single daemon thread runs the pose-detection loop at ~30fps.  ║
║    Results are written to `shared_state` behind a threading.Lock.  ║
║    Flask serves SSE + MJPEG from the main thread pool (threaded=T).║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import time
import threading
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

# ── Internal modules (all in /backend/) ──────────────────────────────────────
from pose_engine      import PoseEngine
from angle_calculator import AngleCalculator
from exercise_manager import ExerciseManager
from session_tracker  import SessionTracker

# ─────────────────────────────────────────────────────────────────────────────
# Flask App
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
)
CORS(app)  # Allow cross-origin during development

# ─────────────────────────────────────────────────────────────────────────────
# Module Singletons  (created once, shared across requests)
# ─────────────────────────────────────────────────────────────────────────────
pose_engine      = PoseEngine(camera_index=int(os.environ.get("REHAB_CAMERA", 0)))
angle_calc       = AngleCalculator()
exercise_manager = ExerciseManager()
session_tracker  = SessionTracker()

# ─────────────────────────────────────────────────────────────────────────────
# Shared State
# ─────────────────────────────────────────────────────────────────────────────
# This dict is written by the background thread and read by SSE/REST handlers.
# ALL access must be wrapped in `with state_lock:`.
state_lock   = threading.Lock()
shared_state = {
    "landmarks":     None,          # List[dict] — 33 MediaPipe landmarks
    "angles":        {},            # Dict[joint_name → degrees]
    "primary_angle": 0,             # Float — the exercise's key joint angle
    "feedback":      "Press START", # String — real-time coaching message
    "rep_count":     0,             # Int — reps in current session
    "phase":         "idle",        # "idle" | "up" | "down"
    "in_range":      False,         # Bool — angle within target ROM?
    "fps":           0.0,           # Float — processing frame rate
    "exercise_id":   "shoulder_flex",
    "active":        False,         # Bool — is session running?
    "camera_ok":     False,         # Bool — camera available?
}

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Pages
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main dashboard HTML page."""
    return render_template("index.html")


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Video
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/video_feed")
def video_feed():
    """
    MJPEG video stream with skeleton overlay.

    The browser connects once via:
        <img src="/video_feed">

    and this generator pushes annotated JPEG frames continuously.
    Format: multipart/x-mixed-replace (standard MJPEG over HTTP).
    """
    def generate():
        while True:
            frame = pose_engine.get_annotated_frame()
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
            time.sleep(0.033)   # ~30fps cap

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Server-Sent Events
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/stream")
def stream():
    """
    Server-Sent Events endpoint.

    The browser subscribes once:
        const es = new EventSource('/stream');
        es.onmessage = (e) => { const d = JSON.parse(e.data); ... };

    We push ~30 JSON messages per second containing all live values.
    This avoids polling and keeps latency under 50ms.

    SSE wire format:
        data: {"angles": {...}, "rep_count": 7, ...}\n\n
    """
    def event_generator():
        while True:
            with state_lock:
                payload = {
                    "angles":        shared_state["angles"],
                    "primary_angle": shared_state["primary_angle"],
                    "feedback":      shared_state["feedback"],
                    "rep_count":     shared_state["rep_count"],
                    "phase":         shared_state["phase"],
                    "in_range":      shared_state["in_range"],
                    "fps":           round(shared_state["fps"], 1),
                    "active":        shared_state["active"],
                    "camera_ok":     shared_state["camera_ok"],
                    "exercise_id":   shared_state["exercise_id"],
                }
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(0.033)

    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering":"no",       # Disable Nginx buffering
            "Connection":       "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes — REST API
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    """Health check — useful for Docker / load balancer probes."""
    with state_lock:
        cam = shared_state["camera_ok"]
        fps = shared_state["fps"]
    return jsonify({"status": "ok", "camera": cam, "fps": fps})


@app.route("/api/exercises")
def get_exercises():
    """
    Return all exercise protocol definitions.

    Response: JSON array of exercise objects:
      [{ id, name, joint, target_min, target_max, color, ... }, ...]
    """
    return jsonify(exercise_manager.get_all_exercises())


@app.route("/api/exercise/set", methods=["POST"])
def set_exercise():
    """
    Switch the active exercise protocol.

    Request body:  { "exercise_id": "knee_ext" }
    Response:      { "status": "ok", "exercise": {...} }
    """
    data    = request.get_json(force=True)
    ex_id   = data.get("exercise_id", "shoulder_flex")

    try:
        exercise = exercise_manager.set_exercise(ex_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400

    with state_lock:
        shared_state["exercise_id"]   = ex_id
        shared_state["rep_count"]     = 0
        shared_state["phase"]         = "idle"
        shared_state["primary_angle"] = 0
        session_tracker.reset()

    return jsonify({"status": "ok", "exercise": exercise})


@app.route("/api/session/start", methods=["POST"])
def start_session():
    """Enable rep-counting and live feedback."""
    with state_lock:
        shared_state["active"] = True
        session_tracker.set_active(True)
    return jsonify({"status": "started"})


@app.route("/api/session/stop", methods=["POST"])
def stop_session():
    """Pause rep-counting (keeps existing data)."""
    with state_lock:
        shared_state["active"] = False
        session_tracker.set_active(False)
    return jsonify({"status": "stopped"})


@app.route("/api/session/reset", methods=["POST"])
def reset_session():
    """Clear all session data and reset rep counter."""
    with state_lock:
        shared_state["active"]        = False
        shared_state["rep_count"]     = 0
        shared_state["phase"]         = "idle"
        shared_state["primary_angle"] = 0
        session_tracker.reset()
    return jsonify({"status": "ok"})


@app.route("/api/session/log")
def session_log():
    """
    Return full session log with milestones and statistics.

    Response:
    {
      "milestones": [{ rep, angle, time, elapsed_s }, ...],
      "summary": {
        "total_reps", "session_time", "max_angle",
        "min_angle", "rom_achieved", "avg_rep_time"
      },
      "angle_history": [float, ...]    ← last 60 seconds
    }
    """
    return jsonify(session_tracker.get_log())


@app.route("/api/state")
def get_state():
    """One-shot snapshot of the current shared state (for polling clients)."""
    with state_lock:
        return jsonify(dict(shared_state))


# ─────────────────────────────────────────────────────────────────────────────
# Background Pose-Detection Thread
# ─────────────────────────────────────────────────────────────────────────────

def processing_loop():
    """
    Runs forever in a daemon thread, executing the full pipeline:

      Frame → MediaPipe → Angles → Feedback → RepCount → shared_state

    Performance target: ≥25fps on a modern laptop CPU.

    This function never raises — exceptions are caught and logged so
    the thread stays alive even if individual frames fail.
    """
    fps_count = 0
    fps_timer = time.time()
    fps_val   = 0.0

    while True:
        try:
            # ── 1. Capture frame + run MediaPipe ─────────────────────────
            result = pose_engine.process_next_frame()
            if result is None:
                time.sleep(0.01)
                continue

            landmarks_raw, landmarks_norm = result

            # ── 2. Read current exercise config (lock-free copy) ──────────
            with state_lock:
                exercise_id = shared_state["exercise_id"]
                active      = shared_state["active"]

            # ── 3. Compute all joint angles ───────────────────────────────
            angles        = angle_calc.compute_all_angles(landmarks_norm)
            primary_angle = angle_calc.get_primary_angle(landmarks_norm, exercise_id)

            # ── 4. Evaluate form quality ──────────────────────────────────
            exercise = exercise_manager.get_exercise(exercise_id)
            feedback = exercise_manager.get_feedback(primary_angle, exercise)
            in_range = (exercise["target_min"] <= primary_angle <= exercise["target_max"])

            # ── 5. Rep counting (only when session is active) ─────────────
            phase  = "idle"
            is_rep = False
            if active and primary_angle > 0:
                phase, is_rep = session_tracker.update(primary_angle, exercise)

            # ── 6. FPS tracking ───────────────────────────────────────────
            fps_count += 1
            now = time.time()
            if now - fps_timer >= 1.0:
                fps_val   = fps_count / (now - fps_timer)
                fps_count = 0
                fps_timer = now

            # ── 7. Update shared state (single lock acquisition) ──────────
            with state_lock:
                if active and is_rep:
                    shared_state["rep_count"] += 1
                    session_tracker.log_milestone(
                        shared_state["rep_count"], primary_angle
                    )

                shared_state["landmarks"]     = landmarks_norm
                shared_state["angles"]        = angles
                shared_state["primary_angle"] = primary_angle
                shared_state["feedback"]      = feedback
                shared_state["phase"]         = phase
                shared_state["in_range"]      = in_range
                shared_state["fps"]           = fps_val
                shared_state["camera_ok"]     = pose_engine.is_camera_open()

        except Exception as exc:
            # Log but never crash the thread
            print(f"[processing_loop] Error: {exc}")
            time.sleep(0.1)


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RehabVision Server")
    parser.add_argument("--port",   type=int, default=5000)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--debug",  action="store_true")
    args = parser.parse_args()

    os.environ["REHAB_CAMERA"] = str(args.camera)

    print("\n" + "═" * 56)
    print("  RehabVision  ─  Physiotherapy AI Monitor")
    print("═" * 56)
    print(f"  Camera : index {args.camera}")
    print(f"  Port   : {args.port}")

    # Start background processing thread
    bg_thread = threading.Thread(target=processing_loop, daemon=True)
    bg_thread.start()
    print("  Processing thread started ✓")
    print(f"\n  Dashboard  →  http://localhost:{args.port}")
    print(f"  Video Feed →  http://localhost:{args.port}/video_feed")
    print("═" * 56 + "\n")

    app.run(
        host="0.0.0.0",
        port=args.port,
        debug=args.debug,
        threaded=True,
        use_reloader=False,  # Must be False with background threads
    )
