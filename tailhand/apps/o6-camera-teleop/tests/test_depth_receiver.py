import asyncio
from dataclasses import FrozenInstanceError
import json
import math
import socket
import time
import unittest
from unittest import mock

import websockets
from websockets.exceptions import ConnectionClosed

from tests.depth_test_utils import make_depth_frame
from tests.test_depth_protocol import make_fixture
from vision.depth_receiver import (
    DepthReceiver,
    DepthReceiverState,
    PairingError,
    validate_hello,
)


PAIRING_CODE = "123456"


def hello(**updates):
    message = {
        "type": "hello",
        "protocol_version": 1,
        "pairing_code": PAIRING_CODE,
        "device_name": "Duami",
        "supports_scene_depth": True,
    }
    message.update(updates)
    return json.dumps(message, separators=(",", ":"))


class DepthReceiverStateTest(unittest.TestCase):
    def test_constructor_rejects_invalid_pairing_code_and_timeout(self):
        for code in (None, "", 123456):
            with self.subTest(code=code), self.assertRaises(ValueError):
                DepthReceiverState(code, 0.5)
        for timeout in (True, 0, -1, math.inf, math.nan, "0.5"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                DepthReceiverState(PAIRING_CODE, timeout)

    def test_validate_hello_requires_exact_text_protocol(self):
        parsed = validate_hello(hello())
        self.assertEqual(parsed.device_name, "Duami")
        self.assertEqual(parsed.pairing_code, PAIRING_CODE)

        invalid = (
            b"not text",
            "not json",
            "[]",
            hello(type="other"),
            hello(protocol_version=True),
            hello(supports_scene_depth=False),
            hello(device_name=""),
            hello(extra="field"),
        )
        for message in invalid:
            with self.subTest(message=message), self.assertRaises(PairingError) as raised:
                validate_hello(message)
            self.assertLessEqual(len(str(raised.exception)), 96)
            self.assertNotIn("not json", str(raised.exception))

    def test_wrong_code_uses_compare_digest_and_second_client_is_rejected(self):
        state = DepthReceiverState(PAIRING_CODE, 0.5)
        with mock.patch("vision.depth_receiver.secrets.compare_digest", wraps=__import__("secrets").compare_digest) as compare:
            with self.assertRaisesRegex(PairingError, "pairing"):
                state.connect("Duami", "999999")
            compare.assert_called_once_with(b"999999", b"123456")

        state.connect("Duami", PAIRING_CODE)
        with self.assertRaisesRegex(PairingError, "already"):
            state.connect("Other", PAIRING_CODE)
        for device, code in ((None, PAIRING_CODE), ("", PAIRING_CODE), ("Other", None)):
            with self.subTest(device=device, code=code), self.assertRaises(PairingError):
                state.connect(device, code)

    def test_unicode_pairing_codes_are_compared_without_type_errors(self):
        state = DepthReceiverState("配对码", 0.5)
        with self.assertRaises(PairingError):
            state.connect("Duami", "错误码")
        state.connect("Duami", "配对码")
        self.assertTrue(state.connected)

    def test_invalid_unicode_text_is_normalized_to_pairing_error(self):
        with self.assertRaises(PairingError):
            validate_hello("\ud800")
        state = DepthReceiverState(PAIRING_CODE, 0.5)
        with self.assertRaises(PairingError):
            state.connect("\ud800", PAIRING_CODE)

    def test_connect_resets_frame_and_sequence_for_new_session(self):
        state = DepthReceiverState(PAIRING_CODE, 0.5)
        state.connect("Duami", PAIRING_CODE)
        state.accept(make_depth_frame(sequence=8, received_monotonic=10.0))
        state.disconnect()
        state.connect("Duami 2", PAIRING_CODE)

        self.assertIsNone(state.latest(now=10.0))
        self.assertIsNone(state.latest_sequence)
        state.accept(make_depth_frame(sequence=1, received_monotonic=11.0))
        self.assertEqual(state.latest_sequence, 1)

    def test_accept_requires_connection_and_strictly_increasing_sequence(self):
        state = DepthReceiverState(PAIRING_CODE, 0.5)
        with self.assertRaises(PairingError):
            state.accept(make_depth_frame(sequence=1))
        state.connect("Duami", PAIRING_CODE)
        state.accept(make_depth_frame(sequence=2))
        for sequence in (2, 1):
            with self.subTest(sequence=sequence), self.assertRaisesRegex(PairingError, "sequence"):
                state.accept(make_depth_frame(sequence=sequence))

    def test_capacity_one_latest_frame_overwrites_old(self):
        state = DepthReceiverState(PAIRING_CODE, 1.0)
        state.connect("Duami", PAIRING_CODE)
        state.accept(make_depth_frame(sequence=1, received_monotonic=10.0, depth_value=400))
        state.accept(make_depth_frame(sequence=2, received_monotonic=10.1, depth_value=600))

        frame = state.latest(now=10.1)
        self.assertEqual(frame.sequence, 2)
        self.assertEqual(int(frame.depth_mm[0, 0]), 600)

    def test_freshness_includes_boundaries_and_rejects_future_or_nonfinite_times(self):
        state = DepthReceiverState(PAIRING_CODE, 0.5)
        state.connect("Duami", PAIRING_CODE)
        state.accept(make_depth_frame(sequence=1, received_monotonic=10.0))
        self.assertEqual(state.latest(now=10.0).sequence, 1)
        self.assertEqual(state.latest(now=10.5).sequence, 1)
        self.assertIsNone(state.latest(now=10.500001))
        self.assertIsNone(state.latest(now=9.999))
        for now in (math.inf, -math.inf, math.nan, True, "10"):
            with self.subTest(now=now):
                self.assertIsNone(state.latest(now=now))

        state.accept(make_depth_frame(sequence=2, received_monotonic=math.inf))
        self.assertIsNone(state.latest(now=10.0))
        state.accept(make_depth_frame(sequence=3, received_monotonic=math.nan))
        self.assertIsNone(state.latest(now=10.0))

    def test_disconnect_clears_read_only_status(self):
        state = DepthReceiverState(PAIRING_CODE, 0.5)
        state.connect("Duami", PAIRING_CODE)
        state.accept(make_depth_frame(sequence=3, received_monotonic=10.0))
        snapshot = state.snapshot(now=10.25)
        self.assertTrue(snapshot.connected)
        self.assertEqual((snapshot.device, snapshot.latest_sequence), ("Duami", 3))
        self.assertTrue(snapshot.fresh)
        self.assertAlmostEqual(snapshot.latest_age_seconds, 0.25)
        with self.assertRaises(FrozenInstanceError):
            snapshot.device = "Other"

        state.disconnect()
        self.assertFalse(state.connected)
        self.assertIsNone(state.device)
        self.assertIsNone(state.latest_sequence)
        self.assertFalse(state.is_fresh(now=10.25))


class DepthReceiverBonjourTest(unittest.TestCase):
    def test_bonjour_registration_does_not_deadlock_receiver_loop(self):
        receiver = DepthReceiver(
            pairing_code=PAIRING_CODE,
            host="127.0.0.1",
            port=0,
            advertise_bonjour=True,
            startup_timeout_seconds=2.0,
            stop_timeout_seconds=2.0,
        )
        try:
            receiver.start()
            status = receiver.status()
            self.assertTrue(status.running)
            self.assertIn(status.bonjour_state, {"starting", "published", "failed"})
        finally:
            receiver.stop()

    def test_bonjour_failure_closes_resources_while_listener_continues(self):
        zeroconf = mock.Mock()
        zeroconf.async_register_service = mock.AsyncMock(side_effect=RuntimeError("network detail"))
        zeroconf.async_unregister_service = mock.AsyncMock()
        zeroconf.async_close = mock.AsyncMock()
        receiver = DepthReceiver(PAIRING_CODE, host="127.0.0.1", port=0)
        try:
            with mock.patch("vision.depth_receiver.AsyncZeroconf", return_value=zeroconf):
                receiver.start()
                deadline = time.monotonic() + 1.0
                while receiver.status().bonjour_state == "starting" and time.monotonic() < deadline:
                    time.sleep(0.01)
                status = receiver.status()
                self.assertTrue(status.running)
                self.assertEqual(status.bonjour_state, "failed")
                self.assertNotIn("network detail", status.bonjour_error)
                zeroconf.async_unregister_service.assert_awaited_once()
                zeroconf.async_close.assert_awaited_once()
        finally:
            receiver.stop()


class DepthReceiverLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.receiver = DepthReceiver(
            pairing_code=PAIRING_CODE,
            host="127.0.0.1",
            port=0,
            timeout_seconds=0.5,
            max_message_bytes=1_000_000,
            max_fps=1_000,
            advertise_bonjour=False,
        )
        self.receiver.start()

    def tearDown(self):
        self.receiver.stop()

    @property
    def uri(self):
        port = self.receiver.status().listening_port
        return f"ws://127.0.0.1:{port}"

    async def wait_for_frame(self):
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            frame = self.receiver.latest()
            if frame is not None:
                return frame
            await asyncio.sleep(0.01)
        self.fail("receiver did not publish the frame")

    async def test_valid_hello_ack_and_binary_frame(self):
        async with websockets.connect(self.uri, max_size=1_000_000) as websocket:
            await websocket.send(hello())
            ack = json.loads(await websocket.recv())
            self.assertEqual(ack, {"type": "hello_ack", "accepted": True, "protocol_version": 1})
            await websocket.send(make_fixture())
            frame = await self.wait_for_frame()
            self.assertEqual(frame.sequence, 7)
            status = self.receiver.status()
            self.assertTrue(status.running)
            self.assertEqual(status.connected_device, "Duami")
            self.assertEqual(status.last_frame_sequence, 7)
            self.assertIsNotNone(status.last_frame_age_ms)
            self.assertEqual(status.bonjour_state, "disabled")

    async def test_wrong_code_receives_bounded_rejection_and_closes(self):
        async with websockets.connect(self.uri) as websocket:
            await websocket.send(hello(pairing_code="wrong"))
            ack = json.loads(await websocket.recv())
            self.assertEqual(ack["type"], "hello_ack")
            self.assertFalse(ack["accepted"])
            self.assertLessEqual(len(json.dumps(ack)), 160)
            with self.assertRaises(ConnectionClosed):
                await websocket.recv()
        self.assertFalse(self.receiver.status().connected)

    async def test_malformed_first_message_is_rejected(self):
        async with websockets.connect(self.uri) as websocket:
            await websocket.send(b"binary hello")
            ack = json.loads(await websocket.recv())
            self.assertFalse(ack["accepted"])
            with self.assertRaises(ConnectionClosed):
                await websocket.recv()

    async def test_second_client_is_rejected_without_disconnecting_owner(self):
        async with websockets.connect(self.uri) as owner:
            await owner.send(hello())
            self.assertTrue(json.loads(await owner.recv())["accepted"])
            async with websockets.connect(self.uri) as second:
                await second.send(hello(device_name="Other"))
                self.assertFalse(json.loads(await second.recv())["accepted"])
            await owner.send(make_fixture())
            self.assertEqual((await self.wait_for_frame()).sequence, 7)
            self.assertEqual(self.receiver.status().connected_device, "Duami")

    async def test_stop_is_idempotent_and_releases_ephemeral_port(self):
        status = self.receiver.status()
        port = status.listening_port
        self.assertTrue(status.running)
        self.receiver.stop()
        self.receiver.stop()
        stopped = self.receiver.status()
        self.assertFalse(stopped.running)
        self.assertIsNone(stopped.listening_host)
        self.assertIsNone(stopped.listening_port)

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()


if __name__ == "__main__":
    unittest.main()
