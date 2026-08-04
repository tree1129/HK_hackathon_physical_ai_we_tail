from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import math
import secrets
import socket
import threading
import time
from typing import Optional

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from vision.depth_protocol import DepthFrame, DepthProtocolError, PROTOCOL_VERSION, parse_depth_frame


_HELLO_FIELDS = frozenset((
    "type",
    "protocol_version",
    "pairing_code",
    "device_name",
    "supports_scene_depth",
))
_MAX_HELLO_BYTES = 4096
_MAX_DEVICE_LENGTH = 128
_MAX_CODE_LENGTH = 128
_MAX_ERROR_LENGTH = 160


class PairingError(ValueError):
    """Raised when a client or frame cannot join the active paired session."""


@dataclass(frozen=True)
class DepthHello:
    pairing_code: str
    device_name: str


@dataclass(frozen=True)
class DepthStateSnapshot:
    connected: bool
    device: Optional[str]
    latest_sequence: Optional[int]
    fresh: bool
    latest_age_seconds: Optional[float]


@dataclass(frozen=True)
class DepthReceiverStatus:
    running: bool
    listening_host: Optional[str]
    listening_port: Optional[int]
    connected: bool
    connected_device: Optional[str]
    depth_latency_ms: Optional[float]
    last_frame_sequence: Optional[int]
    last_frame_age_ms: Optional[float]
    last_error: Optional[str]
    bonjour_state: str
    bonjour_error: Optional[str]


