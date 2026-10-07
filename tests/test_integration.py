import asyncio
import hashlib
import json
import unittest
from pathlib import Path

import websockets

from app.api.ws.spring_session import LinkState, run_spring_session
from app.core.config import Settings
from tests.test_command import _FileServer
from tests.test_init_connect import _link, _wait_until

SLOT = "usb-FTDI_FT232R_A1B2-if00"
PI_SERIAL = "10000000abcd1234"


class FullSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_session_covers_connect_command_report_and_exception(self):
        payload = b"student-zip"
        digest = hashlib.sha256(payload).hexdigest()
        sample = {
            "cpuPct": None,
            "memPct": 63.0,
            "fps": 31.4,
            "tempC": 61.2,
            "powerW": None,
            "errorRate": 0.5,
        }
        server = _FileServer(payload)
        server.start()
        messages: list[dict] = []
        allow_good = asyncio.Event()

        async def handler(websocket):
            sender = asyncio.create_task(_send_when(websocket, allow_good, _good_command(server.url, digest, len(payload))))
            try:
                async for raw in websocket:
                    body = json.loads(raw)
                    messages.append(body)
                    if body["type"] != "initConnect" or any(item["type"] == "BoriException" for item in messages):
                        continue
                    if not body["ports"] or not body["ports"][0]["online"]:
                        continue
                    await websocket.send(_bad_command(server.url, digest, len(payload)))
            finally:
                sender.cancel()

        try:
            import tempfile

            with tempfile.TemporaryDirectory() as raw:
                directory = Path(raw)
                _link(directory, SLOT)
                async with websockets.serve(handler, "127.0.0.1", 0) as socket_server:
                    port = socket_server.sockets[0].getsockname()[1]
                    settings = Settings(
                        spring_ws_url=f"ws://127.0.0.1:{port}",
                        pi_serial_code=PI_SERIAL,
                        usb_by_id_dir=str(directory),
                        usb_poll_seconds=0.05,
                        artifact_max_bytes=100,
                    )
                    task = asyncio.create_task(run_spring_session(settings, LinkState()))
                    try:
                        await _wait_until(lambda: any(item["type"] == "initConnect" for item in messages))
                        hello = next(item for item in messages if item["type"] == "initConnect")
                        self.assertEqual(hello["piSerial"], PI_SERIAL)
                        self.assertEqual(
                            hello["ports"],
                            [{"usbSlot": SLOT, "serialCode": "A1B2", "online": True}],
                        )

                        await _wait_until(lambda: any(item["type"] == "BoriException" for item in messages))
                        rejection = next(item for item in messages if item["type"] == "BoriException")
                        self.assertEqual(rejection["code"], "UNKNOWN_PORT")
                        self.assertEqual(rejection["piSerial"], PI_SERIAL)
                        self.assertEqual(rejection["usbSlot"], SLOT)
                        self.assertEqual((directory / "target" / SLOT).read_bytes(), b"")
                        allow_good.set()

                        board = directory / "target" / SLOT
                        await _wait_until(lambda: board.read_bytes().endswith(payload))
                        written = board.read_bytes()
                        header, body = written.split(b"\n", 1)
                        self.assertEqual(
                            json.loads(header),
                            {
                                "sha256": digest,
                                "size": len(payload),
                                "exec": {"kind": "aiModel", "format": "onnx"},
                            },
                        )
                        self.assertEqual(body, payload)

                        await asyncio.sleep(0.05)
                        with board.open("ab") as device:
                            device.write(json.dumps(sample).encode() + b"\n")
                        await _wait_until(lambda: any(item["type"] == "report" for item in messages))
                        report = next(item for item in messages if item["type"] == "report")
                        self.assertEqual(report["piSerial"], PI_SERIAL)
                        self.assertEqual(report["usbSlot"], SLOT)
                        self.assertEqual(report["serialCode"], "A1B2")
                        self.assertEqual(report["payload"], sample)

                        (directory / SLOT).unlink()
                        await _wait_until(
                            lambda: any(
                                item["type"] == "initConnect" and item["ports"][0]["online"] is False
                                for item in messages
                            )
                        )
                        with board.open("ab") as device:
                            device.write(b'{"fps":1}\n')
                        await asyncio.sleep(0.2)
                        reports = [item for item in messages if item["type"] == "report"]
                        self.assertEqual(len(reports), 1)
                    finally:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
        finally:
            server.close()


def _bad_command(url: str, digest: str, size: int) -> str:
    return json.dumps(
        {
            "type": "command",
            "serialCode": "OTHER",
            "usbSlot": SLOT,
            "payload": {
                "artifactUrl": url,
                "sha256": digest,
                "size": size,
                "exec": {"kind": "code"},
            },
        }
    )


def _good_command(url: str, digest: str, size: int) -> str:
    return json.dumps(
        {
            "type": "command",
            "serialCode": "A1B2",
            "usbSlot": SLOT,
            "payload": {
                "artifactUrl": url,
                "sha256": digest,
                "size": size,
                "exec": {"kind": "aiModel", "format": "onnx"},
            },
        }
    )


async def _send_when(websocket, ready: asyncio.Event, message: str) -> None:
    await ready.wait()
    await websocket.send(message)


if __name__ == "__main__":
    unittest.main()
