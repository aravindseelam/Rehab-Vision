import streamlit as st
import cv2
import av
import mediapipe as mp
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase

# IMPORT FIX: Pointing to the 'backend' folder
from backend.angle_calculator import AngleCalculator
from backend.exercise_manager import ExerciseManager
from backend.session_tracker import SessionTracker

# --- 1. Streamlit Page Config ---
st.set_page_config(page_title="RehabVision", layout="wide")
st.title("RehabVision — Physiotherapy AI Monitor")

# --- 2. Initialize Session State (Singletons) ---
if 'angle_calc' not in st.session_state:
    st.session_state.angle_calc = AngleCalculator()
    st.session_state.ex_mgr = ExerciseManager()
    st.session_state.tracker = SessionTracker()
    st.session_state.mp_pose = mp.solutions.pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    st.session_state.mp_draw = mp.solutions.drawing_utils

# --- 3. Sidebar UI for Controls ---
with st.sidebar:
    st.header("Controls")
    
    # Get all exercises for the dropdown
    exercises = st.session_state.ex_mgr.get_all_exercises()
    ex_names = {ex['id']: ex['name'] for ex in exercises}
    
    selected_ex_id = st.selectbox(
        "Select Exercise", 
        options=list(ex_names.keys()), 
        format_func=lambda x: ex_names[x]
    )
    
    # Update active exercise if changed
    active_ex = st.session_state.ex_mgr.set_exercise(selected_ex_id)
    
    st.markdown(f"**Instructions:** {active_ex['instruction']}")
    
    if st.button("Start Session"):
        st.session_state.tracker.set_active(True)
    if st.button("Stop Session"):
        st.session_state.tracker.set_active(False)
    if st.button("Reset"):
        st.session_state.tracker.reset()

# --- 4. WebRTC Video Processor ---
class PoseProcessor(VideoTransformerBase):
    def __init__(self):
        self.angle_calc = st.session_state.angle_calc
        self.ex_mgr = st.session_state.ex_mgr
        self.tracker = st.session_state.tracker
        self.mp_pose = st.session_state.mp_pose
        self.mp_draw = st.session_state.mp_draw

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1) # Mirror image
        
        # 1. Run MediaPipe
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.mp_pose.process(rgb)
        
        if results.pose_landmarks:
            # Draw Skeleton
            self.mp_draw.draw_landmarks(img, results.pose_landmarks, mp.solutions.pose.POSE_CONNECTIONS)
            
            # Format landmarks for your calculator
            landmarks_norm = [{"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility} for lm in results.pose_landmarks.landmark]
            
            # 2. Get active exercise data
            ex_id = self.ex_mgr._active_id
            active_ex = self.ex_mgr.get_exercise(ex_id)
            
            # 3. Calculate Angles & Feedback
            primary_angle = self.angle_calc.get_primary_angle(landmarks_norm, ex_id)
            feedback = self.ex_mgr.get_feedback(primary_angle, active_ex)
            
            # 4. Update Tracker
            phase, is_rep = self.tracker.update(primary_angle, active_ex)
            
            # 5. Draw HUD on the video frame
            cv2.rectangle(img, (0, 0), (img.shape[1], 40), (8, 11, 20), -1)
            cv2.putText(img, f"Angle: {primary_angle} deg", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 245, 200), 2)
            cv2.putText(img, feedback, (250, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 200, 76), 2)

        return av.VideoFrame.from_ndarray(img, format="bgr24")

# --- 5. Render Video Stream & Stats ---
col1, col2 = st.columns([2, 1])

with col1:
    webrtc_streamer(
        key="rehab-vision", 
        video_transformer_factory=PoseProcessor,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
    )

with col2:
    st.header("Live Stats")
    log = st.session_state.tracker.get_log()
    
    st.metric("Total Reps", log["summary"]["total_reps"])
    st.metric("Max Angle Achieved", f"{log['summary']['max_angle']}°")
    
    st.subheader("Milestones")
    st.dataframe(log["milestones"])
