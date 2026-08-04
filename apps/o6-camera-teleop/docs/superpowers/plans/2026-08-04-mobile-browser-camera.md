# Mobile Browser Camera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an iPhone Safari RGB camera source to the O6 web console with rear-camera default and safe disconnect behavior.

**Architecture:** The browser captures and sequentially uploads bounded JPEG frames. A capacity-one Python receiver feeds the existing frame source manager, keeping recognition and O6 output on the Mac. Flask serves trusted HTTPS on the LAN.

**Tech Stack:** Flask, OpenCV, vanilla JavaScript, MediaDevices API, OpenSSL

---

### Task 1: Mobile Frame Receiver

**Files:**
- Create: `vision/mobile_frame_receiver.py`
- Create: `tests/test_mobile_frame_receiver.py`

- [ ] Write tests for valid JPEG publication, newest-frame replacement, size validation, and one-second stale expiry.
- [ ] Run `.venv/bin/python -m unittest tests.test_mobile_frame_receiver -v` and confirm the new tests initially fail.
- [ ] Implement a lock-protected capacity-one receiver that decodes JPEG with OpenCV and returns only fresh BGR frames.
- [ ] Re-run the focused receiver tests and confirm they pass.

### Task 2: Runtime And Upload API

**Files:**
- Modify: `control/console_mode.py`
- Modify: `vision/frame_source.py`
- Modify: `web_console.py`
- Modify: `tests/test_web_depth_api.py`

- [ ] Add focused tests for selecting `mobile-camera`, rejecting invalid upload content, and accepting a bounded JPEG.
- [ ] Run the focused API tests and confirm the new assertions fail.
- [ ] Add `MOBILE_CAMERA`, wire the receiver into `FrameSourceManager`, expose `/api/mobile-frame`, and report stream freshness in status.
- [ ] Pause following and send safe-open when the selected mobile stream expires.
- [ ] Re-run the focused API and runtime tests.

### Task 3: Mobile Capture Controls

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`

- [ ] Add the `手机相机` source option and compact start, switch, and stop controls.
- [ ] Implement rear-camera-first `getUserMedia`, canvas JPEG encoding, one-request-at-a-time uploads, and clear permission/HTTPS errors.
- [ ] Stop media tracks on explicit stop, page hide, or source change.
- [ ] Verify that the existing responsive layout remains intact at phone width.

### Task 4: LAN HTTPS And Focused Verification

**Files:**
- Modify: `web_console.py`
- Modify: `run_web.sh`
- Modify: `README.md`
- Create: `tools/create_lan_certificate.sh`

- [ ] Add optional certificate and key arguments to the web runner.
- [ ] Generate a local CA and LAN-IP certificate with OpenSSL using explicit project paths.
- [ ] Document the one-time iPhone certificate installation and trust steps.
- [ ] Run focused unit tests, start the real controller on HTTPS, and verify status plus one uploaded frame.
