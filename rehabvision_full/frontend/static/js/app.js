/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║              frontend/static/js/app.js                          ║
 * ╠══════════════════════════════════════════════════════════════════╣
 * ║  ARCHITECTURE                                                   ║
 * ║  ─────────────────────────────────────────────────────────────  ║
 * ║  1. On load → fetch /api/exercises → render sidebar             ║
 * ║  2. Connect EventSource to /stream → onStreamData() ~30fps      ║
 * ║  3. onStreamData() dispatches to individual updater functions   ║
 * ║  4. User actions → POST to REST API → local state update        ║
 * ║  5. Every 5s → GET /api/session/log → refresh Progress tab      ║
 * ║                                                                 ║
 * ║  NO EXTERNAL DEPENDENCIES — pure vanilla JS                     ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

"use strict";

// ─────────────────────────────────────────────────────────────────────────────
// Application State
// ─────────────────────────────────────────────────────────────────────────────
const App = {
  isRunning:      false,
  activeExercise: null,       // Full exercise object from /api/exercises
  exercises:      [],         // All exercise objects
  angleHistory:   [],         // Ring buffer, max 180 samples (6 s @ 30fps)
  sessionStart:   null,       // Date.now() when session began
  timerHandle:    null,       // setInterval handle for session clock
  sse:            null,       // EventSource instance
  goalReps:       10,
  prevRepCount:   0,
  accentColor:    "#00f5d4",
  chartCtx:       null,       // Canvas 2D context for angle chart
};

// ─────────────────────────────────────────────────────────────────────────────
// Startup
// ─────────────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  await loadExercises();
  connectSSE();
  setInterval(refreshProgressTab, 5000);
  initChart();
});

// ─────────────────────────────────────────────────────────────────────────────
// Exercise Loading & Selection
// ─────────────────────────────────────────────────────────────────────────────

async function loadExercises() {
  try {
    const res  = await fetch("/api/exercises");
    const list = await res.json();
    App.exercises = list;
    renderExerciseList(list);
    if (list.length > 0) await selectExercise(list[0]);
  } catch (e) {
    console.error("Could not load exercises:", e);
  }
}

function renderExerciseList(exercises) {
  const el = document.getElementById("exerciseList");
  el.innerHTML = "";
  exercises.forEach(ex => {
    const btn = document.createElement("button");
    btn.className  = "ex-btn";
    btn.dataset.id = ex.id;
    btn.innerHTML  = `
      <span class="ex-btn-name">${ex.name}</span>
      <span class="ex-btn-sub">${ex.joint} · ${ex.target_min}°–${ex.target_max}°</span>
    `;
    btn.onclick = () => selectExercise(ex);
    el.appendChild(btn);
  });
}

async function selectExercise(ex) {
  // Stop running session first
  if (App.isRunning) await stopSession();

  // Update active button
  document.querySelectorAll(".ex-btn").forEach(b => {
    const isActive = b.dataset.id === ex.id;
    b.classList.toggle("active", isActive);
    b.style.borderColor = isActive ? ex.color : "";
    b.style.background  = isActive ? ex.color + "14" : "";
    b.style.color       = isActive ? ex.color : "";
  });

  // Notify backend
  await fetch("/api/exercise/set", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ exercise_id: ex.id }),
  });

  // Update local state
  App.activeExercise = ex;
  App.accentColor    = ex.color;
  App.goalReps       = ex.goal_reps || 10;
  App.angleHistory   = [];
  App.prevRepCount   = 0;

  // Update UI labels
  document.getElementById("kpiAngleSub").textContent    = `${ex.target_min}° to ${ex.target_max}°`;
  document.getElementById("meterRangeLabel").textContent = `${ex.target_min}°–${ex.target_max}°`;
  document.getElementById("kpiRepsSub").textContent     = `goal: ${App.goalReps}`;
  document.getElementById("repGoalLabel").textContent   = App.goalReps;
  document.getElementById("repGoalInput").value         = App.goalReps;
  document.getElementById("catBadge").textContent       = (ex.category || "").toUpperCase();

  // Update arc colour
  const arc = document.getElementById("meterArc");
  arc.style.stroke = ex.color;
  arc.style.filter = `drop-shadow(0 0 8px ${ex.color})`;

  // Reset dots and progress
  renderRepDots(0);
  updateRepProgress(0);

  // Refresh guide tab
  renderGuide(ex);

  // Bottom info bar
  document.getElementById("infoExName").textContent  = ex.name;
  document.getElementById("infoJoint").textContent   = ex.joint;
  document.getElementById("infoMuscles").textContent = ex.muscles || "";
}

