# RehabVision 🦴
## Computer Vision Physiotherapy Monitoring System

Real-time rehabilitation assessment powered by MediaPipe Pose + Flask + vanilla JS.
Point a webcam at a patient, select an exercise, press START — instant joint angle tracking,
rep counting, range-of-motion analysis, and coaching feedback in your browser.

---

## Quick Start (3 steps)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run
python run.py

# 3. Open browser
#    http://localhost:5000
```

> **No camera?** That's fine — the system automatically falls back to
> an animated demo skeleton. Every feature works in demo mode.

---

## Features

| Feature | Details |
|---|---|
| **33-joint detection** | MediaPipe Pose, 30fps, smooth tracking |
| **Joint angle math** | Stable arctan2 formula (not arccos) |
| **9 exercise protocols** | Shoulder, elbow, knee, hip, ankle, trunk, neck |
| **Rep counting** | Hysteresis state machine — no false positives |
| **Live feedback** | 4-tier coaching messages (far/near/perfect/over) |
| **Angle chart** | 60-second rolling time-series with target zone |
| **Session logging** | Milestones, ROM stats, cadence |
| **MJPEG stream** | Annotated skeleton overlay on camera feed |
| **SSE push** | 30fps live data to browser — no polling |
| **Demo mode** | Animated skeleton if no camera available |

---

## Project Structure

```
rehabvision/
│
├── run.py                        ← ENTRY POINT — run this
├── requirements.txt
│
├── backend/                      ← Python (Flask + ML)
│   ├── app.py                    ← Flask server, routes, SSE, MJPEG
│   ├── pose_engine.py            ← Camera + MediaPipe Pose wrapper
│   ├── angle_calculator.py       ← 3-point joint angle math
│   ├── exercise_manager.py       ← Exercise protocols + feedback logic
│   └── session_tracker.py        ← Rep state machine + session log
│
└── frontend/                     ← Browser (HTML + CSS + JS)
    ├── templates/
    │   └── index.html            ← Dashboard page
    └── static/
        ├── css/style.css         ← All styling
        └── js/app.js             ← SSE listener, UI updaters, chart
```

---

## Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         BROWSER                                  │
│                                                                  │
│  <img src="/video_feed">   EventSource("/stream")   REST calls  │
│         ↑                        ↑                    ↕         │
└─────────┼────────────────────────┼────────────────────┼─────────┘
          │  MJPEG bytes           │  JSON ~30fps        │
┌─────────┼────────────────────────┼────────────────────┼─────────┐
│         │          FLASK SERVER (app.py)               │         │
│  /video_feed          /stream             /api/*        │         │
│         │                │                             │         │
└─────────┼────────────────┼─────────────────────────────┼─────────┘
          │                │  reads shared_state          │
┌─────────┼────────────────┼──────────────────────────────┘
│         ↓                ↓             BACKGROUND THREAD
│   get_annotated_frame()  shared_state (threading.Lock)
│         ↑                ↑
│         └────── processing_loop() ─────┐
│                                        │
│  ┌─────────────────────────────────┐   │
│  │  1. PoseEngine.process_next_frame()  │
│  │     OpenCV → flip → MediaPipe   │   │
│  │     → 33 landmarks              │   │
│  │     → draw skeleton overlay     │   │
│  │     → JPEG encode               │   │
│  ├─────────────────────────────────┤   │
│  │  2. AngleCalculator             │   │
│  │     .compute_all_angles()       │   │
│  │     .get_primary_angle()        │   │
│  │     → arctan2 formula           │   │
│  ├─────────────────────────────────┤   │
│  │  3. ExerciseManager             │   │
│  │     .get_feedback()             │   │
│  │     → 4-tier feedback rules     │   │
│  ├─────────────────────────────────┤   │
│  │  4. SessionTracker              │   │
│  │     .update()                   │   │
│  │     → RepStateMachine           │   │
│  │     → is_rep? log_milestone()   │   │
│  └─────────────────────────────────┘   │
└────────────────────────────────────────┘
```

---

## Exercises (9 built-in)

| ID | Exercise | Joint | Target ROM |
|---|---|---|---|
| `shoulder_flex` | Shoulder Flexion | R Shoulder | 60°–170° |
| `shoulder_abd`  | Shoulder Abduction | R Shoulder | 60°–160° |
| `elbow_flex`    | Elbow Flexion | R Elbow | 20°–145° |
| `knee_ext`      | Knee Extension | R Knee | 90°–175° |
| `knee_flex`     | Knee Flexion | R Knee | 20°–130° |
| `hip_abd`       | Hip Abduction | R Hip | 10°–45° |
| `hip_flex`      | Hip Flexion | R Hip | 45°–120° |
| `ankle_df`      | Ankle Dorsiflexion | R Ankle | 70°–110° |
| `trunk_flex`    | Trunk Flexion | Lumbar | 30°–90° |
| `neck_flex`     | Cervical Flexion | Cervical | 20°–80° |

