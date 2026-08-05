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
  WAITING_MODE: "等待切换",
};

const DEPTH_LABELS = {
  DEPTH_UNAVAILABLE: "深度不可用",
  OUTSIDE_OPEN_ZONE: "目标在 5 cm 外",
  PREGRASP_OPEN: "预抓取 / 保持张开",
  CONTACT_CONFIRMED: "接触面已确认",
};

const REAL_ACTIONS = new Set([
  "hand-left",
  "hand-right",
  "mode-hand",
  "mode-object",
  "source-mac-camera",
  "source-mobile-camera",
  "source-iphone-lidar",
  "depth-calibrate-contact",
  "depth-clear-calibration",
  "follow-enable",
  "follow-pause",
  "fist",
  "arm",
  "disarm",
  "open",
  "stop",
]);

const PAGE_META = {
  home: ["控制中心", "LINKERHAND CONTROL"],
  gesture: ["手势控制", "DIRECT CONTROL"],
  agent: ["Agent 与物品抓取", "OBJECT + AGENT"],
  devices: ["设备与校准", "DEVICES"],
  history: ["任务记录", "HISTORY"],
  settings: ["设置", "SETTINGS"],
};

const HISTORY = {
  gesture: ["手势同步测试：连续抓握", "今天 13:48 · 手势控制 · 32 秒", "手势跟随", "正常停止输出"],
  object: ["识别并抓取桌面物品", "今天 11:26 · 物品抓取 · 8.7 秒", "物品抓取", "完成后安全张开"],
  lost: ["目标丢失安全停止", "昨天 18:05 · 安全事件 · 自动停止", "物品抓取", "目标丢失后停止"],
};

const state = { page: "home", online: false, status: null, lastEvent: "" };
const mobileCamera = { stream: null, active: false, facingMode: "environment", timer: null };
const mobileCameraClient = navigator.maxTouchPoints > 0 && window.matchMedia("(pointer: coarse)").matches;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function configureGestureCameraControls() {
  const mobileSourceButton = $("#gestureMobileSourceButton");
  const mobileControls = $("#mobileCameraControls");
  mobileSourceButton.hidden = !mobileCameraClient;
  mobileControls.hidden = !mobileCameraClient;
  $("#gestureSourceSelector").classList.toggle("single", !mobileCameraClient);
}

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}

function setBadge(node, label, tone = "neutral") {
  if (!node) return;
  node.textContent = label;
  node.className = `badge ${tone}`;
}

function setDot(node, tone = "") {
  if (node) node.className = `status-dot${tone ? ` ${tone}` : ""}`;
}

function finiteNumber(value) {
  const number = Number(value);
  return value == null || value === "" || !Number.isFinite(number) ? null : number;
}

