import asyncio
import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

from app.api.ws.spring_session import LinkState, run_spring_session
from app.core.config import Settings
from app.core.registry import PortRegistry
from app.service.command import handle_command
from tests.test_init_connect import _link


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FileServer(threading.Thread):
    def __init__(self, body: bytes) -> None:
        super().__init__(daemon=True)
        self.body = body
        handler = type(
            "Handler",
            (BaseHTTPRequestHandler,),
            {
                "body": body,
                "do_GET": _serve_file,
                "log_message": lambda *args: None,
            },
        )
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/artifact"

    def run(self) -> None:
        self.httpd.serve_forever()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _serve_file(handler) -> None:
    payload = handler.body
    handler.send_response(200)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class CommandDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile

        self._raw = tempfile.TemporaryDirectory()
        self.directory = Path(self._raw.name)
        self.slot = "usb-FTDI_FT232R_A1B2-if00"
        _link(self.directory, self.slot)
        self.registry = PortRegistry()
        self.registry.apply_scan([(self.slot, "A1B2")])

    async def asyncTearDown(self):
        self._raw.cleanup()

    def _command(self, **overrides):
        body = {
            "type": "command",
            "serialCode": "A1B2",
            "usbSlot": self.slot,
            "payload": {
                "artifactUrl": "http://127.0.0.1/unused",
                "sha256": _sha256(b"zip"),
                "size": 3,
                "exec": {"kind": "code"},
            },
        }
        body.update(overrides)
        return body

    async def test_unknown_port(self):
        reply = await handle_command(
            self._command(usbSlot="missing"),
            pi_serial="PI-1",
            registry=self.registry,
            by_id_dir=self.directory,
            max_bytes=100,
        )
        self.assertEqual(reply.code, "UNKNOWN_PORT")
        self.assertEqual((self.directory / "target" / self.slot).read_bytes(), b"")

    async def test_serial_mismatch(self):
        reply = await handle_command(
            self._command(serialCode="OTHER"),
            pi_serial="PI-1",
            registry=self.registry,
            by_id_dir=self.directory,
            max_bytes=100,
        )
        self.assertEqual(reply.code, "UNKNOWN_PORT")

    async def test_port_closed(self):
        self.registry.apply_scan([])
        reply = await handle_command(
            self._command(),
            pi_serial="PI-1",
            registry=self.registry,
            by_id_dir=self.directory,
            max_bytes=100,
        )
        self.assertEqual(reply.code, "PORT_CLOSED")

    async def test_oversize_does_not_download(self):
        reply = await handle_command(
            self._command(),
            pi_serial="PI-1",
            registry=self.registry,
            by_id_dir=self.directory,
            max_bytes=2,
        )
        self.assertEqual(reply.code, "OVERSIZE")
        self.assertEqual((self.directory / "target" / self.slot).read_bytes(), b"")

    async def test_hash_mismatch_does_not_write(self):
        server = _FileServer(b"zip")
        server.start()
        try:
            message = self._command()
            message["payload"]["artifactUrl"] = server.url
            message["payload"]["sha256"] = _sha256(b"nope")
            reply = await handle_command(
                message,
                pi_serial="PI-1",
                registry=self.registry,
                by_id_dir=self.directory,
                max_bytes=100,
            )
        finally:
            server.close()
        self.assertIsNone(reply)
        self.assertEqual((self.directory / "target" / self.slot).read_bytes(), b"")

    async def test_writes_header_and_file_without_changing_exec(self):
        payload = b"zip-bytes"
        server = _FileServer(payload)
        server.start()
        try:
            message = self._command()
            message["payload"].update(
                {
                    "artifactUrl": server.url,
                    "sha256": _sha256(payload),
                    "size": len(payload),
                    "exec": {"kind": "aiModel", "format": "onnx"},
                }
            )
            reply = await handle_command(
                message,
                pi_serial="PI-1",
                registry=self.registry,
                by_id_dir=self.directory,
                max_bytes=100,
            )
        finally:
            server.close()
        self.assertIsNone(reply)
        written = (self.directory / "target" / self.slot).read_bytes()
        header, body = written.split(b"\n", 1)
        self.assertEqual(
            json.loads(header),
            {
                "sha256": _sha256(payload),
                "size": len(payload),
                "exec": {"kind": "aiModel", "format": "onnx"},
            },
        )
        self.assertEqual(body, payload)


class CommandSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_spring_receives_exception_and_board_receives_file(self):
        import tempfile

        payload = b"model"
        server = _FileServer(payload)
        server.start()
        messages: list[dict] = []

        async def handler(websocket):
            async for raw in websocket:
                body = json.loads(raw)
                messages.append(body)
                if body["type"] == "initConnect":
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "command",
                                "serialCode": "NONE",
                                "usbSlot": "usb-FTDI_FT232R_AAA-if00",
                                "payload": {
                                    "artifactUrl": server.url,
                                    "sha256": _sha256(payload),
                                    "size": len(payload),
                                    "exec": {},
                                },
                            }
                        )
                    )
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "command",
                                "serialCode": "AAA",
                                "usbSlot": "usb-FTDI_FT232R_AAA-if00",
                                "payload": {
                                    "artifactUrl": server.url,
                                    "sha256": _sha256(payload),
                                    "size": len(payload),
                                    "exec": {"kind": "code"},
                                },
                            }
                        )
                    )

        try:
            with tempfile.TemporaryDirectory() as raw:
                directory = Path(raw)
                _link(directory, "usb-FTDI_FT232R_AAA-if00")
                async with websockets.serve(handler, "127.0.0.1", 0) as socket_server:
                    port = socket_server.sockets[0].getsockname()[1]
                    settings = Settings(
                        spring_ws_url=f"ws://127.0.0.1:{port}",
                        pi_serial_code="PI-1",
                        usb_by_id_dir=str(directory),
                        usb_poll_seconds=1,
                        artifact_max_bytes=100,
                    )
                    task = asyncio.create_task(run_spring_session(settings, LinkState()))
                    try:
                        await _wait_until(lambda: any(item["type"] == "BoriException" for item in messages))
                        rejection = next(item for item in messages if item["type"] == "BoriException")
                        self.assertEqual(rejection["code"], "UNKNOWN_PORT")
                        self.assertEqual(rejection["piSerial"], "PI-1")
                        await _wait_until(lambda: (directory / "target" / "usb-FTDI_FT232R_AAA-if00").stat().st_size > 0)
                        written = (directory / "target" / "usb-FTDI_FT232R_AAA-if00").read_bytes()
                        self.assertTrue(written.endswith(payload))
                        self.assertIn(b'"kind":"code"', written)
                    finally:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
        finally:
            server.close()


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


if __name__ == "__main__":
    unittest.main()