// ─────────────────────────────────────────────────────────────────────────────
// Server-Sent Events
// ─────────────────────────────────────────────────────────────────────────────

function connectSSE() {
  if (App.sse) App.sse.close();

  App.sse = new EventSource("/stream");

  App.sse.onmessage = e => {
    try { onStreamData(JSON.parse(e.data)); }
    catch (err) { console.warn("SSE parse error:", err); }
  };

  App.sse.onerror = () => {
    // Auto-reconnect
    setTimeout(connectSSE, 2500);
  };
}

/**
 * Central handler called ~30fps with live backend state.
 * Dispatches to individual UI updater functions.
 *
 * @param {Object} d  Parsed JSON from /stream
 * @param {Object} d.angles          All joint angles dict
 * @param {number} d.primary_angle   The exercise's key angle
 * @param {string} d.feedback        Coaching message
 * @param {number} d.rep_count       Reps this session
 * @param {string} d.phase           "idle"|"up"|"down"
 * @param {boolean} d.in_range       Angle within target ROM?
 * @param {number} d.fps             Processing frame rate
 * @param {boolean} d.active         Session running?
 * @param {boolean} d.camera_ok      Camera available?
 */
function onStreamData(d) {
  const ex = App.activeExercise;
  if (!ex) return;

  const angle    = d.primary_angle ?? 0;
  const reps     = d.rep_count     ?? 0;
  const phase    = d.phase         ?? "idle";
  const inRange  = d.in_range      ?? false;
  const feedback = d.feedback      ?? "—";
  const fps      = d.fps           ?? 0;
  const cameraOk = d.camera_ok     ?? false;

  // ── Rep change animation ───────────────────────────────────────────────────
  if (reps !== App.prevRepCount) {
    App.prevRepCount = reps;
    pulseRepCounter(reps);
    renderRepDots(reps);
    updateRepProgress(reps);
  }

  // ── Angle meter ────────────────────────────────────────────────────────────
  updateAngleMeter(angle, inRange);

  // ── KPI cards ──────────────────────────────────────────────────────────────
  document.getElementById("kpiAngleVal").textContent = angle > 0 ? `${angle}°` : "—";
  document.getElementById("kpiAngleVal").style.color = inRange ? ex.color : (angle > 0 ? "#f72585" : ex.color);
  document.getElementById("kpiRepsVal").textContent  = reps;

  const romPct = computeROMPct(ex);
  document.getElementById("kpiRomVal").textContent = `${romPct}%`;

  // ── Feedback ───────────────────────────────────────────────────────────────
  updateFeedback(feedback, inRange, angle, ex);

  // ── Phase pill ─────────────────────────────────────────────────────────────
  const pill = document.getElementById("phasePill");
  pill.textContent = `PHASE: ${phase.toUpperCase()}`;
  pill.className   = `phase-pill ${phase}`;

  // ── Velocity bars (animated activity indicator) ────────────────────────────
  updateVelocityBars(angle, ex, phase);

  // ── Range bar cursor ───────────────────────────────────────────────────────
  updateRangeBar(angle, inRange);

  // ── FPS / camera status ────────────────────────────────────────────────────
  document.getElementById("fpsBadge").textContent = `${fps.toFixed(1)} fps`;
  const camEl = document.getElementById("camIndicator");
  camEl.classList.toggle("ok", cameraOk);
  camEl.title = cameraOk ? "Camera connected" : "Demo mode (no camera)";

  const footerEl = document.getElementById("videoFooter");
  footerEl.textContent = cameraOk
    ? `${Object.keys(d.angles || {}).length} JOINTS TRACKED`
    : "DEMO MODE — NO CAMERA";

  // ── Angle history (only record when active) ────────────────────────────────
  if (d.active && angle > 0) {
    App.angleHistory.push(angle);
    if (App.angleHistory.length > 180) App.angleHistory.shift();

    // Refresh Analysis tab elements
    updateAnalysisStats(angle, inRange);
    drawChart();
  }

  // ── All-joints table (Analysis tab) ───────────────────────────────────────
  if (d.angles && Object.keys(d.angles).length) {
    updateJointsTable(d.angles, ex);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Angle Meter
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Updates the circular SVG arc gauge.
 *
 * The SVG circle has circumference = 2π × r = 2π × 64 ≈ 402.1
 * stroke-dasharray = 402.1 (full circle is visible)
 * stroke-dashoffset controls how much is "erased" from the end:
 *   offset = circumference × (1 – angle/180)
 *   → 0° gives full offset (nothing shown)
 *   → 180° gives offset 0 (full arc shown)
 */
function updateAngleMeter(angle, inRange) {
  const arc    = document.getElementById("meterArc");
  const valEl  = document.getElementById("meterAngleVal");
  const ex     = App.activeExercise;
  const CIRCUM = 2 * Math.PI * 64;   // r=64 in the SVG viewBox

  const pct    = Math.max(0, Math.min(1, angle / 180));
  const offset = CIRCUM * (1 - pct);

  arc.style.strokeDashoffset = offset;

  const colour = inRange ? ex.color : (angle > 0 ? "#f72585" : ex.color);
  arc.style.stroke = colour;
  arc.style.filter = `drop-shadow(0 0 8px ${colour})`;

  valEl.textContent = angle > 0 ? `${angle}°` : "—";
  valEl.style.color = colour;

  // ── Target zone arc ──────────────────────────────────────────────────────
  // Shows a shaded band on the gauge corresponding to the target ROM.
  const tgtArc = document.getElementById("meterTarget");
  const minPct = ex.target_min / 180;
  const maxPct = ex.target_max / 180;
  const tgtLen = (maxPct - minPct) * CIRCUM;
  const tgtOff = CIRCUM * (1 - maxPct);
  tgtArc.style.strokeDasharray  = `${tgtLen} ${CIRCUM - tgtLen}`;
  tgtArc.style.strokeDashoffset = tgtOff;
  tgtArc.style.stroke = ex.color;
}

// ─────────────────────────────────────────────────────────────────────────────
// Feedback
// ─────────────────────────────────────────────────────────────────────────────

function updateFeedback(message, inRange, angle, ex) {
  const card = document.getElementById("feedbackCard");
  document.getElementById("feedbackText").textContent = message;

  card.className = "feedback-card";
  if (angle <= 0) return;
  if (!inRange && angle < ex.target_min) card.className += " warn";
  else if (!inRange)                      card.className += " error";
}

// ─────────────────────────────────────────────────────────────────────────────
// Range Bar
// ─────────────────────────────────────────────────────────────────────────────

function updateRangeBar(angle, inRange) {
  const ex    = App.activeExercise;
  const zone  = document.getElementById("rangeZone");
  const thumb = document.getElementById("rangeThumb");

  const minPct = (ex.target_min / 180) * 100;
  const maxPct = (ex.target_max / 180) * 100;
  zone.style.left  = `${minPct}%`;
  zone.style.width = `${maxPct - minPct}%`;

  const tPct = Math.max(0, Math.min(100, (angle / 180) * 100));
  thumb.style.left       = `${tPct}%`;
  thumb.style.background = inRange ? ex.color : "#f72585";
  thumb.style.boxShadow  = `0 0 10px ${inRange ? ex.color : "#f72585"}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Rep Counter
// ─────────────────────────────────────────────────────────────────────────────

function renderRepDots(reps) {
  const container = document.getElementById("repDots");
  container.innerHTML = "";
  const goal = App.goalReps;
  for (let i = 0; i < goal; i++) {
    const d = document.createElement("div");
    d.className = "rdot";
    if (i < reps)      d.classList.add("done");
    if (i === reps - 1) d.classList.add("fresh");
    container.appendChild(d);
  }
  // Remove "fresh" highlight after animation
  setTimeout(() => {
    container.querySelectorAll(".rdot.fresh").forEach(d => d.classList.remove("fresh"));
  }, 400);
}

function pulseRepCounter(reps) {
  const el = document.getElementById("repBig");
  el.textContent = reps;
  el.classList.add("pulse");
  setTimeout(() => el.classList.remove("pulse"), 180);
}

function updateRepProgress(reps) {
  const pct = Math.min(100, (reps / App.goalReps) * 100);
  document.getElementById("repProgressFill").style.width = `${pct}%`;
}

function updateGoal(val) {
  const n = Math.max(1, parseInt(val) || 10);
  App.goalReps = n;
  document.getElementById("repGoalLabel").textContent = n;
  document.getElementById("kpiRepsSub").textContent   = `goal: ${n}`;
  renderRepDots(App.prevRepCount);
}

// ─────────────────────────────────────────────────────────────────────────────
// Velocity Bars (animated activity widget)
// ─────────────────────────────────────────────────────────────────────────────

let _vbarSeed = 0;
function updateVelocityBars(angle, ex, phase) {
  _vbarSeed++;
  const bars = document.querySelectorAll(".vbar");
  bars.forEach((bar, i) => {
    let h;
    if (phase === "up") {
      h = 30 + 70 * Math.abs(Math.sin(_vbarSeed * 0.3 + i * 0.8));
    } else if (phase === "down") {
      h = 15 + 40 * Math.abs(Math.sin(_vbarSeed * 0.2 + i * 1.1));
    } else {
      h = 8 + 12 * Math.abs(Math.sin(i * 1.3));
    }
    bar.style.height     = `${h}%`;
    bar.style.background = phase === "up"
      ? App.accentColor
      : phase === "down"
      ? "#f72585"
      : "rgba(255,255,255,0.12)";
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// ROM Coverage
// ─────────────────────────────────────────────────────────────────────────────

function computeROMPct(ex) {
  const h = App.angleHistory;
  if (!h.length) return 0;
  const achieved = Math.max(...h) - Math.min(...h);
  const target   = Math.max(ex.target_max - ex.target_min, 1);
  return Math.min(100, Math.round(achieved / target * 100));
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart
// ─────────────────────────────────────────────────────────────────────────────

function initChart() {
  const canvas = document.getElementById("angleChart");
  App.chartCtx = canvas.getContext("2d");
}

function drawChart() {
  const canvas = document.getElementById("angleChart");
  const ctx    = App.chartCtx;
  if (!ctx || !App.activeExercise) return;

  const data = App.angleHistory;
  const ex   = App.activeExercise;

  // Resize to physical pixels
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width  = rect.width  - 16;
  canvas.height = rect.height - 16;
  const W = canvas.width, H = canvas.height;
  if (W <= 0 || H <= 0) return;

  ctx.clearRect(0, 0, W, H);
  if (data.length < 2) return;

  const minV = 0, maxV = 180;
  const toX  = i => (i / (data.length - 1)) * W;
  const toY  = v => H - ((v - minV) / (maxV - minV)) * (H - 14) - 7;

  // ── Target zone shading ───────────────────────────────────────────────────
  const yTop = toY(ex.target_max);
  const yBot = toY(ex.target_min);
  ctx.fillStyle = `${ex.color}12`;
  ctx.fillRect(0, yTop, W, yBot - yTop);

  // Dashed boundary lines
  ctx.setLineDash([3, 4]);
  ctx.strokeStyle = `${ex.color}28`;
  ctx.lineWidth = 1;
  [ex.target_min, ex.target_max].forEach(v => {
    const y = toY(v);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  });
  ctx.setLineDash([]);

  // ── Area fill ─────────────────────────────────────────────────────────────
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, `${ex.color}45`);
  grad.addColorStop(1, `${ex.color}00`);

  ctx.beginPath();
  ctx.moveTo(toX(0), toY(data[0]));
  data.forEach((v, i) => ctx.lineTo(toX(i), toY(v)));
  ctx.lineTo(toX(data.length - 1), H);
  ctx.lineTo(0, H);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // ── Main line ─────────────────────────────────────────────────────────────
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(data[0]));
  data.forEach((v, i) => ctx.lineTo(toX(i), toY(v)));
  ctx.strokeStyle = ex.color;
  ctx.lineWidth   = 2;
  ctx.shadowBlur  = 7;
  ctx.shadowColor = ex.color;
  ctx.stroke();
  ctx.shadowBlur  = 0;

  // ── Current value dot ─────────────────────────────────────────────────────
  const lx = toX(data.length - 1);
  const ly = toY(data[data.length - 1]);
  ctx.beginPath();
  ctx.arc(lx, ly, 5, 0, Math.PI * 2);
  ctx.fillStyle  = ex.color;
  ctx.shadowBlur = 12;
  ctx.shadowColor= ex.color;
  ctx.fill();
  ctx.shadowBlur = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Analysis Stats
// ─────────────────────────────────────────────────────────────────────────────

function updateAnalysisStats(currentAngle, inRange) {
  const h = App.angleHistory;
  if (!h.length) return;

  const maxV = Math.max(...h);
  const minV = Math.min(...h);
  const avgV = Math.round(h.reduce((a, b) => a + b, 0) / h.length);

  document.getElementById("stMax").textContent     = `${maxV}°`;
  document.getElementById("stMin").textContent     = `${minV}°`;
  document.getElementById("stRange").textContent   = `${maxV - minV}°`;
  document.getElementById("stAvg").textContent     = `${avgV}°`;
  document.getElementById("stCurrent").textContent = `${currentAngle}°`;

  const inRangeEl = document.getElementById("stInRange");
  inRangeEl.textContent = currentAngle > 0 ? (inRange ? "YES" : "NO") : "—";
  inRangeEl.style.color = inRange ? "var(--cyan)" : currentAngle > 0 ? "var(--pink)" : "var(--muted)";
}

function updateJointsTable(angles, activeEx) {
  const table = document.getElementById("jointsTable");
  const names = Object.keys(angles);

  // Keep header row, replace data rows
  const header = table.querySelector(".jt-head");
  table.innerHTML = "";
  if (header) table.appendChild(header);
  else {
    const h = document.createElement("div");
    h.className = "jt-row jt-head";
    h.innerHTML = "<span>JOINT</span><span>ANGLE</span><span>STATUS</span>";
    table.appendChild(h);
  }

  names.forEach(name => {
    const val = angles[name];
    const row = document.createElement("div");
    row.className = "jt-row jt-body";

    let statusClass = "jt-na", statusText = "—";
    if (val > 0) {
      statusClass = "jt-ok";
      statusText  = "OK";
    } else {
      statusClass = "jt-na";
      statusText  = "LOW VIS";
    }

    row.innerHTML = `
      <span>${name.replace(/_/g, " ").toUpperCase()}</span>
      <span class="${val > 0 ? "jt-ok" : "jt-na"}">${val > 0 ? val + "°" : "—"}</span>
      <span class="${statusClass}">${statusText}</span>
    `;
    table.appendChild(row);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Guide Tab
// ─────────────────────────────────────────────────────────────────────────────

function renderGuide(ex) {
  const el = document.getElementById("guideContent");
  el.innerHTML = `
    <div class="guide-card">
      <div class="guide-title" style="color:${ex.color}">${ex.name}</div>
      <div class="guide-sub">${ex.category?.toUpperCase()} · ${ex.joint}</div>

      <div class="guide-instruction">${ex.instruction}</div>

      <div class="guide-row">
        <div class="guide-field">
          <div class="guide-field-lbl">TARGET ROM</div>
          <div class="guide-field-val" style="color:${ex.color}">${ex.target_min}° – ${ex.target_max}°</div>
        </div>
        <div class="guide-field">
          <div class="guide-field-lbl">REP GOAL</div>
          <div class="guide-field-val">${ex.goal_reps} reps per set</div>
        </div>
        <div class="guide-field">
          <div class="guide-field-lbl">PRIMARY MUSCLES</div>
          <div class="guide-field-val" style="font-size:11px">${ex.muscles || "—"}</div>
        </div>
        <div class="guide-field">
          <div class="guide-field-lbl">REP TYPE</div>
          <div class="guide-field-val">${ex.rep_trigger === "peak" ? "Peak & return" : "Continuous cycle"}</div>
        </div>
      </div>

      ${ex.notes ? `<div class="guide-notes">📋 ${ex.notes}</div>` : ""}
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// Progress Tab
// ─────────────────────────────────────────────────────────────────────────────

async function refreshProgressTab() {
  try {
    const res  = await fetch("/api/session/log");
    const data = await res.json();
    renderMilestones(data.milestones || []);
    renderSummary(data.summary || {});
  } catch (e) {
    // Silently ignore — backend may not be ready
  }
}

function renderMilestones(milestones) {
  const list = document.getElementById("milestoneList");
  if (!milestones.length) {
    list.innerHTML = '<div class="empty-msg mono">Complete reps to see milestones</div>';
    return;
  }
  list.innerHTML = milestones.map(m => `
    <div class="m-row">
      <span class="m-time mono">${m.time}</span>
      <span class="m-rep  mono">REP ${m.rep}</span>
      <span class="m-angle mono">${m.angle}°</span>
      <span class="m-elapsed mono">${m.elapsed_s}s</span>
    </div>
  `).join("");
  list.scrollTop = list.scrollHeight;
}

function renderSummary(s) {
  document.getElementById("sumReps").textContent    = s.total_reps    ?? "0";
  document.getElementById("sumTime").textContent    = fmtTime(s.session_time ?? 0);
  document.getElementById("sumRom").textContent     = s.rom_achieved != null ? `${s.rom_achieved}°` : "—";
  document.getElementById("sumCadence").textContent = s.avg_rep_time  ? `${s.avg_rep_time}s` : "—";
}

// ─────────────────────────────────────────────────────────────────────────────
// Session Controls
// ─────────────────────────────────────────────────────────────────────────────

async function startSession() {
  await fetch("/api/session/start", { method: "POST" });
  App.isRunning  = true;
  App.sessionStart = Date.now();

  document.getElementById("btnStart").classList.add("hidden");
  document.getElementById("btnStop").classList.remove("hidden");

  const dot   = document.getElementById("statusDot");
  const label = document.getElementById("statusLabel");
  dot.classList.add("on");
  label.classList.add("on");
  label.textContent = "ANALYZING";

  App.timerHandle = setInterval(tickTimer, 1000);
}

async function stopSession() {
  await fetch("/api/session/stop", { method: "POST" });
  App.isRunning = false;

  document.getElementById("btnStart").classList.remove("hidden");
  document.getElementById("btnStop").classList.add("hidden");

  document.getElementById("statusDot").classList.remove("on");
  const label = document.getElementById("statusLabel");
  label.classList.remove("on");
  label.textContent = "STANDBY";

  clearInterval(App.timerHandle);
  await refreshProgressTab();
}

async function resetSession() {
  await stopSession();
  await fetch("/api/session/reset", { method: "POST" });

  App.angleHistory = [];
  App.prevRepCount = 0;

  document.getElementById("repBig").textContent     = "0";
  document.getElementById("kpiRepsVal").textContent  = "0";
  document.getElementById("kpiRomVal").textContent   = "0%";
  document.getElementById("kpiTimeVal").textContent  = "00:00";
  document.getElementById("sessionTimerHdr").textContent = "00:00";
  document.getElementById("feedbackText").textContent    = "Press START to begin";

  renderRepDots(0);
  updateRepProgress(0);
  drawChart();
  await refreshProgressTab();
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab Navigation
// ─────────────────────────────────────────────────────────────────────────────

function switchTab(name) {
  ["monitor","analysis","progress","guide"].forEach(t => {
    document.getElementById(`tab-${t}`).classList.toggle("active", t === name);
    document.getElementById(`pane-${t}`).classList.toggle("hidden", t !== name);
  });
  if (name === "analysis") { drawChart(); }
  if (name === "progress") { refreshProgressTab(); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Timer
// ─────────────────────────────────────────────────────────────────────────────

function tickTimer() {
  if (!App.sessionStart) return;
  const elapsed = Math.floor((Date.now() - App.sessionStart) / 1000);
  const fmt = fmtTime(elapsed);
  document.getElementById("sessionTimerHdr").textContent = fmt;
  document.getElementById("kpiTimeVal").textContent      = fmt;
}

// ─────────────────────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────────────────────

function fmtTime(seconds) {
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2,"0")}:${String(s % 60).padStart(2,"0")}`;
}
