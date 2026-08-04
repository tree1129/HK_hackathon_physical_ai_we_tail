# O6 TAIL3 Light Responsive Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-screen O6 web console with the approved six-page TAIL3 interface in a light responsive theme while preserving real hand-follow, object-grasp, iPhone LiDAR depth, video, and safety behavior.

**Architecture:** Keep the Flask runtime and its four existing endpoints unchanged. Replace the static web surface with one responsive app shell and a small client-side adapter that maps `/api/status`, `/api/action`, `/video_feed`, and `/depth_feed` to the new pages; unsupported Agent planning, mechanical-arm calibration, history, and settings behaviors remain isolated demo state with visible labels.

**Tech Stack:** Python 3.9+, Flask, vanilla HTML, CSS, JavaScript, `unittest`, browser-based responsive QA.

---

## File Map

- Modify `web/index.html`: six-page semantic structure, navigation, global status, real-control hooks, demo labels, mobile safety dock.
- Modify `web/styles.css`: light design tokens, desktop shell, workspace components, responsive mobile layout, fixed safety controls.
- Modify `web/app.js`: navigation, backend adapter, status rendering, real actions, demo-only interactions, error handling.
- Modify `tests/test_mapper.py`: static asset contract tests plus existing endpoint tests.
- Preserve `web_console.py`: backend API, LiDAR receiver, and safety behavior remain unchanged.
- Preserve `web-backup-before-tail3-light-20260804/`: immutable rollback baseline.

### Task 1: Lock the Web Contract With Tests

**Files:**
- Modify: `tests/test_mapper.py`

- [ ] **Step 1: Add a failing six-page static contract test**

Add a test that requests `/`, `/assets/styles.css`, and `/assets/app.js`, then asserts the HTML contains `page-home`, `page-gesture`, `page-agent`, `page-devices`, `page-history`, `page-settings`, `mobile-safety-dock`, `/video_feed`, and a visible `演示` label.

- [ ] **Step 2: Add a failing real-action contract assertion**

Assert the JavaScript contains each supported action string: `hand-left`, `hand-right`, `mode-hand`, `mode-object`, `source-mac-camera`, `source-iphone-lidar`, `depth-calibrate-contact`, `depth-clear-calibration`, `follow-enable`, `follow-pause`, `arm`, `disarm`, `open`, and `stop`.

- [ ] **Step 3: Run the focused test and verify failure**

Run:

```bash
python -m unittest tests.test_mapper.WebConsoleTests.test_web_assets_expose_tail3_shell -v
```

Expected: failure because the six-page shell does not exist yet.

### Task 2: Build the Six-Page Semantic Shell

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Replace the old single console layout**

Create one `.app-shell` containing a desktop sidebar, sticky topbar, six `<section class="page">` elements, a fixed desktop emergency control, a mobile safety dock, and a mobile bottom navigation.

- [ ] **Step 2: Preserve all real integration hooks**

Keep `/video_feed`, `/depth_feed`, IDs for status fields and six channel output values, and `data-action` attributes for every supported backend action. Use separate real-control hooks for hand-follow, object-grasp, source selection, and LiDAR calibration.

- [ ] **Step 3: Mark unsupported content explicitly**

Add visible `演示模式` or `演示数据` labels to Agent planning, unsupported device/calibration rows, task history, and settings persistence.

- [ ] **Step 4: Run the static contract test**

Run the focused test from Task 1. Expected: HTML assertions pass; JavaScript assertions may still fail until Task 4.

### Task 3: Implement the Light Responsive Design System

**Files:**
- Modify: `web/styles.css`

- [ ] **Step 1: Define the approved light tokens**

Use cold-gray backgrounds, white surfaces, near-black text, restrained one-pixel borders, 8px maximum card radius, blue hand controls, purple Agent indicators, green readiness, amber warnings, and red danger states.

- [ ] **Step 2: Implement the desktop shell**

Style the fixed sidebar, sticky topbar, content stage, two-column workspaces, camera treatment, status tables, controls, progress rows, and fixed emergency button without dark page backgrounds or decorative glow effects.

- [ ] **Step 3: Implement the mobile shell**

At widths below 760px, hide the desktop sidebar, reduce the header, convert every page to one column, make the camera first, hide low-priority engineering text where appropriate, and reserve space for `.mobile-safety-dock` plus `.mobile-nav`.

- [ ] **Step 4: Add interaction and accessibility states**