def validate_hello(message: object) -> DepthHello:
    """Validate the first WebSocket message without echoing untrusted input."""
    if not isinstance(message, str):
        raise PairingError("hello must be a text JSON message")
    try:
        encoded_length = len(message.encode("utf-8"))
    except UnicodeError:
        raise PairingError("invalid hello text") from None
    if encoded_length > _MAX_HELLO_BYTES:
        raise PairingError("hello message exceeds size limit")
    try:
        payload = json.loads(message)
    except (TypeError, ValueError, RecursionError):
        raise PairingError("invalid hello JSON") from None
    if not isinstance(payload, dict) or frozenset(payload) != _HELLO_FIELDS:
        raise PairingError("hello fields do not match protocol")
    if payload["type"] != "hello":
        raise PairingError("invalid hello message type")
    version = payload["protocol_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
        raise PairingError("unsupported hello protocol version")
    if payload["supports_scene_depth"] is not True:
        raise PairingError("scene depth support is required")
    device = _bounded_nonempty_string(payload["device_name"], "device name", _MAX_DEVICE_LENGTH)
    code = _bounded_nonempty_string(payload["pairing_code"], "pairing code", _MAX_CODE_LENGTH)
    return DepthHello(pairing_code=code, device_name=device)


class DepthReceiverState:
    """Thread-safe, capacity-one frame state for a single paired client."""

    def __init__(self, pairing_code: str, timeout_seconds: float) -> None:
        self._pairing_code = _constructor_string(pairing_code, "pairing_code", _MAX_CODE_LENGTH)
        self._timeout_seconds = _finite_positive(timeout_seconds, "timeout_seconds")
        self._lock = threading.Lock()
        self._client: Optional[str] = None
        self._latest: Optional[DepthFrame] = None
        self._last_sequence = -1

    @property
    def pairing_code(self) -> str:
        return self._pairing_code

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._client is not None

    @property
    def device(self) -> Optional[str]:
        with self._lock:
            return self._client

    @property
    def latest_sequence(self) -> Optional[int]:
        with self._lock:
            return None if self._last_sequence < 0 else self._last_sequence

    def connect(self, device: object, code: object) -> None:
        try:
            checked_device = _pairing_string(device, "device name", _MAX_DEVICE_LENGTH)
            checked_code = _pairing_string(code, "pairing code", _MAX_CODE_LENGTH)
        except PairingError:
            raise
        with self._lock:
            if not secrets.compare_digest(
                checked_code.encode("utf-8"),
                self._pairing_code.encode("utf-8"),
            ):
                raise PairingError("invalid pairing code")
            if self._client is not None:
                raise PairingError("another iPhone is already connected")
            self._client = checked_device
            self._latest = None
            self._last_sequence = -1

    def accept(self, frame: DepthFrame) -> None:
        with self._lock:
            if self._client is None:
                raise PairingError("no paired client is connected")
            sequence = getattr(frame, "sequence", None)
            if (
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 0
                or sequence <= self._last_sequence
            ):
                raise PairingError("invalid frame sequence")
            self._latest = frame
            self._last_sequence = sequence

    def latest(self, now: object) -> Optional[DepthFrame]:
        with self._lock:
            frame = self._latest
            if frame is None:
                return None
            age = _frame_age(now, getattr(frame, "received_monotonic", None))
            if age is None or age > self._timeout_seconds:
                return None
            return frame

    def is_fresh(self, now: object) -> bool:
        return self.latest(now) is not None

    def snapshot(self, now: object) -> DepthStateSnapshot:
        with self._lock:
            frame = self._latest
            age = None if frame is None else _frame_age(now, getattr(frame, "received_monotonic", None))
            fresh = age is not None and age <= self._timeout_seconds
            return DepthStateSnapshot(
                connected=self._client is not None,
                device=self._client,
                latest_sequence=None if self._last_sequence < 0 else self._last_sequence,
                fresh=fresh,
                latest_age_seconds=age,
            )

    def disconnect(self) -> None:
        with self._lock:
            self._client = None
            self._latest = None
            self._last_sequence = -1


class DepthReceiver:
    """Paired RGB-D WebSocket server running on a bounded daemon thread.

    Bonjour advertisement failure is non-fatal because clients can still use the
    listening host and port directly. The degraded state is exposed by status().
    """

    def __init__(
        self,
        pairing_code: str,
        *,
        host: str = "127.0.0.1",
        port: int = 8766,
        timeout_seconds: float = 0.5,
        max_message_bytes: int = 1_572_864,
        max_fps: float = 20.0,
        advertise_bonjour: bool = True,
        service_name: str = "_o6depth._tcp.local.",
        startup_timeout_seconds: float = 5.0,
        stop_timeout_seconds: float = 5.0,
        hello_timeout_seconds: float = 5.0,
    ) -> None:
        self.state = DepthReceiverState(pairing_code, timeout_seconds)
        self.host = _constructor_string(host, "host", 255)
        self.port = _port(port)
        self.max_message_bytes = _positive_integer(max_message_bytes, "max_message_bytes")
        self.max_fps = _finite_positive(max_fps, "max_fps")
        if not isinstance(advertise_bonjour, bool):
            raise ValueError("advertise_bonjour must be a boolean")
        self.advertise_bonjour = advertise_bonjour
        self.service_type = _service_type(service_name)
        self.startup_timeout_seconds = _finite_positive(startup_timeout_seconds, "startup_timeout_seconds")
        self.stop_timeout_seconds = _finite_positive(stop_timeout_seconds, "stop_timeout_seconds")
        self.hello_timeout_seconds = _finite_positive(hello_timeout_seconds, "hello_timeout_seconds")

        self._lifecycle_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._startup_event = threading.Event()
        self._startup_error: Optional[str] = None
        self._running = False
        self._listening_host: Optional[str] = None
        self._listening_port: Optional[int] = None
        self._latency_ms: Optional[float] = None
        self._last_error: Optional[str] = None
        self._bonjour_state = "disabled" if not advertise_bonjour else "stopped"
        self._bonjour_error: Optional[str] = None
        self._zeroconf: Optional[AsyncZeroconf] = None
        self._service_info: Optional[ServiceInfo] = None

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._startup_event = threading.Event()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._thread_main,
                name="o6-depth-receiver",
                daemon=True,
            )
            thread = self._thread
            thread.start()
            if not self._startup_event.wait(self.startup_timeout_seconds):
                self._request_stop()
                thread.join(self.stop_timeout_seconds)
                if thread.is_alive():
                    raise RuntimeError("depth receiver startup timed out and did not stop")
                self._thread = None
                raise RuntimeError("depth receiver startup timed out")
            if self._startup_error is not None:
                thread.join(self.stop_timeout_seconds)
                self._thread = None
                raise RuntimeError(self._startup_error)

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._request_stop()
            thread.join(self.stop_timeout_seconds)
            if thread.is_alive():
                self._set_error("depth receiver stop timed out")
                raise RuntimeError("depth receiver stop timed out")
            self._thread = None

    def latest(self, now: Optional[float] = None) -> Optional[DepthFrame]:
        return self.state.latest(time.monotonic() if now is None else now)

    def status(self, now: Optional[float] = None) -> DepthReceiverStatus:
        current = time.monotonic() if now is None else now
        state = self.state.snapshot(current)
        with self._status_lock:
            return DepthReceiverStatus(
                running=self._running,
                listening_host=self._listening_host,
                listening_port=self._listening_port,
                connected=state.connected,
                connected_device=state.device,
                depth_latency_ms=self._latency_ms,
                last_frame_sequence=state.latest_sequence,
                last_frame_age_ms=(
                    None if state.latest_age_seconds is None else state.latest_age_seconds * 1000.0
                ),
                last_error=self._last_error,
                bonjour_state=self._bonjour_state,
                bonjour_error=self._bonjour_error,
            )

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            error = _bounded_error("depth receiver failed", exc)
            self._startup_error = self._startup_error or error
            self._set_error(error)
        finally:
            self._startup_event.set()

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        bonjour_task: Optional[asyncio.Task] = None
        try:
            async with serve(
                self._handle_client,
                self.host,
                self.port,
                ping_interval=2.0,
                ping_timeout=2.0,
                close_timeout=1.0,
                max_size=self.max_message_bytes,
                max_queue=1,
                compression=None,
            ) as server:
                bound_host, bound_port = _server_address(server.sockets, self.host)
                with self._status_lock:
                    self._running = True
                    self._listening_host = bound_host
                    self._listening_port = bound_port
                    self._last_error = None
                    if self.advertise_bonjour:
                        self._bonjour_state = "starting"
                        self._bonjour_error = None
                self._startup_event.set()
                if self.advertise_bonjour:
                    bonjour_task = asyncio.create_task(self._publish_bonjour(bound_host, bound_port))
                await self._stop_event.wait()
        except Exception as exc:
            error = _bounded_error("depth receiver listen failed", exc)
            self._startup_error = error
            self._set_error(error)
            raise
        finally:
            if bonjour_task is not None and not bonjour_task.done():
                bonjour_task.cancel()
            if bonjour_task is not None:
                try:
                    await bonjour_task
                except asyncio.CancelledError:
                    pass
            await self._cleanup_bonjour()
            self.state.disconnect()
            with self._status_lock:
                self._running = False
                self._listening_host = None
                self._listening_port = None
                self._latency_ms = None
            self._loop = None
            self._stop_event = None
            self._startup_event.set()

    async def _handle_client(self, websocket: ServerConnection) -> None:
        paired = False
        latency_task: Optional[asyncio.Task] = None
        try:
            try:
                first = await asyncio.wait_for(websocket.recv(), timeout=self.hello_timeout_seconds)
                parsed = validate_hello(first)
                self.state.connect(parsed.device_name, parsed.pairing_code)
                paired = True
            except (asyncio.TimeoutError, ConnectionClosed, PairingError):
                await self._reject(websocket)
                return

            await websocket.send(_hello_ack(True))
            latency_task = asyncio.create_task(self._publish_latency(websocket))
            recent_frames = deque()
            last_device_timestamp = -1
            async for message in websocket:
                received = time.monotonic()
                if not isinstance(message, bytes):
                    raise PairingError("depth frames must be binary")
                recent_frames.append(received)
                while recent_frames and received - recent_frames[0] >= 1.0:
                    recent_frames.popleft()
                if len(recent_frames) > math.ceil(self.max_fps):
                    raise PairingError("depth frame rate exceeds limit")
                frame = parse_depth_frame(
                    message,
                    received_monotonic=received,
                    max_message_bytes=self.max_message_bytes,
                )
                if frame.timestamp_ns < last_device_timestamp:
                    raise PairingError("device timestamp moved backwards")
                last_device_timestamp = frame.timestamp_ns
                self.state.accept(frame)
                self._read_latency(websocket)
        except ConnectionClosed:
            pass
        except (DepthProtocolError, PairingError):
            self._set_error("depth stream rejected")
            await websocket.close(code=1008, reason="depth stream rejected")
        except Exception:
            self._set_error("depth stream connection failed")
            await websocket.close(code=1011, reason="receiver error")
        finally:
            if latency_task is not None:
                latency_task.cancel()
                try:
                    await latency_task
                except asyncio.CancelledError:
                    pass
            if paired:
                self.state.disconnect()
                with self._status_lock:
                    self._latency_ms = None

    async def _reject(self, websocket: ServerConnection) -> None:
        try:
            await websocket.send(_hello_ack(False))
        except ConnectionClosed:
            return
        await websocket.close(code=1008, reason="pairing rejected")

    async def _publish_latency(self, websocket: ServerConnection) -> None:
        while True:
            self._read_latency(websocket)
            await asyncio.sleep(0.25)

    def _read_latency(self, websocket: ServerConnection) -> None:
        latency = getattr(websocket, "latency", None)
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            value = float(latency)
            if math.isfinite(value) and value >= 0.0:
                with self._status_lock:
                    self._latency_ms = value * 1000.0

    def _request_stop(self) -> None:
        loop = self._loop
        event = self._stop_event
        if loop is not None and event is not None and loop.is_running():
            loop.call_soon_threadsafe(event.set)

    async def _publish_bonjour(self, host: str, port: int) -> None:
        if not self.advertise_bonjour:
            return
        try:
            addresses = [socket.inet_aton(address) for address in _advertised_addresses(host)]
            server_name = f"{socket.gethostname().rstrip('.')}.local."
            instance = f"O6 Depth Receiver.{self.service_type}"
            info = ServiceInfo(
                self.service_type,
                instance,
                addresses=addresses,
                port=port,
                properties={"protocol_version": str(PROTOCOL_VERSION)},
                server=server_name,
            )
            zeroconf = AsyncZeroconf()
            self._zeroconf = zeroconf
            self._service_info = info
            await zeroconf.async_register_service(info, allow_name_change=True)
            with self._status_lock:
                self._bonjour_state = "published"
        except Exception as exc:
            error = _bounded_error("Bonjour unavailable", exc)
            await self._cleanup_bonjour()
            with self._status_lock:
                self._bonjour_state = "failed"
                self._bonjour_error = error

    async def _cleanup_bonjour(self) -> None:
        zeroconf = self._zeroconf
        info = self._service_info
        self._zeroconf = None
        self._service_info = None
        if zeroconf is not None:
            try:
                if info is not None:
                    await asyncio.wait_for(
                        zeroconf.async_unregister_service(info),
                        timeout=min(2.0, self.stop_timeout_seconds),
                    )
            except Exception:
                pass
            finally:
                try:
                    await asyncio.wait_for(
                        zeroconf.async_close(),
                        timeout=min(2.0, self.stop_timeout_seconds),
                    )
                except Exception:
                    pass
        with self._status_lock:
            if self.advertise_bonjour and self._bonjour_state != "failed":
                self._bonjour_state = "stopped"

    def _set_error(self, message: str) -> None:
        with self._status_lock:
            self._last_error = message[:_MAX_ERROR_LENGTH]


