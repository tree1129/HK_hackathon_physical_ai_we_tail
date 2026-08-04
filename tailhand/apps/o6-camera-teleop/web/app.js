const CHANNEL_LABELS = {
  thumb_flexion: "拇指弯曲",
  thumb_abduction: "拇指侧摆",
  index_flexion: "食指弯曲",
  middle_flexion: "中指弯曲",
  ring_flexion: "无名指弯曲",
  pinky_flexion: "小指弯曲",
};

const STATE_LABELS = {
  DISARMED: "未布防",
  ARMED: "识别中",
  CLOSING: "正在抓取",
  HOLDING: "保持抓取",
  WAITING_HAND: "等待人手",
  TRACKING: "手势跟随中",
  HOLDING_LAST: "短暂丢手",
  PAUSED_LOST: "丢手已停发",
};

const DEPTH_LABELS = {
  DEPTH_UNAVAILABLE: "深度不可用",
  OUTSIDE_OPEN_ZONE: "目标在 5 cm 外",
  PREGRASP_OPEN: "预抓取 / 保持张开",
  CONTACT_CONFIRMED: "接触面已确认",
};

const channelList = document.querySelector("#channelList");
const toast = document.querySelector("#toast");
let lastEvent = "";
let toastTimer = null;
let depthFeedActive = false;

for (const [name, label] of Object.entries(CHANNEL_LABELS)) {
  const row = document.createElement("div");
  row.className = "channel-row";
  row.dataset.channel = name;
  row.innerHTML = `
    <span class="channel-name" title="${name}">${label}</span>
    <span class="channel-bar"><span></span></span>
    <strong class="channel-value">---</strong>
  `;
  channelList.append(row);
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2800);
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function setDepthFeedActive(active) {
  const feed = document.querySelector("#depthFeed");
  const currentSource = feed.getAttribute("src");
  if (active && currentSource !== feed.dataset.src) {
    feed.src = feed.dataset.src;
  } else if (!active && currentSource) {
    feed.removeAttribute("src");
  }
  depthFeedActive = active;
}

function handLabel(handedness) {
  if (handedness === "Left") return "左手";
  if (handedness === "Right") return "右手";
  return "人手";
}

