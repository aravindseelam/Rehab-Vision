import streamlit as st
import cv2
import av
import mediapipe as mp

# --- THE FIX: Direct Absolute Imports for MediaPipe ---
from mediapipe.python.solutions import pose as mp_pose
from mediapipe.python.solutions import drawing_utils as mp_draw
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase

# --- 1. Import Backend Logic ---
from backend.angle_calculator import AngleCalculator
from backend.exercise_manager import ExerciseManager
from backend.session_tracker import SessionTracker

# --- 2. Streamlit Page Config ---
st.set_page_config(
    page_title="RehabVision AI",
    page_icon="🦾",
    layout="wide"
)

st.title("RehabVision — Physiotherapy AI Monitor")

# --- 3. Initialize Session State (Persistence) ---
if 'angle_calc' not in st.session_state:
    st.session_state.angle_calc = AngleCalculator()
    st.session_state.ex_mgr = ExerciseManager()
    st.session_state.tracker = SessionTracker()
    
    # Initialize Pose using the direct import
    st.session_state.mp_pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        min_detection_confidence=0.5, 
        min_tracking_confidence=0.5
    )
    st.session_state.mp_draw = mp_draw

# --- 4. Sidebar Controls ---
with st.sidebar:
    st.header("Exercise Settings")
    
    exercises = st.session_state.ex_mgr.get_all_exercises()
    ex_names = {ex['id']: ex['name'] for ex in exercises}
    
    selected_ex_id = st.selectbox(
        "Select Protocol", 
        options=list(ex_names.keys()), 
        format_func=lambda x: ex_names[x]
    )
    
    active_ex = st.session_state.ex_mgr.set_exercise(selected_ex_id)
    
    st.info(f"**Target:** {active_ex['joint']}\n\n**Instructions:** {active_ex['instruction']}")
    
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("▶ Start", use_container_width=True):
            st.session_state.tracker.set_active(True)
    with col_b:
        if st.button("⏹ Stop", use_container_width=True):
            st.session_state.tracker.set_active(False)
            
    if st.button("🔄 Reset Session", use_container_width=True):
        st.session_state.tracker.reset()
        st.rerun()

# --- 5. Video Processing Logic ---
class PoseProcessor(VideoTransformerBase):
    def __init__(self):
        self.angle_calc = st.session_state.angle_calc
        self.ex_mgr = st.session_state.ex_mgr
        self.tracker = st.session_state.tracker
        self.mp_pose_inst = st.session_state.mp_pose
        self.mp_draw_inst = st.session_state.mp_draw

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1) # Mirror for user comfort
        
        # RGB conversion for MediaPipe
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.mp_pose_inst.process(rgb)
        
        if results.pose_landmarks:
            # Draw skeleton overlay (Using direct mp_pose import for POSE_CONNECTIONS)
            self.mp_draw_inst.draw_landmarks(
                img, 
                results.pose_landmarks, 
                mp_pose.POSE_CONNECTIONS,
                self.mp_draw_inst.DrawingSpec(color=(0, 245, 200), thickness=2, circle_radius=2),
                self.mp_draw_inst.DrawingSpec(color=(255, 255, 255), thickness=2)
            )
            
            # Map landmarks to your backend format
            landmarks_norm = [
                {"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility} 
                for lm in results.pose_landmarks.landmark
            ]
            
            # Use your backend logic!
            ex_id = self.ex_mgr._active_id
            active_ex = self.ex_mgr.get_exercise(ex_id)
            
            # Calculate angle and get coaching feedback
            raw_angle = self.angle_calc.get_primary_angle(landmarks_norm, ex_id)
            feedback = self.ex_mgr.get_feedback(raw_angle, active_ex)
            
            # Update rep counter
            self.tracker.update(raw_angle, active_ex)
            
            # Draw HUD
            cv2.rectangle(img, (0, 0), (img.shape[1], 50), (10, 15, 30), -1)
            cv2.putText(img, f"ANGLE: {int(raw_angle)} deg", (20, 35), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 245, 200), 2)
            cv2.putText(img, feedback.upper(), (280, 35), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        return av.VideoFrame.from_ndarray(img, format="bgr24")

# --- 6. UI Layout ---
col_vid, col_stats = st.columns([2, 1])

with col_vid:
    webrtc_streamer(
        key="rehab-vision", 
        video_transformer_factory=PoseProcessor,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        media_stream_constraints={"video": True, "audio": False}
    )

with col_stats:
    st.subheader("Live Performance")
    log = st.session_state.tracker.get_log()
    
    m_col1, m_col2 = st.columns(2)
    m_col1.metric("Total Reps", log["summary"]["total_reps"])
    m_col2.metric("Max Angle", f"{log['summary']['max_angle']}°")
    
    st.write("**Recent Reps**")
    if log["milestones"]:
        st.dataframe(log["milestones"], use_container_width=True, hide_index=True)
    else:
        st.caption("Perform your first rep to see logs...")
