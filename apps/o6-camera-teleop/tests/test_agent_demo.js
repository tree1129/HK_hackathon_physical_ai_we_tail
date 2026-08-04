const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const scriptPath = path.join(__dirname, "..", "web", "agent_demo.js");
const source = fs.existsSync(scriptPath) ? fs.readFileSync(scriptPath, "utf8") : "";
const context = { console, globalThis: {} };
vm.runInNewContext(source, context);

assert.ok(context.globalThis.AgentDemoCore, "AgentDemoCore export is missing");
const { AgentDemoMachine, isConfirmCommand, isStopCommand } = context.globalThis.AgentDemoCore;

test("plans a specific multi-step task but waits for confirmation", () => {
  const machine = new AgentDemoMachine();

  const state = machine.submit("抓住红色杯子，然后放到左侧托盘");

  assert.equal(state.phase, "planned");
  assert.equal(state.target.id, "red-cup");
  assert.equal(state.destination.id, "left-tray");
  assert.equal(state.plan.length, 4);
  assert.equal(state.currentStep, -1);
});

test("asks for clarification when a cup is ambiguous", () => {
  const machine = new AgentDemoMachine();

  const state = machine.submit("抓住杯子");

  assert.equal(state.phase, "clarifying");
  assert.deepEqual(Array.from(state.candidates, (item) => item.id), ["red-cup", "blue-cup"]);
});

test("clarification selects one target and creates a plan", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把杯子放到左边托盘");

  const state = machine.clarify("red-cup");

  assert.equal(state.phase, "planned");
  assert.equal(state.target.id, "red-cup");
  assert.equal(state.destination.id, "left-tray");
});

test("runs only after explicit confirmation", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");

  assert.equal(machine.advance().phase, "planned");
  assert.equal(machine.confirm().phase, "running");
  assert.equal(machine.advance().currentStep, 0);
});

test("completes after every plan step advances", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");
  machine.confirm();

  machine.advance();
  machine.advance();
  machine.advance();
  const state = machine.advance();

  assert.equal(state.phase, "completed");
  assert.equal(state.currentStep, 3);
});

test("pauses on target loss and resumes the same plan", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");
  machine.confirm();
  machine.advance();

  assert.equal(machine.loseTarget().phase, "paused");
  const state = machine.resume();

  assert.equal(state.phase, "running");
  assert.equal(state.currentStep, 0);
});

test("stop terminates the current task immediately", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");
  machine.confirm();

  const state = machine.stop();

  assert.equal(state.phase, "stopped");
  assert.equal(machine.advance().phase, "stopped");
});

test("recognizes voice confirmation and stop phrases", () => {
  assert.equal(isConfirmCommand("确认执行"), true);
  assert.equal(isConfirmCommand("开始"), true);
  assert.equal(isStopCommand("Tail，急停"), true);
  assert.equal(isStopCommand("取消任务"), true);
});

test("rejects commands outside the demo vocabulary", () => {
  const machine = new AgentDemoMachine();

  const state = machine.submit("帮我整理整个房间");

  assert.equal(state.phase, "idle");
  assert.match(state.message, /没有形成可演示计划/);
});
