import asyncio
import json
import unittest
from pathlib import Path

import websockets

from app.api.ws.spring_session import LinkState, run_spring_session
from app.core.config import Settings
from app.schema.messages import build_report
from app.service.report import ReportReader
from tests.test_init_connect import _link, _wait_until

SLOT = "usb-FTDI_FT232R_AAA-if00"


class ReportMessageTests(unittest.TestCase):
    def test_payload_nulls_stay_null(self):
        payload = {
            "cpuPct": None,
            "memPct": 10.5,
            "fps": None,
            "tempC": 61.2,
            "powerW": None,
            "errorRate": 0.5,
        }
        body = json.loads(
            build_report("PI-1", SLOT, "AAA", payload).model_dump_json(by_alias=True)
        )
        self.assertEqual(body["type"], "report")
        self.assertEqual(body["piSerial"], "PI-1")
        self.assertEqual(body["usbSlot"], SLOT)
        self.assertEqual(body["serialCode"], "AAA")
        self.assertEqual(body["payload"], payload)
        self.assertIsNone(body["payload"]["fps"])
        self.assertNotIn(0, body["payload"].values())


class ReportReaderTests(unittest.TestCase):
    def test_ignores_command_header_and_keeps_board_json(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _link(directory, SLOT)
            device = directory / SLOT
            device.write_bytes(b'{"sha256":"abc","size":3,"exec":{}}\nzip\n')
            reader = ReportReader()
            self.assertEqual(reader.read_board_reports(SLOT, device), [])
            with device.open("ab") as port:
                port.write(b'{"fps":31.4,"tempC":61.2,"powerW":null}\n')
            reports = reader.read_board_reports(SLOT, device)
            self.assertEqual(reports, [{"fps": 31.4, "tempC": 61.2, "powerW": None}])

    def test_two_lines_keep_order(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _link(directory, SLOT)
            device = directory / SLOT
            reader = ReportReader()
            reader.read_board_reports(SLOT, device)
            with device.open("ab") as port:
                port.write(b'{"cpuPct":1}\n{"cpuPct":2}\n')
            self.assertEqual(
                reader.read_board_reports(SLOT, device),
                [{"cpuPct": 1}, {"cpuPct": 2}],
            )


class ReportSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_board_metrics_are_forwarded_unchanged(self):
        import tempfile

        messages: list[dict] = []

        async def handler(websocket):
            async for raw in websocket:
                messages.append(json.loads(raw))

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
                )
                task = asyncio.create_task(run_spring_session(settings, LinkState()))
                try:
                    await _wait_until(lambda: any(item["type"] == "initConnect" for item in messages))
                    await asyncio.sleep(0.15)
                    sample = {
                        "cpuPct": None,
                        "memPct": 63.0,
                        "fps": 31.4,
                        "tempC": 61.2,
                        "powerW": None,
                        "errorRate": 0.5,
                    }
                    with (directory / SLOT).open("ab") as device:
                        device.write(json.dumps(sample).encode() + b"\n")
                    await _wait_until(lambda: any(item["type"] == "report" for item in messages))
                    report = next(item for item in messages if item["type"] == "report")
                    self.assertEqual(report["piSerial"], "PI-1")
                    self.assertEqual(report["usbSlot"], SLOT)
                    self.assertEqual(report["serialCode"], "AAA")
                    self.assertEqual(report["payload"], sample)
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

    async def test_offline_port_is_not_forwarded(self):
        import tempfile

        messages: list[dict] = []

        async def handler(websocket):
            async for raw in websocket:
                messages.append(json.loads(raw))

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
                )
                task = asyncio.create_task(run_spring_session(settings, LinkState()))
                try:
                    await _wait_until(lambda: messages and messages[-1]["type"] == "initConnect")
                    (directory / SLOT).unlink()
                    await _wait_until(
                        lambda: messages[-1]["type"] == "initConnect"
                        and messages[-1]["ports"][0]["online"] is False
                    )
                    with (directory / "target" / SLOT).open("ab") as device:
                        device.write(b'{"fps":1}\n')
                    await asyncio.sleep(0.2)
                    self.assertFalse(any(item["type"] == "report" for item in messages))
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task


if __name__ == "__main__":
    unittest.main()
