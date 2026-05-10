import streamlit as st
import cv2
import av
import mediapipe as mp
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase

# --- 1. Import Backend Logic ---
from backend.angle_calculator import AngleCalculator
from backend.exercise_manager import ExerciseManager
from backend.session_tracker import SessionTracker

# --- 2. Streamlit Page Config ---
st.set_page_config(page_title="RehabVision AI", page_icon="🦾", layout="wide")
st.title("RehabVision — Physiotherapy AI Monitor")

# --- Temporary UI Manager (For Sidebar Options) ---
ui_ex_mgr = ExerciseManager()

# --- 3. Sidebar Controls ---
with st.sidebar:
    st.header("Exercise Settings")
    exercises = ui_ex_mgr.get_all_exercises()
    ex_names = {ex['id']: ex['name'] for ex in exercises}
    
    selected_ex_id = st.selectbox(
        "Select Protocol", 
        options=list(ex_names.keys()), 
        format_func=lambda x: ex_names[x]
    )
    
    active_ex = ui_ex_mgr.set_exercise(selected_ex_id)
    st.info(f"**Target:** {active_ex['joint']}\n\n**Instructions:** {active_ex['instruction']}")
    
    start_btn = st.button("▶ Start", use_container_width=True)
    stop_btn = st.button("⏹ Stop", use_container_width=True)
    reset_btn = st.button("🔄 Reset Session", use_container_width=True)

# --- 4. Video Processing Logic (Background Thread) ---
class PoseProcessor(VideoProcessorBase):
    def __init__(self):
        # We initialize everything directly inside the background thread here!
        self.angle_calc = AngleCalculator()
        self.ex_mgr = ExerciseManager()
        self.tracker = SessionTracker()
        self.mp_pose_inst = mp.solutions.pose.Pose(
            min_detection_confidence=0.5, 
            min_tracking_confidence=0.5
        )
        self.mp_draw_inst = mp.solutions.drawing_utils
        self.is_active = False

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1) 
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        results = self.mp_pose_inst.process(rgb)
        
        if results.pose_landmarks:
            self.mp_draw_inst.draw_landmarks(
                img, 
                results.pose_landmarks, 
                mp.solutions.pose.POSE_CONNECTIONS,
                self.mp_draw_inst.DrawingSpec(color=(0, 245, 200), thickness=2, circle_radius=2),
                self.mp_draw_inst.DrawingSpec(color=(255, 255, 255), thickness=2)
            )
            
            landmarks_norm = [{"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility} for lm in results.pose_landmarks.landmark]
            
            ex_id = self.ex_mgr._active_id
            active_ex = self.ex_mgr.get_exercise(ex_id)
            raw_angle = self.angle_calc.get_primary_angle(landmarks_norm, ex_id)
            feedback = self.ex_mgr.get_feedback(raw_angle, active_ex)
            
            # Only track reps if the user pressed 'Start'
            if self.is_active:
                self.tracker.update(raw_angle, active_ex)
            
            cv2.rectangle(img, (0, 0), (img.shape[1], 50), (10, 15, 30), -1)
            cv2.putText(img, f"ANGLE: {int(raw_angle)} deg", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 245, 200), 2)
            cv2.putText(img, feedback.upper(), (280, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        return av.VideoFrame.from_ndarray(img, format="bgr24")

# --- 5. UI Layout ---
col_vid, col_stats = st.columns([2, 1])

with col_vid:
    # We save the video feed to a variable called 'ctx' (context)
    ctx = webrtc_streamer(
        key="rehab-vision", 
        video_processor_factory=PoseProcessor,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        media_stream_constraints={"video": True, "audio": False}
    )

with col_stats:
    st.subheader("Live Performance")
    
    # If the camera is on, we bridge the background thread back to the UI
    if ctx and ctx.state.playing and ctx.video_processor:
        
        # Send sidebar updates to the background thread
        ctx.video_processor.ex_mgr.set_exercise(selected_ex_id)
        
        if start_btn:
            ctx.video_processor.is_active = True
        if stop_btn:
            ctx.video_processor.is_active = False
        if reset_btn:
            ctx.video_processor.tracker.reset()
        
        # Pull the live math from the background thread to the UI
        log = ctx.video_processor.tracker.get_log()
        
        m_col1, m_col2 = st.columns(2)
        m_col1.metric("Total Reps", log["summary"]["total_reps"])
        m_col2.metric("Max Angle", f"{log['summary']['max_angle']}°")
        
        st.write("**Recent Reps**")
        if log["milestones"]:
            st.dataframe(log["milestones"], use_container_width=True, hide_index=True)
        else:
            st.caption("Perform your first rep to see logs...")
    else:
        st.info("Start the video stream to see live stats.")
