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
      const target = MOCK_OBJECTS[targetId];
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
})(globalThis);
