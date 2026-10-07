import asyncio
import json
import unittest
from pathlib import Path

import websockets

from app.api.ws.spring_session import LinkState, run_spring_session
from app.core.config import Settings
from app.core.registry import PortRegistry
from app.service.command import handle_command
from tests.test_init_connect import _link, _wait_until

SLOT = "usb-FTDI_FT232R_A1B2-if00"


class BoriExceptionDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile

        self._raw = tempfile.TemporaryDirectory()
        self.directory = Path(self._raw.name)
        _link(self.directory, SLOT)
        self.registry = PortRegistry()
        self.registry.apply_scan([(SLOT, "A1B2")])

    async def asyncTearDown(self):
        self._raw.cleanup()

    def _command(self, **overrides):
        body = {
            "type": "command",
            "serialCode": "A1B2",
            "usbSlot": SLOT,
            "payload": {
                "artifactUrl": "http://127.0.0.1/unused",
                "sha256": "abc",
                "size": 3,
                "exec": {},
            },
        }
        body.update(overrides)
        return body

    async def _reject(self, message, **kwargs):
        return await handle_command(
            message,
            pi_serial="PI-1",
            registry=self.registry,
            by_id_dir=self.directory,
            max_bytes=kwargs.get("max_bytes", 100),
        )

    def _assert_shape(self, reply, code, usb_slot):
        body = json.loads(reply.model_dump_json(by_alias=True))
        self.assertEqual(
            body,
            {
                "type": "BoriException",
                "piSerial": "PI-1",
                "usbSlot": usb_slot,
                "code": code,
            },
        )
        self.assertEqual((self.directory / "target" / SLOT).read_bytes(), b"")

    async def test_missing_slot_is_unknown_port(self):
        reply = await self._reject(self._command(usbSlot="missing-slot"))
        self._assert_shape(reply, "UNKNOWN_PORT", "missing-slot")

    async def test_serial_mismatch_is_unknown_port(self):
        reply = await self._reject(self._command(serialCode="OTHER"))
        self._assert_shape(reply, "UNKNOWN_PORT", SLOT)

    async def test_offline_slot_is_port_closed(self):
        self.registry.apply_scan([])
        reply = await self._reject(self._command())
        self._assert_shape(reply, "PORT_CLOSED", SLOT)

    async def test_missing_device_is_port_closed(self):
        (self.directory / SLOT).unlink()
        reply = await self._reject(self._command())
        self._assert_shape(reply, "PORT_CLOSED", SLOT)

    async def test_over_limit_is_oversize(self):
        reply = await self._reject(self._command(), max_bytes=2)
        self._assert_shape(reply, "OVERSIZE", SLOT)

    async def test_negative_size_is_oversize(self):
        message = self._command()
        message["payload"]["size"] = -1
        reply = await self._reject(message)
        self._assert_shape(reply, "OVERSIZE", SLOT)

    async def test_other_message_is_not_an_exception(self):
        reply = await self._reject({"type": "report", "payload": {}})
        self.assertIsNone(reply)

    async def test_broken_command_is_not_an_exception(self):
        reply = await self._reject({"type": "command"})
        self.assertIsNone(reply)


class BoriExceptionSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_spring_receives_each_code_and_board_stays_empty(self):
        import tempfile

        messages: list[dict] = []
        sent_closed = False

        async def handler(websocket):
            nonlocal sent_closed
            async for raw in websocket:
                body = json.loads(raw)
                messages.append(body)
                if body["type"] != "initConnect":
                    continue
                online = body["ports"] and body["ports"][0]["online"]
                if online and not any(item["type"] == "BoriException" for item in messages):
                    await websocket.send(_command(usb_slot="missing-slot", serial_code="A1B2"))
                    await websocket.send(_command(usb_slot=SLOT, serial_code="OTHER"))
                    await websocket.send(_command(usb_slot=SLOT, serial_code="A1B2", size=101))
                if not online and not sent_closed:
                    sent_closed = True
                    await websocket.send(_command(usb_slot=SLOT, serial_code="A1B2", size=3))

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _link(directory, SLOT)
            async with websockets.serve(handler, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                settings = Settings(
                    spring_ws_url=f"ws://127.0.0.1:{port}",
                    pi_serial_code="PI-1",
                    usb_by_id_dir=str(directory),
                    usb_poll_seconds=0.05,
                    artifact_max_bytes=100,
                )
                task = asyncio.create_task(run_spring_session(settings, LinkState()))
                try:
                    await _wait_until(lambda: _codes(messages) == ["UNKNOWN_PORT", "UNKNOWN_PORT", "OVERSIZE"])
                    (directory / SLOT).unlink()
                    await _wait_until(lambda: _codes(messages) == ["UNKNOWN_PORT", "UNKNOWN_PORT", "OVERSIZE", "PORT_CLOSED"])
                    self.assertEqual(
                        [item["usbSlot"] for item in messages if item["type"] == "BoriException"],
                        ["missing-slot", SLOT, SLOT, SLOT],
                    )
                    self.assertTrue(all(item["piSerial"] == "PI-1" for item in messages if item["type"] == "BoriException"))
                    self.assertEqual((directory / "target" / SLOT).read_bytes(), b"")
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task


def _command(usb_slot=SLOT, serial_code="A1B2", size=3):
    return json.dumps(
        {
            "type": "command",
            "serialCode": serial_code,
            "usbSlot": usb_slot,
            "payload": {
                "artifactUrl": "http://127.0.0.1/unused",
                "sha256": "abc",
                "size": size,
                "exec": {},
            },
        }
    )


def _codes(messages: list[dict]) -> list[str]:
    return [item["code"] for item in messages if item["type"] == "BoriException"]


if __name__ == "__main__":
    unittest.main()
