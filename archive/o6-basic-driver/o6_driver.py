#!/usr/bin/env python3
"""Minimal, safety-gated LinkerHand O6 left-hand CAN driver."""

from __future__ import annotations

import argparse
import ctypes.util
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

try:
    import can
except ImportError:  # `doctor` can still explain how to install dependencies.
    can = None


HAND_ID_LEFT = 0x28
BITRATE = 1_000_000
JOINT_NAMES = (
    "thumb_pitch",
    "thumb_yaw",
    "index_pitch",
    "middle_pitch",
    "ring_pitch",
    "little_pitch",
)

# From linker-bot/linkerhand-python-sdk, O6 GUI presets.
GESTURES: Dict[str, List[int]] = {
    "open": [250, 250, 250, 250, 250, 250],
    "five": [255, 255, 255, 255, 255, 255],
    "fist": [102, 18, 0, 0, 0, 0],
    "one": [125, 18, 255, 0, 0, 0],
    "two": [92, 87, 255, 255, 0, 0],
    "three": [92, 87, 255, 255, 255, 0],
    "four": [92, 87, 255, 255, 255, 255],
    "ok": [96, 100, 118, 250, 250, 250],
    "thumbs_up": [250, 79, 0, 0, 0, 0],
}

QUERY_COMMANDS = {
    "position": 0x01,
    "torque": 0x02,
    "speed": 0x05,
    "temperature": 0x33,
    "fault": 0x35,
    "current": 0x36,
}


def six_uint8(values: Iterable[int], label: str = "values") -> List[int]:
    result = [int(value) for value in values]
    if len(result) != 6:
        raise ValueError(f"{label} must contain exactly 6 values")
    if any(value < 0 or value > 255 for value in result):
        raise ValueError(f"every {label} value must be in 0..255")
    return result


def six_or_scalar(values: Iterable[int], label: str = "values") -> List[int]:
    """Accept either one value for all joints or six per-joint values."""
    result = [int(value) for value in values]
    if len(result) == 1:
        result *= 6
    return six_uint8(result, label)


def interpolate(start: Sequence[int], target: Sequence[int], max_step: int) -> List[List[int]]:
    """Build a bounded-step path, excluding start and including target."""
    start_values = six_uint8(start, "start")
    target_values = six_uint8(target, "target")
    if max_step < 1:
        raise ValueError("max_step must be at least 1")
    largest_delta = max(abs(a - b) for a, b in zip(start_values, target_values))
    steps = max(1, math.ceil(largest_delta / max_step))
    path = []
    for index in range(1, steps + 1):
        ratio = index / steps
        point = [round(a + (b - a) * ratio) for a, b in zip(start_values, target_values)]
        if not path or point != path[-1]:
            path.append(point)
    return path


def four_finger_wave_position(
    elapsed: float,
    *,
    duration: float,
    frequency: float,
    amplitude: int,
    phase_delay: float,
    ramp_time: float,
) -> List[int]:
    """Return an O6 pose for a four-finger travelling wave with soft edges."""
    if duration <= 0 or frequency <= 0 or not 1 <= amplitude <= 250:
        raise ValueError("invalid wave duration, frequency, or amplitude")
    if phase_delay < 0 or ramp_time <= 0:
        raise ValueError("phase_delay must be non-negative and ramp_time must be positive")
    t = max(0.0, min(float(elapsed), duration))
    envelope = min(1.0, t / ramp_time, (duration - t) / ramp_time)
    envelope = max(0.0, envelope)
    pose = [250, 250]
    for finger_index in range(4):
        phase_t = t - finger_index * phase_delay
        contraction = 0.5 - 0.5 * math.cos(2.0 * math.pi * frequency * phase_t)
        value = round(250 - amplitude * envelope * contraction)
        pose.append(max(0, min(255, value)))
    return pose


