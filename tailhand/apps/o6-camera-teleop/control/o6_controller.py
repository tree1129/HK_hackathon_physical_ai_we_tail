from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any


def _pose6(values: list[int], label: str = "pose") -> list[int]:
    pose = [int(value) for value in values]
    if len(pose) != 6:
        raise ValueError(f"{label} must contain exactly 6 values")
    if any(value < 0 or value > 255 for value in pose):
        raise ValueError(f"all {label} values must be in 0..255")
    return pose


def _resolve_can_id(hand_type: str, configured: int | str | None) -> int:
    if configured is None:
        return 0x28 if hand_type == "left" else 0x27
    can_id = int(configured, 0) if isinstance(configured, str) else int(configured)
    if can_id not in (0x27, 0x28):
        raise ValueError("O6 can_id must be 0x27 or 0x28")
    return can_id


class _MacPcanO6:
    """Minimal official O6 CAN frame protocol for the SDK's missing Darwin backend."""

    def __init__(
        self,
        hand_type: str,
        channel: str,
        bitrate: int = 1_000_000,
        can_id: int | str | None = None,
    ) -> None:
        import can

        self._can = can
        self.hand_id = _resolve_can_id(hand_type, can_id)
        self.bus = can.Bus(
            interface="pcan",
            channel=channel,
            bitrate=bitrate,
            receive_own_messages=False,
        )

    def _send(self, command: int, values: list[int] | None = None) -> None:
        message = self._can.Message(
            arbitration_id=self.hand_id,
            data=[command] + (values or []),
            is_extended_id=False,
        )
        self.bus.send(message, timeout=0.2)

    def move(self, pose: list[int]) -> None:
        self._send(0x01, _pose6(pose))

    def set_speed(self, values: list[int]) -> None:
        values = _pose6(values, "speed")
        self._send(0x05, values)
        time.sleep(0.002)
        self._send(0x05, values)

    def get_state(self) -> list[int] | None:
        self._send(0x01)
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline:
            message = self.bus.recv(timeout=max(0.0, deadline - time.monotonic()))
            data = list(message.data) if message is not None else []
            if message is not None and message.arbitration_id == self.hand_id and data[:1] == [0x01]:
                return data[1:7]
        return None

    def close(self) -> None:
        self.bus.shutdown()


class O6Controller:
    def __init__(self, config: dict[str, Any], project_dir: Path, dry_run: bool) -> None:
        self.config = config
        self.project_dir = project_dir
        self.requested_dry_run = bool(dry_run)
        self.dry_run = self.requested_dry_run
        self.connected = False
        self.backend = "dry-run"
        self.fallback_reason: str | None = None
        self._device: Any = None
        self._emergency_stopped = False

    def connect(self) -> None:
        self.dry_run = self.requested_dry_run
        self.connected = False
        self.backend = "dry-run"
        self.fallback_reason = None
        if self.dry_run:
            print("O6 controller: dry-run (hardware connection skipped)")
            return
        try:
            use_mac_pcan = (
                sys.platform == "darwin"
                and str(self.config.get("modbus", "None")) == "None"
                and self.config.get("backend", "auto") in ("auto", "mac_pcan")
            )
            if use_mac_pcan:
                candidate = _MacPcanO6(
                    hand_type=self.config["hand_type"],
                    channel=self.config.get("can_channel", "PCAN_USBBUS1"),
                    can_id=self.config.get("can_id"),
                )
                initial_state = None
                for _ in range(3):
                    initial_state = candidate.get_state()
                    if initial_state is not None and len(initial_state) == 6:
                        break
                    time.sleep(0.2)
                if initial_state is None or len(initial_state) != 6:
                    candidate.close()
                    raise ConnectionError(
                        "PCAN adapter opened, but O6 did not return a 6-value state; "
                        "check hand power and CAN wiring"
                    )
                self._device = candidate
                self.backend = "mac-pcan-o6"
            else:
                sdk_path = (self.project_dir / self.config["sdk_path"]).resolve()
                if str(sdk_path) not in sys.path:
                    sys.path.insert(0, str(sdk_path))
                from LinkerHand.linker_hand_api import LinkerHandApi

                self._device = LinkerHandApi(
                    hand_type=self.config["hand_type"],
                    hand_joint="O6",
                    modbus=str(self.config.get("modbus", "None")),
                    can=str(self.config.get("can_channel", "can0")),
                )
                self.backend = "official-linkerhand-sdk"
            self.connected = True
            print(f"O6 controller connected: backend={self.backend}")
        except BaseException as exc:
            self.fallback_reason = f"{type(exc).__name__}: {exc}"
            self._device = None
            self.connected = False
            self.dry_run = True
            self.backend = "dry-run-fallback"
            print("ERROR: O6 hardware initialization failed; falling back to dry-run.")
            print(f"ERROR detail: {self.fallback_reason}")
            print("No hardware command will be sent.")

    def reconnect_hand(self, hand_type: str) -> None:
        if hand_type not in ("left", "right"):
            raise ValueError("hand_type must be left or right")
        if self._emergency_stopped:
            raise RuntimeError("emergency stop is latched; restart before reconnecting")
        self.close()
        self.config["hand_type"] = hand_type
        self.connect()

    def set_speed(self, values: list[int]) -> None:
        values = _pose6(values, "speed")
        if self.dry_run:
            print(f"O6 speed: {values} (dry-run)")
        elif self.backend == "mac-pcan-o6":
            self._device.set_speed(values)
        else:
            self._device.set_speed(speed=values)

    def move(self, pose: list[int]) -> None:
        pose = _pose6(pose)
        if self._emergency_stopped:
            return
        self._send_pose(pose)

    def get_state(self) -> list[int] | None:
        if self.dry_run or self._device is None:
            return None
        try:
            state = self._device.get_state()
            return _pose6(state, "state") if state is not None else None
        except Exception as exc:
            print(f"WARNING: O6 get_state failed: {exc}")
            return None

    def emergency_stop(self) -> None:
        self._emergency_stopped = True
        print("EMERGENCY STOP: command output latched off")

    def send_safe_open(self, pose: list[int]) -> None:
        """One explicit safe-open command, even after an emergency latch."""
        self._send_pose(_pose6(pose))

    def close(self) -> None:
        device, self._device = self._device, None
        self.connected = False
        if device is None:
            return
        try:
            if self.backend == "mac-pcan-o6":
                device.close()
                return
            hand = getattr(device, "hand", None)
            if hand is not None and hasattr(hand, "close_can_interface"):
                hand.close_can_interface()
            elif hand is not None and hasattr(hand, "close"):
                hand.close()
            elif hasattr(device, "close_can"):
                device.close_can()
        except Exception as exc:
            print(f"WARNING: O6 close failed: {exc}")

    @property
    def emergency_stopped(self) -> bool:
        return self._emergency_stopped

    def _send_pose(self, pose: list[int]) -> None:
        if self.dry_run:
            print(f"O6 pose: {pose}")
        elif self.backend == "mac-pcan-o6":
            self._device.move(pose)
        else:
            self._device.finger_move(pose=pose)
