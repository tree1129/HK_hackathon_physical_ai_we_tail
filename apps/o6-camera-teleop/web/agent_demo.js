(function installAgentDemoCore(global) {
  "use strict";

  const MOCK_OBJECTS = Object.freeze({
    "red-cup": Object.freeze({ id: "red-cup", label: "红色杯子", kind: "cup", color: "red" }),
    "blue-cup": Object.freeze({ id: "blue-cup", label: "蓝色杯子", kind: "cup", color: "blue" }),
    "left-tray": Object.freeze({ id: "left-tray", label: "左侧托盘", kind: "tray", position: "left" }),
  });

  function isConfirmCommand(text) {
    return /(^|[，,。\s])(确认|确认执行|开始|开始执行)([，,。\s]|$)/i.test(String(text).trim());
  }

  function isStopCommand(text) {
    return /(停止|急停|取消任务|取消执行)/i.test(String(text));
  }

  function cloneObject(item) {
    return item ? { ...item } : null;
  }

  function initialState() {
    return {
      phase: "idle",
      command: "",
      message: "等待任务",
      target: null,
      destination: null,
      candidates: [],
      plan: [],
      currentStep: -1,
    };
  }

  class AgentDemoMachine {
    constructor() {
      this.state = initialState();
      this.pendingDestination = null;
    }

    snapshot() {
      return {
        ...this.state,
        target: cloneObject(this.state.target),
        destination: cloneObject(this.state.destination),
        candidates: this.state.candidates.map(cloneObject),
        plan: this.state.plan.map((step) => ({ ...step })),
      };
    }

    submit(rawCommand) {
      const command = String(rawCommand || "").trim();
      if (isStopCommand(command)) return this.stop();
      if (isConfirmCommand(command) && this.state.phase === "planned") return this.confirm();

      const mentionsCup = /(杯子?|cup)/i.test(command);
      const destination = /(托盘|tray|指定区域)/i.test(command)
        ? MOCK_OBJECTS["left-tray"]
        : null;
      const target = /(红色?|red)/i.test(command)
        ? MOCK_OBJECTS["red-cup"]
        : /(蓝色?|blue)/i.test(command)
          ? MOCK_OBJECTS["blue-cup"]
          : null;

      this.pendingDestination = destination;
      if (mentionsCup && !target) {
        this.state = {
          ...initialState(),
          phase: "clarifying",
          command,
          message: "检测到两个杯子，请选择红色杯子或蓝色杯子。",
          destination: cloneObject(destination),
          candidates: [cloneObject(MOCK_OBJECTS["red-cup"]), cloneObject(MOCK_OBJECTS["blue-cup"])],
        };
        return this.snapshot();
      }
      if (!mentionsCup || !target) {
        this.state = {
          ...initialState(),
          command,
          message: "这条指令没有形成可演示计划，请指定杯子和操作。",
        };
        return this.snapshot();
      }
      return this._plan(command, target, destination);
    }

    clarify(targetId) {
      if (this.state.phase !== "clarifying") return this.snapshot();
      const answer = String(targetId || "");
      const resolvedId = /(红色?|red)/i.test(answer)
        ? "red-cup"
        : /(蓝色?|blue)/i.test(answer)
          ? "blue-cup"
          : answer;
      const target = MOCK_OBJECTS[resolvedId];
      if (!target || target.kind !== "cup") return this.snapshot();
      return this._plan(this.state.command, target, this.pendingDestination || this.state.destination);
    }

    confirm() {
      if (this.state.phase !== "planned") return this.snapshot();
      this.state.phase = "running";
      this.state.message = "计划已确认，开始演示。";
      return this.snapshot();
    }

    advance() {
      if (this.state.phase !== "running") return this.snapshot();
      this.state.currentStep += 1;
      if (this.state.currentStep >= this.state.plan.length - 1) {
        this.state.currentStep = this.state.plan.length - 1;
        this.state.phase = "completed";
        this.state.message = "任务演示已完成。";
      } else {
        this.state.message = this.state.plan[this.state.currentStep].detail;
      }
      return this.snapshot();
    }

    loseTarget() {
      if (this.state.phase !== "running") return this.snapshot();
      this.state.phase = "paused";
      this.state.message = "目标暂时丢失，演示已暂停。";
      return this.snapshot();
    }

    resume() {
      if (this.state.phase !== "paused") return this.snapshot();
      this.state.phase = "running";
      this.state.message = "目标已重新识别，继续当前步骤。";
      return this.snapshot();
    }

    stop() {
      this.state.phase = "stopped";
      this.state.message = "任务已停止，需要重新开始。";
      return this.snapshot();
    }

    reset() {
      this.pendingDestination = null;
      this.state = initialState();
      return this.snapshot();
    }

    _plan(command, target, destination) {
      const plan = [
        { id: "locate", title: `定位${target.label}`, detail: "视觉目标已锁定，置信度 92%。" },
        { id: "grasp", title: "接近并抓取", detail: "工作区检查通过，执行 Mock 抓取。" },
      ];
      if (destination) {
        plan.push(
          { id: "move", title: `移动到${destination.label}`, detail: "保持抓取并移动到目标区域。" },
          { id: "release", title: "放置并撤离", detail: "释放目标并退出工作区。" },
        );
      }
      this.state = {
        ...initialState(),
        phase: "planned",
        command,
        message: `已锁定${target.label}，请确认执行计划。`,
        target: cloneObject(target),
        destination: cloneObject(destination),
        plan,
      };
      return this.snapshot();
    }
  }

  global.AgentDemoCore = {
    AgentDemoMachine,
    MOCK_OBJECTS,
    isConfirmCommand,
    isStopCommand,
  };

  if (!global.document) return;

  const PHASE_META = {
    idle: ["等待任务", "simulation"],
    listening: ["正在聆听", "warning"],
    clarifying: ["需要确认目标", "warning"],
    planned: ["等待执行确认", "warning"],
    running: ["演示执行中", "simulation"],
    paused: ["目标丢失", "danger"],
    completed: ["任务完成", "success"],
    stopped: ["任务已停止", "danger"],
  };

  class AgentDemoController {
    constructor(documentRef) {
      this.document = documentRef;
      this.machine = new AgentDemoMachine();
      this.timer = null;
      this.voiceTimer = null;
      this.recognition = null;
      this.wakeEnabled = false;
      this.destroyed = false;
      this.nodes = this._collectNodes();
      this._bindEvents();
      this.render(this.machine.snapshot());
    }

    _collectNodes() {
      const byId = (id) => this.document.getElementById(id);
      return {
        conversation: byId("agentConversation"),
        clarification: byId("agentClarification"),
        plan: byId("agentPlan"),
        planSummary: byId("agentPlanSummary"),
        planState: byId("agentPlanState"),
        phaseBadge: byId("agentPhaseBadge"),
        taskInput: byId("agentTaskInput"),
        composer: byId("agentComposer"),
        micButton: byId("agentMicButton"),
        wakeToggle: byId("agentWakeToggle"),
        confirmButton: byId("agentConfirmButton"),
        loseTargetButton: byId("agentLoseTargetButton"),
        cancelButton: byId("agentCancelButton"),
        recoveryActions: byId("agentRecoveryActions"),
        resumeButton: byId("agentResumeButton"),
        restartButton: byId("agentRestartButton"),
        voiceDemoButton: byId("agentVoiceDemoButton"),
        voiceStatus: byId("agentVoiceStatus"),
        lockedTarget: byId("agentLockedTarget"),
        ambiguity: byId("agentAmbiguity"),
        workspaceSafety: byId("agentWorkspaceSafety"),
        scenePulse: byId("agentScenePulse"),
      };
    }

    _bindEvents() {
      this.nodes.composer?.addEventListener("submit", (event) => {
        event.preventDefault();
        this.submit(this.nodes.taskInput.value, "text");
      });
      this.nodes.confirmButton?.addEventListener("click", () => this.confirm());
      this.nodes.cancelButton?.addEventListener("click", () => this.stop("任务已由操作者取消。"));
      this.nodes.loseTargetButton?.addEventListener("click", () => this.loseTarget());
      this.nodes.resumeButton?.addEventListener("click", () => this.resume());
      this.nodes.restartButton?.addEventListener("click", () => this.reset());
      this.nodes.voiceDemoButton?.addEventListener("click", () => this.triggerVoiceDemo());
      this.nodes.micButton?.addEventListener("click", () => this.startListening());
      this.nodes.wakeToggle?.addEventListener("change", () => {
        this.wakeEnabled = this.nodes.wakeToggle.checked;
        if (this.wakeEnabled) this.startWakeMode();
        else this._stopRecognition();
      });
      this.document.querySelectorAll("[data-agent-example]").forEach((button) => {
        button.addEventListener("click", () => this.submit(button.dataset.agentExample, "example"));
      });
      this.document.querySelectorAll("[data-agent-clarify]").forEach((button) => {
        button.addEventListener("click", () => this.clarify(button.dataset.agentClarify));
      });
      this.document.querySelectorAll("[data-agent-object]").forEach((button) => {
        button.addEventListener("click", () => {
          if (this.machine.state.phase === "clarifying") return this.clarify(button.dataset.agentObject);
          const item = MOCK_OBJECTS[button.dataset.agentObject];
          if (item?.kind === "cup") this.nodes.taskInput.value = `抓住${item.label}，然后放到左侧托盘`;
        });
      });
      this.document.querySelectorAll("[data-page-target]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.dataset.pageTarget !== "agent") this.deactivate();
        });
      });
    }

    submit(rawText, source = "text") {
      const text = String(rawText || "").trim();
      if (!text) return this.machine.snapshot();
      this._clearRunTimer();
      this._appendMessage("user", text, source === "voice" ? "V" : "你");
      let state;
      if (this.machine.state.phase === "clarifying" && /(红|蓝|red|blue)/i.test(text)) state = this.machine.clarify(text);
      else state = this.machine.submit(this._stripWakeWord(text));
      this.nodes.taskInput.value = "";
      this.render(state);
      this._appendMessage("assistant", state.message, "A");
      if (state.phase === "running") this._startRunTimer();
      return state;
    }

    clarify(target) {
      const item = MOCK_OBJECTS[target] || (/(红|red)/i.test(target) ? MOCK_OBJECTS["red-cup"] : MOCK_OBJECTS["blue-cup"]);
      this._appendMessage("user", item.label, "你");
      const state = this.machine.clarify(target);
      this.render(state);
      this._appendMessage("assistant", state.message, "A");
      return state;
    }

    confirm() {
      const state = this.machine.confirm();
      this.render(state);
      if (state.phase === "running") {
        this._appendMessage("assistant", "确认已收到，开始逐步演示。", "A");
        this._startRunTimer();
      }
      return state;
    }

    loseTarget() {
      this._clearRunTimer();
      const state = this.machine.loseTarget();
      this.render(state);
      this._appendMessage("assistant", state.message, "A");
      return state;
    }

    resume() {
      const state = this.machine.resume();
      this.render(state);
      this._appendMessage("assistant", state.message, "A");
      if (state.phase === "running") this._startRunTimer();
      return state;
    }

    stop(message = "急停已触发，演示任务立即终止。") {
      this._clearRunTimer();
      this._clearVoiceTimer();
      this._stopRecognition();
      const wasStopped = this.machine.state.phase === "stopped";
      const state = this.machine.stop();
      this.render(state);
      if (!wasStopped) this._appendMessage("assistant", message, "A");
      return state;
    }

    reset() {
      this._clearRunTimer();
      const state = this.machine.reset();
      this.nodes.conversation.innerHTML = "";
      this._appendMessage("assistant", "请指定目标和任务，例如“抓住红色杯子，然后放到左侧托盘”。", "A");
      this.render(state);
      return state;
    }

    deactivate() {
      this._clearRunTimer();
      if (!this.wakeEnabled) this._stopRecognition();
    }

    destroy() {
      this.destroyed = true;
      this.deactivate();
      this._clearVoiceTimer();
    }

    triggerVoiceDemo() {
      this._clearVoiceTimer();
      const phase = this.machine.state.phase;
      const transcript = phase === "clarifying"
        ? "红色的"
        : phase === "planned"
          ? "确认执行"
          : phase === "running"
            ? "停止执行"
            : "Tail，抓住红色杯子，然后放到左侧托盘";
      this._setListening(true, "正在播放语音示例...");
      this.voiceTimer = global.setTimeout(() => {
        this._setListening(false, `识别结果：${transcript}`);
        this.submit(transcript, "voice");
      }, 650);
    }

    startListening() {
      const Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
      if (!Recognition) return this.triggerVoiceDemo();
      this._startRecognition(false);
    }

    startWakeMode() {
      const Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
      if (!Recognition) {
        this._setVoiceStatus("唤醒词演示已开启；使用“播放语音示例”触发。");
        return;
      }
      this._startRecognition(true);
    }

    _startRecognition(continuous) {
      this._stopRecognition();
      const Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
      if (!Recognition) return;
      const recognition = new Recognition();
      this.recognition = recognition;
      recognition.lang = "zh-CN";
      recognition.interimResults = true;
      recognition.continuous = Boolean(continuous);
      recognition.onstart = () => this._setListening(true, continuous ? "正在等待唤醒词 Tail..." : "正在聆听...");
      recognition.onresult = (event) => {
        let transcript = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) transcript += event.results[index][0].transcript;
        this._setVoiceStatus(`正在识别：${transcript}`);
        if (!event.results[event.results.length - 1].isFinal) return;
        const wakeMatched = /(tail|泰尔|小助手)/i.test(transcript);
        if (!continuous || wakeMatched || isStopCommand(transcript) || isConfirmCommand(transcript)) this.submit(transcript, "voice");
      };
      recognition.onerror = () => {
        this._setListening(false, "语音识别不可用，可播放语音示例。");
      };
      recognition.onend = () => {
        this._setListening(false, this.wakeEnabled ? "唤醒词已开启" : "语音待命");
        if (this.wakeEnabled && !this.destroyed) global.setTimeout(() => this.startWakeMode(), 350);
      };
      try {
        recognition.start();
      } catch (_error) {
        this._setListening(false, "语音识别忙碌，请稍后重试。");
      }
    }

    _stopRecognition() {
      if (!this.recognition) return;
      const recognition = this.recognition;
      this.recognition = null;
      recognition.onend = null;
      try { recognition.stop(); } catch (_error) { /* already stopped */ }
      this._setListening(false, "语音待命");
    }

    _stripWakeWord(text) {
      return String(text).replace(/^(tail|泰尔|小助手)[，,：:\s]*/i, "").trim();
    }

    _startRunTimer() {
      this._clearRunTimer();
      const tick = () => {
        const state = this.machine.advance();
        this.render(state);
        const step = state.plan[state.currentStep];
        if (step) this._appendMessage("assistant", `${step.title}：${step.detail}`, "A");
        if (state.phase === "completed") {
          this._clearRunTimer();
          this._appendMessage("assistant", "任务完成，Mock 审计记录已生成。", "A");
        }
      };
      tick();
      if (this.machine.state.phase === "running") this.timer = global.setInterval(tick, 1250);
    }

    _clearRunTimer() {
      if (this.timer) global.clearInterval(this.timer);
      this.timer = null;
    }

    _clearVoiceTimer() {
      if (this.voiceTimer) global.clearTimeout(this.voiceTimer);
      this.voiceTimer = null;
    }

    _appendMessage(role, text, avatar) {
      if (!this.nodes.conversation || !text) return;
      const message = this.document.createElement("div");
      message.className = `agent-message ${role}`;
      const icon = this.document.createElement("span");
      icon.textContent = avatar;
      const body = this.document.createElement("p");
      body.textContent = text;
      message.append(icon, body);
      this.nodes.conversation.append(message);
      this.nodes.conversation.scrollTop = this.nodes.conversation.scrollHeight;
    }

    _setListening(active, status) {
      this.nodes.micButton?.classList.toggle("listening", active);
      if (this.nodes.micButton) this.nodes.micButton.textContent = active ? "■" : "●";
      this._setVoiceStatus(status);
    }

    _setVoiceStatus(status) {
      if (this.nodes.voiceStatus) this.nodes.voiceStatus.textContent = status;
    }

    render(state) {
      if (!this.nodes.phaseBadge) return;
      const [phaseLabel, phaseTone] = PHASE_META[state.phase] || PHASE_META.idle;
      this.nodes.phaseBadge.textContent = phaseLabel;
      this.nodes.phaseBadge.className = `badge ${phaseTone}`;
      this.nodes.lockedTarget.textContent = state.target?.label || "尚未选择";
      this.nodes.ambiguity.textContent = state.phase === "clarifying" ? `${state.candidates.length} 个候选` : (state.target ? "唯一候选" : "等待指令");
      this.nodes.workspaceSafety.textContent = state.phase === "stopped" ? "任务已锁定" : (state.phase === "paused" ? "演示已暂停" : "可演示");
      this.nodes.workspaceSafety.className = state.phase === "stopped" ? "" : "success-text";
      this.nodes.clarification.hidden = state.phase !== "clarifying";
      this.nodes.recoveryActions.hidden = !["paused", "stopped", "completed"].includes(state.phase);
      this.nodes.confirmButton.disabled = state.phase !== "planned";
      this.nodes.loseTargetButton.disabled = state.phase !== "running";
      this.nodes.cancelButton.disabled = ["idle", "stopped", "completed"].includes(state.phase);
      this.nodes.scenePulse.hidden = state.phase !== "running";
      this._renderDetections(state);
      this._renderPlan(state);
    }

    _renderDetections(state) {
      this.document.querySelectorAll(".mock-detection").forEach((node) => {
        const active = node.dataset.agentObject === state.target?.id || node.dataset.agentObject === state.destination?.id;
        const hasSelection = Boolean(state.target || state.destination);
        node.classList.toggle("selected", active);
        node.classList.toggle("dimmed", hasSelection && !active);
      });
    }

    _renderPlan(state) {
      this.nodes.plan.innerHTML = "";
      if (!state.plan.length) {
        const empty = this.document.createElement("li");
        empty.className = "empty";
        empty.innerHTML = "<span>—</span><div><strong>等待自然语言任务</strong><small>Agent 会在确认前展示完整计划</small></div>";
        this.nodes.plan.append(empty);
        this.nodes.planSummary.textContent = "输入任务后生成步骤";
        this.nodes.planState.textContent = "未生成";
        return;
      }
      state.plan.forEach((step, index) => {
        const item = this.document.createElement("li");
        const completed = state.phase === "completed" || index < state.currentStep;
        const current = state.phase === "running" && index === state.currentStep;
        const failed = ["paused", "stopped"].includes(state.phase) && index === Math.max(0, state.currentStep);
        item.className = completed ? "done" : current ? "current" : failed ? "failed" : "";
        const number = this.document.createElement("span");
        number.textContent = completed ? "✓" : String(index + 1).padStart(2, "0");
        const detail = this.document.createElement("div");
        const title = this.document.createElement("strong");
        const description = this.document.createElement("small");
        title.textContent = step.title;
        description.textContent = step.detail;
        detail.append(title, description);
        item.append(number, detail);
        this.nodes.plan.append(item);
      });
      this.nodes.planSummary.textContent = `${state.target.label}${state.destination ? ` → ${state.destination.label}` : ""}`;
      this.nodes.planState.textContent = state.phase === "planned"
        ? "等待确认"
        : state.phase === "running"
          ? `${state.currentStep + 1} / ${state.plan.length}`
          : PHASE_META[state.phase][0];
    }
  }

  const root = global.document.getElementById("page-agent");
  if (root) {
    const controller = new AgentDemoController(global.document);
    global.agentDemoController = {
      stop: (message) => controller.stop(message),
      reset: () => controller.reset(),
      triggerVoiceDemo: () => controller.triggerVoiceDemo(),
      startWakeMode: () => controller.startWakeMode(),
      destroy: () => controller.destroy(),
    };
  }
})(globalThis);