class O6CanDriver:
    """Small subset of the official O6 protocol on a python-can bus."""

    def __init__(
        self,
        interface: str,
        channel: str,
        *,
        bus=None,
        execute: bool = False,
        timeout: float = 0.35,
    ) -> None:
        self.interface = interface
        self.channel = channel
        self.execute = execute
        self.timeout = timeout
        self.bus = bus

    def __enter__(self) -> "O6CanDriver":
        if self.execute and self.bus is None:
            if can is None:
                raise RuntimeError("python-can is not installed; run: pip install -r requirements.txt")
            try:
                self.bus = can.Bus(
                    interface=self.interface,
                    channel=self.channel,
                    bitrate=BITRATE,
                    receive_own_messages=False,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"cannot open CAN backend {self.interface}/{self.channel}: {exc}"
                ) from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.bus is not None and hasattr(self.bus, "shutdown"):
            self.bus.shutdown()

    @staticmethod
    def _frame(command: int, payload: Sequence[int] = ()):
        data = [command] + [int(value) for value in payload]
        if len(data) > 8:
            raise ValueError("classic CAN frames can contain at most 8 bytes")
        if can is None:
            return {"arbitration_id": HAND_ID_LEFT, "data": data}
        return can.Message(
            arbitration_id=HAND_ID_LEFT,
            data=data,
            is_extended_id=False,
        )

    def send(self, command: int, payload: Sequence[int] = ()) -> None:
        payload_values = [int(value) for value in payload]
        if any(value < 0 or value > 255 for value in payload_values):
            raise ValueError("CAN payload bytes must be in 0..255")
        if not self.execute:
            print(
                f"DRY-RUN can_id=0x{HAND_ID_LEFT:02X} "
                f"data={[command] + payload_values}"
            )
            return
        if self.bus is None:
            raise RuntimeError("CAN bus is not open")
        self.bus.send(self._frame(command, payload_values), timeout=self.timeout)

    def request(self, command: int, *, timeout: Optional[float] = None) -> List[int]:
        if not self.execute:
            raise RuntimeError("read operations require a live CAN bus")
        if self.bus is None:
            raise RuntimeError("CAN bus is not open")
        self.send(command)
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            message = self.bus.recv(timeout=max(0.0, deadline - time.monotonic()))
            if message is None:
                break
            data = list(message.data)
            if message.arbitration_id == HAND_ID_LEFT and data and data[0] == command:
                return data[1:]
        raise TimeoutError(f"O6 did not answer command 0x{command:02X}")

    def set_speed(self, values: Sequence[int]) -> None:
        values = six_uint8(values, "speed")
        # The official O6 implementation sends speed twice.
        self.send(0x05, values)
        if self.execute:
            time.sleep(0.002)
        self.send(0x05, values)

    def set_torque(self, values: Sequence[int]) -> None:
        self.send(0x02, six_uint8(values, "torque"))

    def move(self, values: Sequence[int]) -> None:
        self.send(0x01, six_uint8(values, "position"))

    def move_safely(
        self,
        target: Sequence[int],
        *,
        speed: Sequence[int],
        torque: Sequence[int],
        max_step: int,
        interval: float,
        settle_timeout: float = 15.0,
        tolerance: int = 5,
    ) -> None:
        target_values = six_uint8(target, "position")
        speed_values = six_uint8(speed, "speed")
        torque_values = six_uint8(torque, "torque")
        if interval < 0.01:
            raise ValueError("interval must be at least 0.01 seconds")

        self.set_speed(speed_values)
        self.set_torque(torque_values)

        if self.execute:
            start = self.request(QUERY_COMMANDS["position"], timeout=0.6)
            if len(start) != 6:
                raise RuntimeError(f"invalid O6 position response: {start!r}; motion aborted")
        else:
            # Dry-run shows the destination frame without inventing a current pose.
            print("DRY-RUN ramp starts from the live position (queried only with --execute)")
            self.move(target_values)
            return

        for point in interpolate(start, target_values, max_step):
            self.move(point)
            time.sleep(interval)
        self.wait_until_reached(
            target_values,
            timeout=settle_timeout,
            tolerance=tolerance,
        )

    def wait_until_reached(
        self,
        target: Sequence[int],
        *,
        timeout: float = 15.0,
        tolerance: int = 5,
        poll_interval: float = 0.2,
        temperature_limit: int = 55,
    ) -> List[int]:
        """Wait for two consecutive healthy samples near the requested target."""
        target_values = six_uint8(target, "position")
        if not self.execute:
            raise RuntimeError("settling checks require a live CAN bus")
        if timeout <= 0 or tolerance < 0 or poll_interval < 0.05:
            raise ValueError("invalid settling-check parameters")

        deadline = time.monotonic() + timeout
        stable_samples = 0
        last_position: List[int] = []
        while time.monotonic() < deadline:
            last_position = self.request(0x01, timeout=min(0.6, self.timeout + 0.2))
            temperature = self.request(0x33, timeout=min(0.6, self.timeout + 0.2))
            fault = self.request(0x35, timeout=min(0.6, self.timeout + 0.2))
            if fault != [0] * 6:
                raise RuntimeError(f"O6 fault while moving: {fault}")
            if len(temperature) != 6 or max(temperature) >= temperature_limit:
                raise RuntimeError(f"O6 temperature gate failed: {temperature}")
            if len(last_position) != 6:
                raise RuntimeError(f"invalid O6 position response: {last_position}")

            error = max(abs(actual - expected) for actual, expected in zip(last_position, target_values))
            stable_samples = stable_samples + 1 if error <= tolerance else 0
            if stable_samples >= 2:
                return last_position
            time.sleep(poll_interval)
        raise TimeoutError(
            f"O6 did not settle near {target_values} within {timeout:.1f}s; "
            f"last position was {last_position}"
        )

    def read_status(self) -> Dict[str, object]:
        status: Dict[str, object] = {}
        try:
            status["version"] = self.request(0x64, timeout=0.4)
        except TimeoutError:
            status["version"] = self.request(0xC2, timeout=0.4)
        for name, command in QUERY_COMMANDS.items():
            try:
                status[name] = self.request(command)
            except TimeoutError as exc:
                status[name] = {"error": str(exc)}
        return status