---

## Rep Counting — How It Works

```
File: backend/session_tracker.py → class RepStateMachine

           UP_THRESH = target_min + 65% × span
           DN_THRESH = target_min + 35% × span

Angle: ________/‾‾‾‾‾‾‾‾‾‾\________/‾‾‾‾‾‾‾‾‾‾\________
               ↑UP          ↓DN      ↑UP          ↓DN
State: idle → ascending → idle(rep!) ascending → idle(rep!)
                                REP 1                REP 2
```

**Why hysteresis?**
A single threshold causes double-counting when the angle wobbles near
the boundary. Two thresholds (with a gap between them) ensure a full
excursion is required before a rep is counted.

---

## Joint Angle Formula

```python
# File: backend/angle_calculator.py → _angle_at_b()

# Vectors from vertex B to points A and C
BA = (A.x - B.x, A.y - B.y)
BC = (C.x - B.x, C.y - B.y)

# Components of the angle
dot   = BA.x*BC.x + BA.y*BC.y          # |BA||BC|·cos(θ)
cross = |BA.x*BC.y - BA.y*BC.x|        # |BA||BC|·sin(θ)

# arctan2 is stable at all angles [0°, 180°]
θ = degrees(atan2(cross, dot))
```

Using `atan2` instead of `arccos` avoids the numerical instability
that occurs when the angle is near 0° or 180°.

---

## REST API Reference

| Method | Endpoint | Body / Response |
|---|---|---|
| `GET` | `/` | HTML dashboard |
| `GET` | `/video_feed` | MJPEG stream |
| `GET` | `/stream` | SSE stream (JSON ~30fps) |
| `GET` | `/api/health` | `{"status","camera","fps"}` |
| `GET` | `/api/exercises` | `[{id,name,joint,...}]` |
| `POST` | `/api/exercise/set` | `{"exercise_id":"knee_ext"}` |
| `POST` | `/api/session/start` | `{}` |
| `POST` | `/api/session/stop` | `{}` |
| `POST` | `/api/session/reset` | `{}` |
| `GET` | `/api/session/log` | `{milestones, summary, angle_history}` |
| `GET` | `/api/state` | Full state snapshot |

### SSE stream payload (per frame)
```json
{
  "angles":        {"right_shoulder": 95.3, "right_elbow": 142.1, ...},
  "primary_angle": 95.3,
  "feedback":      "✓  Perfect — hold that range!",
  "rep_count":     7,
  "phase":         "up",
  "in_range":      true,
  "fps":           28.4,
  "active":        true,
  "camera_ok":     true,
  "exercise_id":   "shoulder_flex"
}
```

---

## Adding a New Exercise

### Step 1 — `backend/exercise_manager.py`
```python
"wrist_ext": {
    "id":          "wrist_ext",
    "name":        "Wrist Extension",
    "joint":       "Right Wrist",
    "target_min":  20,
    "target_max":  70,
    "rep_trigger": "peak",
    "instruction": "Extend wrist upward from neutral, then return.",
    "phases":      {"up": "Extending", "down": "Flexing"},
    "color":       "#ff9f1c",
    "category":    "upper",
    "muscles":     "Extensor carpi radialis longus & brevis",
    "goal_reps":   15,
    "notes":       "Avoid pain. Normal ROM: 0–70°.",
},
```

### Step 2 — `backend/angle_calculator.py` (JOINT_TRIPLETS)
```python
"right_wrist": (14, 16, 18),   # R_elbow → R_wrist → R_pinky (idx 18)
```

### Step 3 — `backend/angle_calculator.py` (EXERCISE_PRIMARY)
```python
"wrist_ext": "right_wrist",
```

### Step 4 — Nothing! Frontend auto-populates from `/api/exercises`.

---

## Command-line Options

```
python run.py --help

  --port   N    HTTP port           (default: 5000)
  --camera N    Camera device index (default: 0)
  --debug       Enable Flask debug mode
```

---

## Troubleshooting

**"DEMO MODE — NO CAMERA"**
- Another app may be using the camera
- Try `python run.py --camera 1` (or 2)
- On macOS: System Preferences → Privacy → Camera → allow Terminal

**Slow FPS (< 15)**
- Change `model_complexity=0` in `pose_engine.py` (faster, less accurate)
- Reduce resolution: set 320×240 in `_open_camera()`

**Port in use**
```bash
python run.py --port 8080
```

**"mediapipe not found"**
```bash
pip install -r requirements.txt
# or
pip install mediapipe opencv-python flask flask-cors numpy
```

---

## Requirements

- Python 3.9–3.12
- Webcam (optional — demo mode works without)
- Modern browser (Chrome, Firefox, Safari, Edge)

---

## License

MIT — free for research, education, and clinical development.