def _hello_ack(accepted: bool) -> str:
    payload = {"type": "hello_ack", "accepted": accepted}
    if accepted:
        payload["protocol_version"] = PROTOCOL_VERSION
    else:
        payload["error"] = "pairing_rejected"
    return json.dumps(payload, separators=(",", ":"))


def _bounded_nonempty_string(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise PairingError(f"invalid {field}")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise PairingError(f"invalid {field}") from None
    if any(ord(character) < 32 for character in value):
        raise PairingError(f"invalid {field}")
    return value


def _pairing_string(value: object, field: str, limit: int) -> str:
    return _bounded_nonempty_string(value, field, limit)


def _constructor_string(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{field} must be a nonempty bounded string")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"{field} must contain valid Unicode text") from None
    return value


def _finite_positive(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite positive number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0.0:
        raise ValueError(f"{field} must be a finite positive number")
    return converted


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")
    return value


def _frame_age(now: object, received: object) -> Optional[float]:
    if (
        isinstance(now, bool)
        or isinstance(received, bool)
        or not isinstance(now, (int, float))
        or not isinstance(received, (int, float))
    ):
        return None
    current = float(now)
    arrival = float(received)
    if not math.isfinite(current) or not math.isfinite(arrival):
        return None
    age = current - arrival
    return age if age >= 0.0 and math.isfinite(age) else None


def _service_type(name: object) -> str:
    value = _constructor_string(name, "service_name", 128)
    if value.endswith(".local."):
        service_type = value
    elif value.endswith(".local"):
        service_type = value + "."
    else:
        service_type = value.rstrip(".") + ".local."
    if not service_type.startswith("_") or "._tcp." not in service_type:
        raise ValueError("service_name must be a TCP Bonjour service type")
    return service_type


def _server_address(sockets: object, configured_host: str) -> tuple[str, int]:
    if not sockets:
        raise RuntimeError("server did not expose a listening socket")
    address = sockets[0].getsockname()
    return configured_host, int(address[1])


def _advertised_addresses(host: str) -> tuple[str, ...]:
    if host not in ("0.0.0.0", "::", ""):
        try:
            return (socket.gethostbyname(host),)
        except OSError:
            return ("127.0.0.1",)
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address != "0.0.0.0":
                addresses.add(address)
    except OSError:
        pass
    if not addresses:
        addresses.add("127.0.0.1")
    return tuple(sorted(addresses))


def _bounded_error(prefix: str, exc: BaseException) -> str:
    errno = getattr(exc, "errno", None)
    suffix = type(exc).__name__ if errno is None else f"{type(exc).__name__} {errno}"
    return f"{prefix}: {suffix}"[:_MAX_ERROR_LENGTH]