def defaults_for_host() -> tuple[str, str]:
    if sys.platform == "darwin":
        return "pcan", "PCAN_USBBUS1"
    return "socketcan", "can0"


def find_xcan_usb() -> Dict[str, object]:
    result: Dict[str, object] = {
        "expected_vid_pid": "0c72:000c",
        "detected": False,
    }
    try:
        import usb.core
        import usb.util

        device = usb.core.find(idVendor=0x0C72, idProduct=0x000C)
        if device is not None:
            result["detected"] = True
            try:
                result["product"] = usb.util.get_string(device, device.iProduct)
            except Exception:
                result["product"] = "XCAN-USB"
    except Exception as exc:
        result["probe_error"] = str(exc)
    return result


def doctor(interface: str, channel: str) -> int:
    report: Dict[str, object] = {
        "model": "LinkerHand O6 left",
        "can_id": f"0x{HAND_ID_LEFT:02X}",
        "bitrate": BITRATE,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "backend": {"interface": interface, "channel": channel},
        "xcan_usb": find_xcan_usb(),
        "python_can_installed": can is not None,
    }
    if sys.platform == "darwin":
        candidates = [
            Path("/usr/local/lib/libPCBUSB.dylib"),
            Path("/opt/homebrew/lib/libPCBUSB.dylib"),
        ]
        library = ctypes.util.find_library("PCBUSB")
        report["macos_pcan_library"] = library or next(
            (str(path) for path in candidates if path.exists()), None
        )
        report["ready"] = bool(
            report["xcan_usb"].get("detected")
            and report["python_can_installed"]
            and report["macos_pcan_library"]
        )
        report["note"] = (
            "The official LinkerHand SDK has no macOS CAN backend. "
            "A compatible PCBUSB user-space library is required for the pcan path."
        )
    else:
        can_path = Path("/sys/class/net") / channel
        report["socketcan_interface_exists"] = can_path.exists()
        report["ready"] = bool(report["python_can_installed"] and can_path.exists())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 2


def add_motion_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--speed",
        nargs="+",
        type=int,
        default=[50],
        help="one value for all joints, or six per-joint values (default: 50)",
    )
    parser.add_argument(
        "--torque",
        nargs="+",
        type=int,
        default=[80],
        help="one value for all joints, or six per-joint values (default: 80)",
    )
    parser.add_argument("--max-step", type=int, default=8)
    parser.add_argument("--interval", type=float, default=0.04)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually transmit CAN frames; without this flag only print a preview",
    )