function updateStatus(status) {
  const mode = status.mode || "object-grasp";
  const handMode = mode === "hand-follow";
  const state = status.state || "DISARMED";
  const stopped = Boolean(status.emergency_stopped);
  const ready = Boolean(status.ready);
  const handDetected = Boolean(status.hand_detected);
  const followEnabled = Boolean(status.follow_enabled);
  const trackingState = status.tracking_state || "WAITING_HAND";
  const deviceHand = status.hand_type || "left";
  const recameraSource = status.vision_source === "recamera";
  const lidarSource = status.vision_source === "iphone-lidar";
  const macSource = !recameraSource && !lidarSource;
  const showLidar = !handMode && lidarSource;
  const showRecamera = !handMode && recameraSource;
  const iphoneConnected = Boolean(status.iphone_connected);
  const recameraConnected = Boolean(status.recamera_connected);
  const recameraFps = finiteNumber(status.recamera_fps);
  const recameraAge = finiteNumber(status.recamera_frame_age_ms);
  const depthCalibrated = Boolean(status.depth_calibrated);
  const depthRatioValue = finiteNumber(status.depth_valid_ratio);
  const depthValidRatio = Math.max(0, Math.min(1, depthRatioValue || 0));
  const signedDistance = finiteNumber(status.signed_distance_mm);
  const contactDepth = finiteNumber(status.contact_depth_mm);
  const depthFps = finiteNumber(status.depth_fps);
  const depthLatency = finiteNumber(status.depth_latency_ms);
  const depthPhaseKey = typeof status.depth_phase === "string" ? status.depth_phase : "DEPTH_UNAVAILABLE";
  const depthPhaseLabel = DEPTH_LABELS[depthPhaseKey] || "等待深度";
  const hasTarget = Boolean(status.target && status.target !== "无");
  const hasValidDepthTarget = iphoneConnected && depthValidRatio > 0 && hasTarget;
  const stateLabel = document.querySelector("#stateLabel");
  stateLabel.textContent = stopped ? "急停锁定" : (STATE_LABELS[state] || state);
  stateLabel.className = `state-label ${stopped ? "stopped" : state.toLowerCase()}`;

  const handModeButton = document.querySelector("#handModeButton");
  const objectModeButton = document.querySelector("#objectModeButton");
  handModeButton.classList.toggle("selected", handMode);
  objectModeButton.classList.toggle("selected", !handMode);
  handModeButton.setAttribute("aria-pressed", String(handMode));
  objectModeButton.setAttribute("aria-pressed", String(!handMode));
  handModeButton.disabled = stopped || !ready || handMode;
  objectModeButton.disabled = stopped || !ready || !handMode;
  document.querySelector("#handActions").hidden = !handMode;
  document.querySelector("#objectActions").hidden = handMode;

  const macSourceButton = document.querySelector("#macSourceButton");
  const recameraSourceButton = document.querySelector("#recameraSourceButton");
  const iphoneSourceButton = document.querySelector("#iphoneSourceButton");
  macSourceButton.classList.toggle("selected", macSource);
  recameraSourceButton.classList.toggle("selected", recameraSource);
  iphoneSourceButton.classList.toggle("selected", lidarSource);
  macSourceButton.setAttribute("aria-pressed", String(macSource));
  recameraSourceButton.setAttribute("aria-pressed", String(recameraSource));
  iphoneSourceButton.setAttribute("aria-pressed", String(lidarSource));
  macSourceButton.disabled = stopped || !ready || handMode || macSource;
  recameraSourceButton.disabled = stopped || !ready || handMode || recameraSource;
  iphoneSourceButton.disabled = stopped || !ready || handMode || lidarSource;
  document.querySelector("#lidarActions").hidden = !showLidar;
  document.querySelector("#lidarDiagnostics").hidden = !showLidar;
  document.querySelector("#recameraActions").hidden = !showRecamera;
  document.querySelector("#recameraDiagnostics").hidden = !showRecamera;
  document.querySelector("#automaticGraspActions").hidden = handMode;
  document.querySelector("#depthPanel").hidden = !showLidar;
  document.querySelector("#streamGrid").classList.toggle("single-source", !showLidar);
  setDepthFeedActive(showLidar);

  setText(
    "#cameraTitle",
    handMode ? "手势识别" : (showLidar ? "iPhone 腕部视角" : (showRecamera ? "reCamera 腕部视角" : "Mac 摄像头")),
  );
  setText("#rgbSourceLabel", showLidar ? "iPhone RGB" : (showRecamera ? "reCamera RTSP" : "Mac 摄像头"));
  setText("#recameraState", recameraConnected ? "已连接" : "等待连接");
  setText(
    "#recameraStreamState",
    `${Math.max(0, recameraFps || 0).toFixed(1)} FPS / ${recameraAge == null ? "---" : `${Math.max(0, recameraAge).toFixed(0)} ms`}`,
  );
  setText("#pairingCode", String(status.pairing_code || "------"));
  setText("#iphoneState", iphoneConnected ? "已连接" : "等待连接");
  setText("#iphoneDevice", status.iphone_device || "---");
  setText(
    "#depthStreamState",
    `${Math.max(0, depthFps || 0).toFixed(1)} FPS / ${depthLatency == null ? "---" : `${Math.max(0, depthLatency).toFixed(0)} ms`}`,
  );
  setText("#depthValidRatio", `${Math.round(depthValidRatio * 100)}%`);
  setText("#contactDepth", depthCalibrated && contactDepth != null ? `${contactDepth.toFixed(1)} mm` : "未标定");
  const distanceText = signedDistance == null ? "---" : `${signedDistance >= 0 ? "+" : ""}${signedDistance.toFixed(1)} mm`;
  setText("#depthDistance", distanceText);
  setText("#diagnosticDepthDistance", distanceText);
  setText("#depthPhase", depthPhaseLabel);
  setText("#diagnosticDepthPhase", depthPhaseLabel);
  document.querySelector("#depthPhase").className = `depth-phase ${depthPhaseKey.toLowerCase()}`;

  const leftHandButton = document.querySelector("#leftHandButton");
  const rightHandButton = document.querySelector("#rightHandButton");
  const leftDevice = deviceHand === "left";
  leftHandButton.classList.toggle("selected", leftDevice);
  rightHandButton.classList.toggle("selected", !leftDevice);
  leftHandButton.setAttribute("aria-pressed", String(leftDevice));
  rightHandButton.setAttribute("aria-pressed", String(!leftDevice));
  leftHandButton.disabled = stopped || !ready || leftDevice;
  rightHandButton.disabled = stopped || !ready || !leftDevice;

  const modeBadge = document.querySelector("#modeBadge");
  if (status.backend === "dry-run-fallback") {
    modeBadge.textContent = "真机失败 / 已回退模拟";
    modeBadge.className = "badge fallback";
  } else if (status.dry_run) {
    modeBadge.textContent = "模拟模式";
    modeBadge.className = "badge simulation";
  } else {
    modeBadge.textContent = "真机模式";
    modeBadge.className = "badge real";
  }

  const connectionDot = document.querySelector("#connectionDot");
  connectionDot.className = `status-dot ${ready ? "online" : "danger"}`;
  setText("#connectionText", ready ? "视觉运行层在线" : "视觉运行层异常");
  setText("#fpsValue", Number(status.fps || 0).toFixed(1));
  setText("#objectCount", handMode ? (handDetected ? 1 : 0) : (status.objects || 0));
  setText("#metricUnit", handMode ? "只手" : "物品");
  setText("#handState", handDetected ? `已识别${handLabel(status.handedness)}` : "未检测到手");
  setText("#progressLabel", handMode ? "手部识别" : "目标稳定度");
  document.querySelector(".progress-track").setAttribute(
    "aria-label",
    handMode ? "手部识别" : "目标稳定度",
  );
  setText("#diagnosticLabel", handMode ? "手势输入" : "抓取目标");
  if (handMode) {
    const handDetail = handDetected
      ? `${handLabel(status.handedness)} / ${Number(status.hand_score || 0).toFixed(2)}`
      : "无";
    setText("#targetLabel", `输入：${handDetail}`);
    setText("#diagnosticTarget", handDetail);
    setText("#stableText", handDetected ? "已识别" : "等待中");
  } else {
    setText("#targetLabel", `目标：${status.target || "无"}`);
    setText("#diagnosticTarget", status.target ? `${status.target} / ${Number(status.target_score || 0).toFixed(2)}` : "无");
    setText("#stableText", `${status.stable_count || 0} / ${status.stable_frames || 0}`);
  }
  const stableMax = Math.max(1, Number(status.stable_frames || 1));
  document.querySelector("#stableProgress").style.width = `${Math.min(100, Number(status.stable_count || 0) / stableMax * 100)}%`;

  const safetyDot = document.querySelector("#safetyDot");
  let safetyText = handMode ? "跟随未启用" : "区域安全，可布防";
  let safetyClass = "online";
  if (stopped) {
    safetyText = "急停锁定，停止下发";
    safetyClass = "danger";
  } else if (showLidar && !iphoneConnected && (state === "CLOSING" || state === "HOLDING")) {
    safetyText = "深度断流，保持当前姿态";
    safetyClass = "danger";
  } else if (showLidar && !iphoneConnected) {
    safetyText = "iPhone LiDAR 未连接";
    safetyClass = "danger";
  } else if (showLidar && !depthCalibrated) {
    safetyText = "等待 0 cm 接触面标定";
    safetyClass = "warning";
  } else if (showLidar && depthPhaseKey === "DEPTH_UNAVAILABLE") {
    safetyText = "深度不可用，禁止闭合";
    safetyClass = "danger";
  } else if (showRecamera && !recameraConnected) {
    safetyText = "reCamera RTSP 未连接";
    safetyClass = "danger";
  } else if (!status.camera_ok) {
    safetyText = "摄像头不可用";
    safetyClass = "warning";
  } else if (handMode && !followEnabled) {
    safetyText = handDetected ? "已识别人手，跟随未启用" : "等待人手，跟随未启用";
    safetyClass = "warning";
  } else if (handMode && trackingState === "TRACKING") {
    safetyText = "手势跟随中，正在限速下发";
  } else if (handMode && trackingState === "HOLDING_LAST") {
    safetyText = "短暂丢手，保持最后姿态";
    safetyClass = "warning";
  } else if (handMode && trackingState === "PAUSED_LOST") {
    safetyText = "丢手超过时限，已经停止下发";
    safetyClass = "danger";
  } else if (handMode) {
    safetyText = "跟随已启用，等待识别人手";
    safetyClass = "warning";
  } else if (status.hand_blocked) {
    safetyText = "手进入抓取区域，禁止闭合";
    safetyClass = "danger";
  } else if (showRecamera && state === "DISARMED") {
    safetyText = "可布防自动抓取，或手动保守握合";
  } else if (state === "CLOSING") {
    safetyText = "正在按限速闭合";
    safetyClass = "warning";
  } else if (state === "HOLDING") {
    safetyText = "已保持抓取，等待张开";
  } else if (state === "ARMED") {
    if (showLidar && depthPhaseKey === "OUTSIDE_OPEN_ZONE") {
      safetyText = "目标仍在 5 cm 外";
    } else if (showLidar && depthPhaseKey === "PREGRASP_OPEN") {
      safetyText = "目标接近，保持张开";
      safetyClass = "warning";
    } else if (showLidar && depthPhaseKey === "CONTACT_CONFIRMED") {
      safetyText = "接触面已确认，等待稳定计数";
    } else {
      safetyText = "已布防，等待稳定目标";
    }
  }
  safetyDot.className = `status-dot ${safetyClass}`;
  setText("#safetyText", safetyText);
  setText("#commandCount", `${status.commands || 0} 条指令`);
  setText("#channelTitle", handMode && !followEnabled ? "六维映射预览" : "O6 六维位置");
  setText("#backendValue", status.backend || "unknown");
  setText("#hardwareValue", status.connected ? "已连接" : "未连接");
  setText("#deviceValue", deviceHand === "left" ? "左手 / 0x28" : "右手 / 0x27");
  setText(
    "#cameraValue",
    status.camera_ok ? (showLidar ? "iPhone RGB 正常" : (showRecamera ? "reCamera RTSP 正常" : "正常")) : "不可用",
  );
  setText("#eventMessage", status.last_event || "等待事件");

  const fallback = document.querySelector("#fallbackReason");
  const reason = status.fallback_reason || status.last_error;
  fallback.hidden = !reason;
  fallback.textContent = reason ? `诊断：${reason}` : "";
  setText(
    "#cameraErrorTitle",
    showLidar ? "iPhone RGB 画面不可用" : (showRecamera ? "reCamera RTSP 画面不可用" : "摄像头画面不可用"),
  );
  setText(
    "#cameraErrorDetail",
    showLidar
      ? "等待 iPhone RGB 数据流。"
      : (showRecamera
        ? "检查 reCamera Stream 节点、端口 554 和 config.yaml 中的 RTSP 地址。"
        : "检查 macOS 摄像头权限，或确认没有其他程序占用摄像头。"),
  );
  document.querySelector("#cameraError").hidden = Boolean(status.camera_ok);
  document.querySelector("#depthError").hidden = !showLidar || (iphoneConnected && (depthFps || 0) > 0);

  const pose = Array.isArray(status.pose) ? status.pose : [];
  const channels = Array.isArray(status.channels) ? status.channels : Object.keys(CHANNEL_LABELS);
  channels.forEach((name, index) => {
    const row = document.querySelector(`[data-channel="${name}"]`);
    if (!row) return;
    const value = Math.max(0, Math.min(255, Number(pose[index] || 0)));
    row.querySelector(".channel-value").textContent = String(Math.round(value)).padStart(3, "0");
    row.querySelector(".channel-bar span").style.width = `${value / 255 * 100}%`;
  });

  document.querySelector("#followEnableButton").disabled = stopped || !handMode || followEnabled || !ready;
  document.querySelector("#followPauseButton").disabled = stopped || !handMode || !followEnabled || !ready;
  document.querySelector("#calibrateDepthButton").disabled = stopped || !showLidar || !ready
    || state !== "DISARMED" || !hasValidDepthTarget;
  document.querySelector("#clearDepthButton").disabled = stopped || !showLidar || !ready
    || state !== "DISARMED" || !depthCalibrated;
  document.querySelector("#armButton").disabled = stopped || handMode || state !== "DISARMED" || !ready
    || (showLidar && (!iphoneConnected || !depthCalibrated))
    || (showRecamera && (!recameraConnected || !status.camera_ok
      || status.backend === "dry-run-fallback"));
  document.querySelector("#disarmButton").disabled = stopped || handMode || state !== "ARMED" || !ready;
  document.querySelector("#manualGraspButton").disabled = stopped || !showRecamera || !ready
    || !status.camera_ok || !recameraConnected || state !== "DISARMED"
    || status.backend === "dry-run-fallback";
  document.querySelector("#openButton").disabled = !ready;
  document.querySelector("#stopButton").disabled = stopped || !ready;

  if (status.last_event && status.last_event !== lastEvent) {
    lastEvent = status.last_event;
    if (status.ready) showToast(lastEvent);
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    updateStatus(await response.json());
  } catch (error) {
    document.querySelector("#connectionDot").className = "status-dot danger";
    setText("#connectionText", "无法连接本地运行层");
    setText("#eventMessage", `状态接口错误：${error.message}`);
  }
}

async function sendAction(action, button) {
  button.disabled = true;
  try {
    const response = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const result = await response.json();
    if (!response.ok || !result.accepted) throw new Error(result.error || `HTTP ${response.status}`);
    showToast("指令已进入安全队列");
    window.setTimeout(refreshStatus, 80);
  } catch (error) {
    showToast(`指令失败：${error.message}`);
  } finally {
    window.setTimeout(() => { button.disabled = false; }, 250);
  }
}

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => sendAction(button.dataset.action, button));
});

document.querySelector("#cameraFeed").addEventListener("error", () => {
  document.querySelector("#cameraError").hidden = false;
});

document.querySelector("#depthFeed").addEventListener("load", () => {
  document.querySelector("#depthError").hidden = true;
});

document.querySelector("#depthFeed").addEventListener("error", () => {
  if (depthFeedActive) document.querySelector("#depthError").hidden = false;
});

refreshStatus();
window.setInterval(refreshStatus, 250);