function showToast(title, message, tone = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${tone}`;
  toast.innerHTML = `<strong>${title}</strong><span>${message}</span>`;
  $("#toastRegion").append(toast);
  window.setTimeout(() => toast.remove(), 3000);
}

function handLabel(value) {
  if (value === "Left") return "左手";
  if (value === "Right") return "右手";
  return "人手";
}

function deviceLabel(value) {
  return value === "right" ? "右手 / 0x27" : "左手 / 0x28";
}

function setFeed(node, active) {
  if (!node) return;
  const source = node.dataset.src;
  if (active && node.getAttribute("src") !== source) node.setAttribute("src", source);
  if (!active && node.getAttribute("src")) node.removeAttribute("src");
}

function updateFeeds() {
  const lidar = state.status?.vision_source === "iphone-lidar";
  setFeed($("#gestureFeed"), state.page === "gesture");
  setFeed($("#agentFeed"), state.page === "agent");
  setFeed($("#depthFeed"), state.page === "agent" && lidar);
}

function setPage(page) {
  if (!PAGE_META[page]) return;
  state.page = page;
  $$(".page").forEach((node) => node.classList.toggle("active", node.id === `page-${page}`));
  $$('[data-page-target]').forEach((node) => node.classList.toggle("active", node.dataset.pageTarget === page));
  setText("#pageTitle", PAGE_META[page][0]);
  setText("#pageEyebrow", PAGE_META[page][1]);
  updateFeeds();
  updateMobilePrimary();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setOnline(online) {
  state.online = online;
  document.body.classList.toggle("offline", !online);
  if (!online) {
    setDot($("#sidebarConnectionDot"), "danger");
    setText("#sidebarDeviceText", "O6 离线");
    setText("#sidebarBackendText", "无法连接运行层");
    setText("#connectionText", "运行层离线");
    const safety = $("#safetyBadge");
    setDot($("i", safety), "danger");
    $("span", safety).textContent = "连接异常";
  }
  updateMobilePrimary();
}

function updateMobilePrimary() {
  const button = $("#mobilePrimaryAction");
  const status = state.status || {};
  button.className = "mobile-primary";
  button.dataset.action = "";
  button.disabled = false;
  if (state.page === "home") button.textContent = "进入手势控制";
  if (state.page === "gesture") {
    if (status.mode !== "hand-follow") {
      button.textContent = "切换至手势模式";
      button.dataset.action = "mode-hand";
    } else {
      button.textContent = status.follow_enabled ? "暂停跟随" : "启用跟随";
      button.dataset.action = status.follow_enabled ? "follow-pause" : "follow-enable";
    }
    button.disabled = !state.online || Boolean(status.emergency_stopped);
  }
  if (state.page === "agent") {
    button.classList.add("agent");
    button.textContent = "播放语音示例";
    button.disabled = false;
  }
  if (state.page === "devices") { button.classList.add("neutral"); button.textContent = "刷新设备状态"; }
  if (state.page === "history") { button.classList.add("neutral"); button.textContent = "查看最近记录"; }
  if (state.page === "settings") { button.classList.add("neutral"); button.textContent = "保存演示设置"; }
}

function backendBadge(status) {
  if (status.backend === "dry-run-fallback") return ["真机失败 / 模拟回退", "fallback"];
  if (status.dry_run) return ["模拟模式", "simulation"];
  return ["真机模式", "real"];
}

function renderGlobal(status) {
  const [modeText, modeTone] = backendBadge(status);
  setBadge($("#modeBadge"), modeText, modeTone);
  setDot($("#sidebarConnectionDot"), status.ready ? "online" : "danger");
  setText("#sidebarDeviceText", status.connected ? "O6 已连接" : (status.dry_run ? "O6 模拟连接" : "O6 未连接"));
  setText("#sidebarBackendText", status.backend || "unknown");
  setText("#connectionText", status.ready ? "视觉运行层在线" : "视觉运行层异常");
  let safetyText = "系统未布防";
  let safetyTone = "online";
  if (status.emergency_stopped) { safetyText = "急停锁定"; safetyTone = "danger"; }
  else if (!status.camera_ok) { safetyText = "摄像头异常"; safetyTone = "warning"; }
  else if (status.mode === "hand-follow" && status.follow_enabled) safetyText = "跟随已启用";
  else if (status.mode === "object-grasp" && status.state === "ARMED") { safetyText = "抓取已布防"; safetyTone = "warning"; }
  const safety = $("#safetyBadge");
  setDot($("i", safety), safetyTone);
  $("span", safety).textContent = safetyText;
  document.body.classList.toggle("emergency-locked", Boolean(status.emergency_stopped));
  $("#desktopEmergency").classList.toggle("locked", Boolean(status.emergency_stopped));
  setText("#desktopEmergency strong", status.emergency_stopped ? "急停已锁定" : "紧急停止");
}

function renderHome(status) {
  const ready = Boolean(status.ready);
  setDot($("#homeReadiness i"), ready ? "online" : "danger");
  setText("#homeReadiness span", ready ? "视觉运行层已连接，可进入控制" : "视觉运行层异常，控制已停用");
  setText("#homeMode", status.mode === "hand-follow" ? "手势跟随" : "物品抓取");
  setText("#homeCamera", status.camera_ok ? "正常" : "不可用");
  setText("#homeDevice", status.connected ? "真机" : (status.dry_run ? "模拟" : "未连接"));
  setText("#homeCommands", String(status.commands || 0));
  setText("#homeGestureState", status.mode === "hand-follow" ? (status.follow_enabled ? "跟随已启用" : "等待启用") : "可切换进入");
  setText("#homeLastEvent", status.last_event || "等待运行事件");
  setDot($("#homeBackendDot"), ready ? "online" : "danger");
  setText("#homeBackendDetail", status.backend || "unknown");
  setBadge($("#homeBackendBadge"), ready ? "在线" : "异常", ready ? "success" : "danger");
  setDot($("#homeO6Dot"), status.connected || status.dry_run ? "online" : "warning");
  setText("#homeO6Detail", `${deviceLabel(status.hand_type)} · ${status.backend || "unknown"}`);
  setBadge($("#homeO6Badge"), status.connected ? "已连接" : (status.dry_run ? "模拟" : "未连接"), status.connected ? "success" : (status.dry_run ? "simulation" : "warning"));
  setDot($("#homeCameraDot"), status.camera_ok ? "online" : "danger");
  setText("#homeCameraDetail", status.camera_ok ? `${Number(status.fps || 0).toFixed(1)} FPS` : "摄像头不可用");
  setBadge($("#homeCameraBadge"), status.camera_ok ? "正常" : "异常", status.camera_ok ? "success" : "danger");
  setDot($("#homeIphoneDot"), status.iphone_connected ? "online" : "warning");
  setText("#homeIphoneDetail", status.iphone_connected ? `${status.iphone_device || "iPhone"} · ${Number(status.depth_fps || 0).toFixed(1)} FPS` : "接收器在线，等待 iPhone");
  setBadge($("#homeIphoneBadge"), status.iphone_connected ? "已连接" : "待连接", status.iphone_connected ? "success" : "warning");
}

function renderGesture(status) {
  const tracking = status.tracking_state || "WAITING_HAND";
  const detected = Boolean(status.hand_detected);
  setText("#gestureFps", Number(status.fps || 0).toFixed(1));
  setText("#gestureHand", detected ? `已识别${handLabel(status.handedness)}` : "未检测到手");
  setText("#gestureStateLabel", status.emergency_stopped ? "急停锁定" : (STATE_LABELS[tracking] || tracking));
  setText("#gestureInputLabel", `输入：${detected ? `${handLabel(status.handedness)} / ${Number(status.hand_score || 0).toFixed(2)}` : "无"}`);
  setText("#gestureTracking", STATE_LABELS[tracking] || tracking);
  setText("#gestureCommandCount", `${status.commands || 0} 条指令`);
  setText("#gestureSafety", status.emergency_stopped ? "急停锁定，需重启运行器" : (status.follow_enabled ? "跟随已启用" : "跟随未启用"));
  setText("#gestureDetection", detected ? "已识别" : "等待中");
  setText("#gestureFollowStatus", status.follow_enabled ? "已启用" : "未启用");
  setText("#gestureDeviceHand", status.hand_type === "right" ? "右手" : "左手");
  setText("#gestureEvent", status.last_event || "等待运行事件");
  setBadge($("#gestureReadyBadge"), status.emergency_stopped ? "急停锁定" : (status.mode !== "hand-follow" ? "等待切换" : (status.follow_enabled ? "控制中" : "已准备")), status.emergency_stopped ? "danger" : (status.mode !== "hand-follow" ? "warning" : "success"));

  const left = status.hand_type !== "right";
  const mobileSource = status.vision_source === "mobile-camera";
  $("#gestureMacSourceButton").classList.toggle("selected", !mobileSource);
  $("#gestureMobileSourceButton").classList.toggle("selected", mobileSource);
  $("#leftHandButton").classList.toggle("selected", left);
  $("#rightHandButton").classList.toggle("selected", !left);
  $("#leftHandButton").disabled = !state.online || status.emergency_stopped || left;
  $("#rightHandButton").disabled = !state.online || status.emergency_stopped || !left;
  const followButton = $("#followEnableButton");
  if (status.mode !== "hand-follow") { followButton.textContent = "切换至手势模式"; followButton.dataset.action = "mode-hand"; }
  else { followButton.textContent = "启用跟随"; followButton.dataset.action = "follow-enable"; }
  followButton.disabled = !state.online || status.emergency_stopped || (status.mode === "hand-follow" && status.follow_enabled);
  $("#followPauseButton").disabled = !state.online || status.emergency_stopped || status.mode !== "hand-follow" || !status.follow_enabled;
  $("#fistButton").disabled = !state.online || status.emergency_stopped || status.mode !== "hand-follow";
  setText("#backendValue", status.backend || "unknown");
  setText("#hardwareValue", status.connected ? "已连接" : "未连接");
  setText("#cameraValue", status.camera_ok ? "正常" : "不可用");
  setText("#trackingValue", tracking);
  const reason = status.fallback_reason || status.last_error;
  $("#fallbackReason").hidden = !reason;
  setText("#fallbackReason", reason ? `诊断：${reason}` : "");
  $("#gestureCameraError").hidden = Boolean(status.camera_ok);
  const pose = Array.isArray(status.pose) ? status.pose : [];
  const channels = Array.isArray(status.channels) ? status.channels : Object.keys(CHANNEL_LABELS);
  channels.forEach((name, index) => {
    const row = $(`[data-channel="${name}"]`);
    if (!row) return;
    const value = Math.max(0, Math.min(255, Number(pose[index] || 0)));
    $(".channel-value", row).textContent = String(Math.round(value)).padStart(3, "0");
    $(".channel-bar span", row).style.width = `${value / 255 * 100}%`;
  });
}

function renderAgent(status) {
  if (!$("#agentStreams")) return;
  const objectMode = status.mode === "object-grasp";
  const lidar = status.vision_source === "iphone-lidar";
  const mobileSource = status.vision_source === "mobile-camera";
  const stopped = Boolean(status.emergency_stopped);
  const graspState = status.state || "DISARMED";
  const displayedGraspState = objectMode ? graspState : "WAITING_MODE";
  const iphone = Boolean(status.iphone_connected);
  const depthCalibrated = Boolean(status.depth_calibrated);
  const depthFps = Math.max(0, finiteNumber(status.depth_fps) || 0);
  const depthLatency = finiteNumber(status.depth_latency_ms);
  const signedDistance = finiteNumber(status.signed_distance_mm);
  const validRatio = Math.max(0, Math.min(1, finiteNumber(status.depth_valid_ratio) || 0));
  const hasTarget = Boolean(status.target && status.target !== "无");
  const validDepthTarget = iphone && validRatio > 0 && hasTarget;
  const phaseKey = status.depth_phase || "DEPTH_UNAVAILABLE";

  setText("#agentCameraTitle", lidar ? "iPhone 腕部视角" : (mobileSource ? "手机物品抓取" : "Mac 物品抓取"));
  setText("#agentFps", Number(status.fps || 0).toFixed(1));
  setText("#agentObjectCount", String(status.objects || 0));
  setText("#agentStateLabel", stopped ? "急停锁定" : (STATE_LABELS[displayedGraspState] || displayedGraspState));
  setText("#agentTargetLabel", `目标：${status.target || "无"}`);
  setText("#agentTarget", status.target || "无");
  setText("#agentGraspState", objectMode ? (STATE_LABELS[graspState] || graspState) : "手势模式中");
  setText("#agentEvent", status.last_event || "等待运行事件");
  const maxStable = Math.max(1, Number(status.stable_frames || 1));
  const stable = Math.max(0, Number(status.stable_count || 0));
  setText("#agentStableText", objectMode ? `${stable} / ${maxStable}` : "等待切换");
  $("#agentStableProgress").style.width = objectMode ? `${Math.min(100, stable / maxStable * 100)}%` : "0%";

  $("#macSourceButton").classList.toggle("selected", !lidar && !mobileSource);
  $("#mobileSourceButton").classList.toggle("selected", mobileSource);
  $("#iphoneSourceButton").classList.toggle("selected", lidar);
  $("#macSourceButton").disabled = !state.online || stopped || !objectMode || (!lidar && !mobileSource);
  $("#mobileSourceButton").disabled = !state.online || stopped || !objectMode || mobileSource;
  $("#iphoneSourceButton").disabled = !state.online || stopped || !objectMode || lidar;
  $("#lidarSummary").hidden = !lidar;
  $("#depthPanel").hidden = !lidar;
  $("#agentStreams").classList.toggle("single", !lidar);
  setText("#rgbSourceLabel", lidar ? "iPhone RGB" : (mobileSource ? "手机相机" : "Mac 摄像头"));
  setText("#pairingCode", String(status.pairing_code || "------"));
  setText("#iphoneState", iphone ? "已连接" : "等待连接");
  setText("#depthStreamState", `${depthFps.toFixed(1)} FPS${depthLatency == null ? "" : ` / ${Math.max(0, depthLatency).toFixed(0)} ms`}`);
  setText("#contactDepth", depthCalibrated && finiteNumber(status.contact_depth_mm) != null ? `${finiteNumber(status.contact_depth_mm).toFixed(1)} mm` : "未标定");
  setText("#depthDistance", signedDistance == null ? "---" : `${signedDistance >= 0 ? "+" : ""}${signedDistance.toFixed(1)} mm`);
  setText("#depthPhase", DEPTH_LABELS[phaseKey] || "等待深度");
  $("#calibrateDepthButton").disabled = !state.online || stopped || !objectMode || !lidar || graspState !== "DISARMED" || !validDepthTarget;
  $("#clearDepthButton").disabled = !state.online || stopped || !objectMode || !lidar || graspState !== "DISARMED" || !depthCalibrated;

  let safetyText = "区域安全，可布防";
  let safetyTone = "online";
  if (stopped) { safetyText = "急停锁定，需重启运行器"; safetyTone = "danger"; }
  else if (!objectMode) { safetyText = "当前为手势模式"; safetyTone = "warning"; }
  else if (lidar && !iphone) { safetyText = "iPhone LiDAR 未连接"; safetyTone = "danger"; }
  else if (lidar && !depthCalibrated) { safetyText = "等待 0 cm 接触面标定"; safetyTone = "warning"; }
  else if (!status.camera_ok) { safetyText = "摄像头不可用"; safetyTone = "warning"; }
  else if (status.hand_blocked) { safetyText = "手进入抓取区域，禁止闭合"; safetyTone = "danger"; }
  else if (graspState === "ARMED") { safetyText = "已布防，等待稳定目标"; safetyTone = "warning"; }
  else if (graspState === "CLOSING") { safetyText = "正在按限速闭合"; safetyTone = "warning"; }
  else if (graspState === "HOLDING") safetyText = "已保持抓取，等待张开";
  setDot($("#agentSafetyDot"), safetyTone);
  setText("#agentSafetyText", safetyText);
  $("#agentCameraError").hidden = Boolean(status.camera_ok);
  $("#depthError").hidden = !lidar || (iphone && depthFps > 0);

  const arm = $("#armButton");
  if (!objectMode) { arm.textContent = "切换至物品模式"; arm.dataset.action = "mode-object"; }
  else { arm.textContent = "布防识别"; arm.dataset.action = "arm"; }
  arm.disabled = !state.online || stopped || (objectMode && (graspState !== "DISARMED" || (lidar && (!iphone || !depthCalibrated))));
  $("#disarmButton").disabled = !state.online || stopped || !objectMode || graspState !== "ARMED";
  updateFeeds();
}

function renderDevices(status) {
  setBadge($("#deviceO6Badge"), status.connected ? "已连接" : (status.dry_run ? "模拟" : "未连接"), status.connected ? "success" : (status.dry_run ? "simulation" : "warning"));
  setText("#deviceO6Description", status.connected ? "O6 已连接，指令由安全队列下发。" : (status.dry_run ? "模拟模式，不向真实设备下发。" : "运行层未检测到 O6。"));
  setText("#deviceHandValue", deviceLabel(status.hand_type));
  setText("#deviceCommandValue", String(status.commands || 0));
  setBadge($("#deviceCameraBadge"), status.camera_ok ? "正常" : "异常", status.camera_ok ? "success" : "danger");
  setText("#deviceCameraDescription", status.camera_ok ? "视觉输入在线，可用于识别。" : "请检查权限或设备占用。" );
  setText("#deviceFpsValue", `${Number(status.fps || 0).toFixed(1)} FPS`);
  setText("#deviceCameraState", status.camera_ok ? "在线" : "不可用");
  setBadge($("#deviceIphoneBadge"), status.iphone_connected ? "已连接" : "待连接", status.iphone_connected ? "success" : "warning");
  setText("#deviceIphoneDescription", status.iphone_connected ? "RGB 与 LiDAR 深度流已接入。" : "局域网接收器在线，等待 iPhone。" );
  setText("#deviceIphoneName", status.iphone_device || "---");
  setText("#deviceDepthFps", `${Number(status.depth_fps || 0).toFixed(1)} FPS`);
  setText("#deviceDepthCalibration", status.depth_calibrated ? "接触面已标定" : "尚未标定");
  setBadge($("#deviceRuntimeBadge"), status.ready ? "运行中" : "异常", status.ready ? "success" : "danger");
  setText("#deviceBackend", status.backend || "unknown");
  setText("#deviceVisionSource", status.vision_source === "iphone-lidar" ? "iPhone LiDAR" : (status.vision_source === "mobile-camera" ? "手机相机" : "Mac 摄像头"));
  setText("#deviceBonjour", status.bonjour_state || "---");
  setText("#deviceLastEvent", status.last_event || "等待事件");
}

function renderStatus(status) {
  state.status = status;
  setOnline(true);
  renderGlobal(status);
  renderHome(status);
  renderGesture(status);
  renderAgent(status);
  renderDevices(status);
  updateMobilePrimary();
  $$(".real-control").forEach((button) => {
    if (!button.matches("button")) return;
    const managed = ["leftHandButton", "rightHandButton", "followEnableButton", "followPauseButton", "macSourceButton", "mobileSourceButton", "iphoneSourceButton", "gestureMacSourceButton", "gestureMobileSourceButton", "calibrateDepthButton", "clearDepthButton", "armButton", "disarmButton"].includes(button.id);
    if (!managed) button.disabled = !status.ready || Boolean(status.emergency_stopped);
  });
  if (!state.lastEvent) state.lastEvent = status.last_event || "";
  else if (status.last_event && status.last_event !== state.lastEvent) {
    state.lastEvent = status.last_event;
    showToast("运行状态更新", status.last_event, status.emergency_stopped ? "danger" : "success");
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderStatus(await response.json());
  } catch (error) {
    setOnline(false);
    setText("#homeReadiness span", "视觉运行层离线，真实控制已停用");
    setText("#homeLastEvent", `状态接口错误：${error.message}`);
  }
}

async function sendAction(action, button = null) {
  if (!REAL_ACTIONS.has(action)) return;
  if (!state.online) return showToast("无法发送指令", "视觉运行层当前离线。", "danger");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
    const result = await response.json();
    if (!response.ok || !result.accepted) throw new Error(result.error || `HTTP ${response.status}`);
    showToast("指令已进入安全队列", "等待运行层确认实际状态。");
    window.setTimeout(refreshStatus, 80);
  } catch (error) {
    showToast("指令失败", error.message, "danger");
  } finally {
    if (button) window.setTimeout(() => { button.disabled = false; }, 260);
  }
}

function stopMobileTracks() {
  window.clearTimeout(mobileCamera.timer);
  mobileCamera.timer = null;
  mobileCamera.active = false;
  if (mobileCamera.stream) mobileCamera.stream.getTracks().forEach((track) => track.stop());
  mobileCamera.stream = null;
  $("#mobileCameraPreview").srcObject = null;
  $("#startMobileCamera").disabled = false;
  $("#switchMobileCamera").disabled = true;
  $("#stopMobileCamera").disabled = true;
}

async function uploadMobileFrame() {
  if (!mobileCamera.active) return;
  const video = $("#mobileCameraPreview");
  if (video.readyState < 2 || !video.videoWidth) {
    mobileCamera.timer = window.setTimeout(uploadMobileFrame, 90);
    return;
  }
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 480;
  const sourceRatio = video.videoWidth / video.videoHeight;
  const targetRatio = 4 / 3;
  let sx = 0, sy = 0, sw = video.videoWidth, sh = video.videoHeight;
  if (sourceRatio > targetRatio) { sw = video.videoHeight * targetRatio; sx = (video.videoWidth - sw) / 2; }
  else { sh = video.videoWidth / targetRatio; sy = (video.videoHeight - sh) / 2; }
  canvas.getContext("2d").drawImage(video, sx, sy, sw, sh, 0, 0, 640, 480);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.72));
  try {
    if (!blob || !mobileCamera.active) return;
    const response = await fetch("/api/mobile-frame", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob, cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setText("#mobileCameraStatus", `${mobileCamera.facingMode === "environment" ? "后置" : "前置"}相机采集中`);
  } catch (error) {
    setText("#mobileCameraStatus", `上传失败：${error.message}`);
  }
  if (mobileCamera.active) mobileCamera.timer = window.setTimeout(uploadMobileFrame, 83);
}

async function startMobileCamera(button = null) {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    setText("#mobileCameraStatus", "需要使用 HTTPS 地址打开并允许相机权限");
    return showToast("无法打开手机相机", "请使用 HTTPS 局域网地址。", "danger");
  }
  if (button) button.disabled = true;
  stopMobileTracks();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: mobileCamera.facingMode }, width: { ideal: 1280 }, height: { ideal: 960 }, frameRate: { ideal: 12, max: 15 } },
    });
    mobileCamera.stream = stream;
    mobileCamera.active = true;
    const video = $("#mobileCameraPreview");
    video.srcObject = stream;
    await video.play();
    $("#startMobileCamera").disabled = true;
    $("#switchMobileCamera").disabled = false;
    $("#stopMobileCamera").disabled = false;
    await sendAction("source-mobile-camera");
    uploadMobileFrame();
  } catch (error) {
    stopMobileTracks();
    setText("#mobileCameraStatus", `相机不可用：${error.message}`);
    showToast("手机相机未启动", "请在 Safari 中允许相机权限。", "danger");
  }
}

async function stopMobileCamera(selectMac = true) {
  stopMobileTracks();
  setText("#mobileCameraStatus", "手机相机已停止");
  if (selectMac && state.status?.vision_source === "mobile-camera") await sendAction("source-mac-camera");
}

function renderChannels() {
  for (const [name, label] of Object.entries(CHANNEL_LABELS)) {
    const row = document.createElement("div");
    row.className = "channel-row";
    row.dataset.channel = name;
    row.innerHTML = `<span class="channel-name" title="${name}">${label}</span><span class="channel-bar"><span></span></span><strong class="channel-value">---</strong>`;
    $("#channelList").append(row);
  }
}

$$('[data-page-target]').forEach((button) => button.addEventListener("click", () => setPage(button.dataset.pageTarget)));
$$('[data-action]').forEach((button) => button.addEventListener("click", () => {
  const action = button.dataset.action;
  if (action === "stop") globalThis.agentDemoController?.stop();
  if (action === "stop" && state.status?.emergency_stopped) return showToast("急停保持锁定", "请重启运行器解除，前端不会绕过安全锁。", "danger");
  if (action === "source-mobile-camera" && !mobileCamera.active) return startMobileCamera(button);
  if ((action === "source-mac-camera" || action === "source-iphone-lidar") && mobileCamera.active) stopMobileTracks();
  sendAction(action, button);
}));
$("#startMobileCamera").addEventListener("click", (event) => startMobileCamera(event.currentTarget));
$("#switchMobileCamera").addEventListener("click", async () => {
  mobileCamera.facingMode = mobileCamera.facingMode === "environment" ? "user" : "environment";
  await startMobileCamera($("#switchMobileCamera"));
});
$("#stopMobileCamera").addEventListener("click", () => stopMobileCamera(true));
window.addEventListener("pagehide", () => stopMobileTracks());
$("#mobilePrimaryAction").addEventListener("click", () => {
  const button = $("#mobilePrimaryAction");
  if (button.dataset.action) return sendAction(button.dataset.action, button);
  if (state.page === "home") return setPage("gesture");
  if (state.page === "devices") return refreshStatus();
  if (state.page === "history") return $(".history-item.active")?.scrollIntoView({ block: "center", behavior: "smooth" });
  if (state.page === "settings") return $("#saveSettings").click();
  if (state.page === "agent") return globalThis.agentDemoController?.triggerVoiceDemo();
});
$("#refreshDevices").addEventListener("click", async (event) => { event.currentTarget.textContent = "刷新中…"; await refreshStatus(); event.currentTarget.textContent = "刷新状态"; showToast("设备状态已刷新", state.online ? "真实运行状态已更新。" : "运行层仍处于离线状态。", state.online ? "success" : "warning"); });
$$('.history-item').forEach((button) => button.addEventListener("click", () => { $$(".history-item").forEach((item) => item.classList.toggle("active", item === button)); const item = HISTORY[button.dataset.history]; setText("#historyTitle", item[0]); setText("#historyMeta", item[1]); setText("#historyMode", item[2]); setText("#historySafety", item[3]); }));
$$('[data-settings-tab]').forEach((button) => button.addEventListener("click", () => { $$('[data-settings-tab]').forEach((item) => item.classList.toggle("active", item === button)); showToast("设置分类", `${button.textContent}选项为演示界面。`); }));
$$('[data-interface-mode]').forEach((button) => button.addEventListener("click", () => { document.body.classList.toggle("expert-mode", button.dataset.interfaceMode === "expert"); $$('[data-interface-mode]').forEach((item) => item.classList.toggle("selected", item === button)); }));
$("#saveSettings").addEventListener("click", () => { setText("#settingsSaveStatus", "本次会话的演示设置已保存"); showToast("演示设置已保存", "未修改运行层配置或硬件参数。"); });
$$('[data-video-feed]').forEach((image) => image.addEventListener("error", () => { $(image.id === "gestureFeed" ? "#gestureCameraError" : "#agentCameraError").hidden = false; }));
$("#depthFeed")?.addEventListener("error", () => { if (state.page === "agent") $("#depthError").hidden = false; });

renderChannels();
configureGestureCameraControls();
updateFeeds();
updateMobilePrimary();
refreshStatus();
window.setInterval(refreshStatus, 250);