def build_parser() -> argparse.ArgumentParser:
    default_interface, default_channel = defaults_for_host()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default=default_interface)
    parser.add_argument("--channel", default=default_channel)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="inspect host, USB-CAN, and backend readiness")
    subparsers.add_parser("status", help="read O6 version, position, and health data")

    gesture_parser = subparsers.add_parser("gesture", help="move to an official O6 preset")
    gesture_parser.add_argument("name", choices=sorted(GESTURES))
    add_motion_options(gesture_parser)

    move_parser = subparsers.add_parser("move", help="move to six raw 0..255 positions")
    move_parser.add_argument("position", nargs=6, type=int)
    add_motion_options(move_parser)

    finger_parser = subparsers.add_parser("finger", help="move one joint while retaining the others")
    finger_parser.add_argument("joint", choices=JOINT_NAMES)
    finger_parser.add_argument("position", type=int)
    add_motion_options(finger_parser)

    cycle_parser = subparsers.add_parser("cycle", help="repeat fist then open and finish open")
    cycle_parser.add_argument("--count", type=int, default=1)
    cycle_parser.add_argument("--hold", type=float, default=1.0)
    add_motion_options(cycle_parser)

    demo_parser = subparsers.add_parser(
        "demo",
        help="run open, fist, index 180, gestures one/two/three, then finish open",
    )
    demo_parser.add_argument("--hold", type=float, default=1.0)
    add_motion_options(demo_parser)

    wave_parser = subparsers.add_parser(
        "wave",
        help="run a phase-delayed four-finger travelling wave and finish open",
    )
    wave_parser.add_argument("--duration", type=float, default=5.0)
    wave_parser.add_argument("--frequency", type=float, default=0.8)
    wave_parser.add_argument("--amplitude", type=int, default=90)
    wave_parser.add_argument("--phase-delay", type=float, default=0.12)
    wave_parser.add_argument("--rate", type=float, default=25.0)
    add_motion_options(wave_parser)
    wave_parser.set_defaults(speed=[120], torque=[80], max_step=10, interval=0.04)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor(args.interface, args.channel)

    execute = args.command == "status" or args.execute
    try:
        with O6CanDriver(
            args.interface,
            args.channel,
            execute=execute,
        ) as driver:
            if args.command == "status":
                print(json.dumps(driver.read_status(), ensure_ascii=False, indent=2))
                return 0

            speed = six_or_scalar(args.speed, "speed")
            torque = six_or_scalar(args.torque, "torque")

            def run_target(label: str, target: Sequence[int], hold: float = 0.0) -> None:
                target_values = six_uint8(target, "position")
                print(f"{label}: target={target_values} speed={speed} torque={torque}")
                driver.move_safely(
                    target_values,
                    speed=speed,
                    torque=torque,
                    max_step=args.max_step,
                    interval=args.interval,
                )
                if execute and hold > 0:
                    time.sleep(hold)

            if args.command == "cycle":
                if args.count < 1 or args.count > 100:
                    raise ValueError("count must be in 1..100")
                if args.hold < 0:
                    raise ValueError("hold must not be negative")
                try:
                    for index in range(1, args.count + 1):
                        run_target(f"cycle {index}/{args.count} fist", GESTURES["fist"], args.hold)
                        run_target(f"cycle {index}/{args.count} open", GESTURES["open"], args.hold)
                finally:
                    if execute:
                        run_target("final open", GESTURES["open"])
                return 0

            if args.command == "demo":
                if args.hold < 0:
                    raise ValueError("hold must not be negative")
                sequence = [
                    ("open", GESTURES["open"]),
                    ("fist", GESTURES["fist"]),
                    ("open", GESTURES["open"]),
                    ("index 180", [250, 250, 180, 250, 250, 250]),
                    ("open", GESTURES["open"]),
                    ("one", GESTURES["one"]),
                    ("two", GESTURES["two"]),
                    ("three", GESTURES["three"]),
                    ("final open", GESTURES["open"]),
                ]
                try:
                    for label, target in sequence:
                        run_target(label, target, args.hold)
                finally:
                    if execute:
                        run_target("safety open", GESTURES["open"])
                return 0

            if args.command == "wave":
                if not 2.0 <= args.duration <= 60.0:
                    raise ValueError("wave duration must be in 2..60 seconds")
                if not 0.1 <= args.frequency <= 2.0:
                    raise ValueError("wave frequency must be in 0.1..2.0 Hz")
                if not 10 <= args.amplitude <= 250:
                    raise ValueError("wave amplitude must be in 10..250")
                if not 0.0 <= args.phase_delay <= 1.0:
                    raise ValueError("phase delay must be in 0..1 seconds")
                if not 10.0 <= args.rate <= 50.0:
                    raise ValueError("wave command rate must be in 10..50 Hz")
                ramp_time = min(1.0, args.duration / 4.0)
                print(
                    f"four-finger wave: duration={args.duration}s frequency={args.frequency}Hz "
                    f"amplitude={args.amplitude} phase_delay={args.phase_delay}s rate={args.rate}Hz "
                    f"speed={speed} torque={torque}"
                )
                if not execute:
                    sample_count = 8
                    for index in range(sample_count + 1):
                        elapsed = args.duration * index / sample_count
                        pose = four_finger_wave_position(
                            elapsed,
                            duration=args.duration,
                            frequency=args.frequency,
                            amplitude=args.amplitude,
                            phase_delay=args.phase_delay,
                            ramp_time=ramp_time,
                        )
                        print(f"DRY-RUN t={elapsed:.2f}s pose={pose}")
                    return 0

                run_target("wave initial open", GESTURES["open"])
                driver.set_speed(speed)
                driver.set_torque(torque)
                started = time.monotonic()
                next_health_check = started
                period = 1.0 / args.rate
                observed_min = [255] * 4
                try:
                    while True:
                        now = time.monotonic()
                        elapsed = now - started
                        if elapsed >= args.duration:
                            break
                        pose = four_finger_wave_position(
                            elapsed,
                            duration=args.duration,
                            frequency=args.frequency,
                            amplitude=args.amplitude,
                            phase_delay=args.phase_delay,
                            ramp_time=ramp_time,
                        )
                        driver.move(pose)
                        if now >= next_health_check:
                            position = driver.request(0x01, timeout=0.6)
                            temperature = driver.request(0x33, timeout=0.6)
                            fault = driver.request(0x35, timeout=0.6)
                            if len(position) != 6:
                                raise RuntimeError(f"invalid O6 position during wave: {position}")
                            observed_min = [
                                min(previous, actual)
                                for previous, actual in zip(observed_min, position[2:])
                            ]
                            if fault != [0] * 6:
                                raise RuntimeError(f"O6 fault during wave: {fault}")
                            if len(temperature) != 6 or max(temperature) >= 55:
                                raise RuntimeError(f"O6 temperature gate failed during wave: {temperature}")
                            next_health_check = now + 0.5
                        deadline = started + (math.floor(elapsed / period) + 1) * period
                        time.sleep(max(0.0, deadline - time.monotonic()))
                finally:
                    driver.set_speed([60] * 6)
                    driver.set_torque(torque)
                    driver.move(GESTURES["open"])
                    driver.wait_until_reached(GESTURES["open"], timeout=15, tolerance=6)
                print(
                    "four-finger wave complete; "
                    f"observed finger minima={observed_min}; hand returned open"
                )
                return 0

            if args.command == "finger":
                if not 0 <= args.position <= 255:
                    raise ValueError("finger position must be in 0..255")
                if execute:
                    target = driver.request(QUERY_COMMANDS["position"], timeout=0.6)
                    if len(target) != 6:
                        raise RuntimeError(f"invalid O6 position response: {target}")
                else:
                    print("DRY-RUN uses the open pose as the unknown live starting pose")
                    target = list(GESTURES["open"])
                target[JOINT_NAMES.index(args.joint)] = args.position
                run_target(f"finger {args.joint}", target)
                return 0

            target = GESTURES[args.name] if args.command == "gesture" else args.position
            print(
                f"O6 left target={six_uint8(target, 'position')} "
                f"speed={speed} torque={torque}"
            )
            driver.move_safely(
                target,
                speed=speed,
                torque=torque,
                max_step=args.max_step,
                interval=args.interval,
            )
        return 0
    except (RuntimeError, TimeoutError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