Add hover, active, selected, disabled, focus-visible, loading, offline, and emergency-locked styles, plus `prefers-reduced-motion` handling.

### Task 4: Add the Backend Adapter and Page State

**Files:**
- Modify: `web/app.js`

- [ ] **Step 1: Implement page navigation**

Use `data-page-target` buttons to set the active page, update the topbar title, synchronize desktop/mobile selected states, and scroll to the top without changing the URL.

- [ ] **Step 2: Keep one status polling path**

Poll `/api/status` every 250ms, normalize missing values, and render global connection, backend mode, camera health, selected O6 hand, emergency lock, target, stability, pose, and command count.

- [ ] **Step 3: Map the hand-follow page to real actions**

Entering the page requests `mode-hand` only when required. Enable `follow-enable`, `follow-pause`, `hand-left`, `hand-right`, `open`, and `stop` according to confirmed backend status.

- [ ] **Step 4: Map the Agent/object page to real actions**

Entering the page requests `mode-object` only when required. Map `source-mac-camera`, `source-iphone-lidar`, `depth-calibrate-contact`, `depth-clear-calibration`, `arm`, `disarm`, `open`, and `stop` to the existing action queue, conditionally display RGB/depth streams, and keep task text and plan progress in an isolated demo state.

- [ ] **Step 5: Preserve safety truthfulness**

Never set a real action to success before the next status response. When `emergency_stopped` is true, disable motion controls, show the restart requirement, and omit any client-side unlock handler.

- [ ] **Step 6: Add demo-only interactions**

Implement page-local Agent plan preview, task record selection, device refresh display, and settings selection without sending unsupported API actions. Every such surface retains its demo label.

- [ ] **Step 7: Run all unit tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all endpoint and static contract tests pass.

### Task 5: Verify Syntax and Runtime Behavior

**Files:**
- Verify: `web/index.html`
- Verify: `web/styles.css`
- Verify: `web/app.js`
- Verify: `web_console.py`

- [ ] **Step 1: Run static syntax checks**

Run:

```bash
node --check web/app.js
python -m py_compile web_console.py
```

Expected: both commands exit 0.

- [ ] **Step 2: Start the dry-run server**

Run:

```bash
python web_console.py --dry-run --host 127.0.0.1 --port 8765
```

Expected: console reports `http://127.0.0.1:8765` and the browser loads the six-page shell.

- [ ] **Step 3: Verify the real action flow in dry-run mode**

Exercise left/right selection, hand-follow enable/pause, Mac/iPhone source selection, depth calibration controls, object mode arm/disarm, safe open, and emergency stop. Confirm each accepted action is followed by a matching status update and that emergency stop remains locked.

### Task 6: Responsive and Visual QA

**Files:**
- Modify if required: `web/index.html`
- Modify if required: `web/styles.css`
- Modify if required: `web/app.js`

- [ ] **Step 1: Capture desktop and mobile screenshots**

Check at 1440x900 and 390x844. Capture the home, hand-follow, and Agent/object pages at both widths.

- [ ] **Step 2: Inspect the responsive contract**

Confirm no horizontal overflow, camera visibility, readable control labels, minimum 44px mobile targets, fixed dock clearance, bottom navigation clearance, and no overlap with toasts or emergency messaging.

- [ ] **Step 3: Inspect the visual contract**

Confirm the page background is light, surfaces are white, dark color is limited to video content, cards use restrained radii, hand and Agent colors are distinct, and red appears only for genuine danger or failure.

- [ ] **Step 4: Verify offline degradation**

Stop the server after loading or block `/api/status`. Confirm all six pages remain navigable, real controls become unavailable, the connection state becomes offline, and demo pages remain viewable.

- [ ] **Step 5: Run the final verification suite**

Run the full unit tests, JavaScript syntax check, Python compile check, and repeat the primary desktop/mobile browser flow. Expected: no failures and no unresolved visual overlap.

## Plan Self-Review

- Spec coverage: all six pages, real action mappings, demo boundaries, light palette, responsive layout, safety lock, offline behavior, backup, and browser QA are covered.
- Placeholder scan: no TBD, TODO, or unspecified implementation steps remain.
- Type consistency: action names match `ALLOWED_ACTIONS`; status names match the existing `/api/status` payload; DOM hooks are defined before the adapter tasks use them.
- Repository constraint: the repository has unrelated user changes, so the plan does not create commits automatically. The timestamped web backup is the direct rollback mechanism.
