#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                       run.py — Launch Script                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  The only file you need to run directly.                            ║
║                                                                     ║
║  Usage:                                                             ║
║    python run.py                  # default port 5000, camera 0    ║
║    python run.py --port 8080      # custom port                    ║
║    python run.py --camera 1       # alternate camera               ║
║    python run.py --debug          # Flask debug mode               ║
║                                                                     ║
║  Then open:  http://localhost:5000                                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import argparse

# Add /backend to Python path so imports resolve correctly
ROOT    = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)


# ─────────────────────────────────────────────────────────────────────────────
# Dependency check
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_PACKAGES = {
    "flask":     "flask",
    "flask_cors":"flask-cors",
    "mediapipe": "mediapipe",
    "cv2":       "opencv-python",
    "numpy":     "numpy",
}

def check_dependencies():
    missing = []
    for module, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print("\n  ⚠  Missing packages:", ", ".join(missing))
        print("     Fix:  pip install -r requirements.txt\n")
        sys.exit(1)

    print("  Dependencies: all OK ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="RehabVision — Physiotherapy AI Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py\n"
            "  python run.py --port 8080\n"
            "  python run.py --camera 1 --port 8080\n"
        ),
    )
    parser.add_argument("--port",   type=int, default=5000, metavar="N",
                        help="HTTP port (default: 5000)")
    parser.add_argument("--camera", type=int, default=0,    metavar="N",
                        help="Camera device index (default: 0)")
    parser.add_argument("--debug",  action="store_true",
                        help="Enable Flask debug mode")
    args = parser.parse_args()

    print("\n" + "═" * 56)
    print("  RehabVision  ─  Physiotherapy AI Monitor")
    print("═" * 56)

    check_dependencies()

    # Pass camera index to PoseEngine via environment variable
    os.environ["REHAB_CAMERA"] = str(args.camera)

    # ── Import here (after path setup + dependency check) ────────────────────
    import threading
    from app import app, processing_loop

    # ── Start background pose-detection thread ────────────────────────────────
    print(f"  Camera  : index {args.camera}")
    print(f"  Port    : {args.port}")
    print("  Starting processing thread…")

    bg = threading.Thread(target=processing_loop, daemon=True)
    bg.start()
    print("  Background thread running ✓")

    print(f"\n  ➜  Open browser →  http://localhost:{args.port}")
    print("═" * 56 + "\n")

    # ── Run Flask ─────────────────────────────────────────────────────────────
    # threaded=True   — allows concurrent SSE + MJPEG connections
    # use_reloader=False — required when running background threads
    app.run(
        host="0.0.0.0",
        port=args.port,
        debug=args.debug,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
