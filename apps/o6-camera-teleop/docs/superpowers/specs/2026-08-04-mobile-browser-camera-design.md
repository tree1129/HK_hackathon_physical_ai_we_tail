# Mobile Browser Camera Design

## Goal

Allow an iPhone on the same Wi-Fi to use Safari and the existing O6 console as a live RGB camera source for gesture following and RGB object recognition.

## Design

The mobile page requests `getUserMedia` only after an explicit button press, defaults to `facingMode: environment`, and offers camera switching and stop controls. A hidden canvas scales frames to 640x480 and sends JPEG blobs sequentially at up to 12 FPS so slow requests cannot accumulate.

Flask accepts same-origin JPEG uploads into a thread-safe, capacity-one mobile frame receiver. `FrameSourceManager` exposes this receiver as `mobile-camera`; the existing MediaPipe tracking, annotation, command filtering, and O6 controller remain unchanged. Only the newest fresh frame is processed.

The control console is served over trusted HTTPS because iOS Safari exposes camera capture only in a secure context. A local development certificate includes the Mac LAN IP. The user installs and trusts its local root certificate once on the iPhone.

## Interface

- Add `手机相机` to the RGB input selector.
- On mobile, show `启动手机相机`, `切换镜头`, and `停止采集` near the live video workspace.
- Display upload state and errors without blocking the safety controls.
- The rear camera is the default; front camera remains optional.

## Safety And Failure Handling

- JPEG uploads have a strict content type and byte limit.
- Only one fresh frame is retained; stale frames expire after one second.
- Switching away from the mobile source or losing the stream pauses gesture following and sends the configured safe-open pose.
- Mobile RGB does not provide LiDAR depth and cannot satisfy depth-grasp safety gates.
- Existing emergency stop behavior is unchanged.

## Verification

- Unit-test upload validation, latest-frame replacement, and stale-frame expiry.
- Exercise the upload API with a valid JPEG and confirm status reports `mobile-camera` and a fresh stream.
- Confirm the HTTPS server binds to the LAN interface and Safari can request the rear camera after the certificate is trusted.
