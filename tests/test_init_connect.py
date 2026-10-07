import asyncio
import json
import unittest
from pathlib import Path

import websockets

from app.core.pi_serial import read_pi_serial
from app.core.usb_scan import scan_ports, serial_from_slot_name
from app.api.ws.spring_session import LinkState, run_spring_session
from app.core.config import Settings
from app.core.registry import PortRegistry
from app.schema.messages import build_init_connect


def _link(directory: Path, name: str) -> None:
    target = directory / "target" / name
    target.parent.mkdir(exist_ok=True)
    target.touch()
    (directory / name).symlink_to(target)


class SerialTests(unittest.TestCase):
    def test_override_is_used(self):
        self.assertEqual(read_pi_serial("  PI-1  "), "PI-1")

    def test_device_tree_serial(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            serial_path = root / "serial-number"
            serial_path.write_bytes(b"10000000abcd\0")
            self.assertEqual(
                read_pi_serial(serial_path=serial_path, cpuinfo_path=root / "missing"),
                "10000000abcd",
            )

    def test_cpuinfo_fallback(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cpuinfo = root / "cpuinfo"
            cpuinfo.write_text("Hardware\t: bcm\nSerial\t\t: abcdef\n")
            self.assertEqual(
                read_pi_serial(serial_path=root / "missing", cpuinfo_path=cpuinfo),
                "abcdef",
            )

    def test_missing_serial_raises(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(RuntimeError):
                read_pi_serial(serial_path=root / "missing", cpuinfo_path=root / "also-missing")


class UsbScanTests(unittest.TestCase):
    def test_serial_from_by_id_name(self):
        self.assertEqual(serial_from_slot_name("usb-FTDI_FT232R_A1B2-if00"), "A1B2")
        self.assertEqual(serial_from_slot_name("no-underscore"), "")

    def test_scan_reads_links_in_name_order(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _link(directory, "usb-FTDI_FT232R_BBB-if00")
            _link(directory, "usb-FTDI_FT232R_AAA-if00")
            self.assertEqual(
                scan_ports(directory),
                [
                    ("usb-FTDI_FT232R_AAA-if00", "AAA"),
                    ("usb-FTDI_FT232R_BBB-if00", "BBB"),
                ],
            )

    def test_missing_directory_is_empty(self):
        self.assertEqual(scan_ports(Path("/no/such/by-id")), [])


class RegistryTests(unittest.TestCase):
    def test_sixth_port_is_left_out(self):
        registry = PortRegistry()
        found = [(f"usb-DEV_{name}-if00", name) for name in "ABCDEF"]
        self.assertTrue(registry.apply_scan(found))
        self.assertEqual([link.serial_code for link in registry.ports()], list("ABCDE"))

    def test_unplug_keeps_slot_offline_and_replug_is_same_slot(self):
        registry = PortRegistry()
        slot = "usb-FTDI_FT232R_A1B2-if00"
        registry.apply_scan([(slot, "A1B2")])
        self.assertTrue(registry.apply_scan([]))
        self.assertEqual(
            [(link.usb_slot, link.online) for link in registry.ports()],
            [(slot, False)],
        )
        self.assertTrue(registry.apply_scan([(slot, "A1B2")]))
        self.assertEqual(
            [(link.usb_slot, link.serial_code, link.online) for link in registry.ports()],
            [(slot, "A1B2", True)],
        )

    def test_unchanged_scan_reports_no_change(self):
        registry = PortRegistry()
        found = [("usb-FTDI_FT232R_A1B2-if00", "A1B2")]
        registry.apply_scan(found)
        self.assertFalse(registry.apply_scan(found))

    def test_offline_slot_still_counts_toward_limit(self):
        registry = PortRegistry()
        first = [(f"usb-DEV_{name}-if00", name) for name in "ABCDE"]
        registry.apply_scan(first)
        registry.apply_scan(first[:4])
        registry.apply_scan(first[:4] + [("usb-DEV_Z-if00", "Z")])
        slots = [link.usb_slot for link in registry.ports()]
        self.assertNotIn("usb-DEV_Z-if00", slots)
        self.assertEqual(len(slots), 5)


class MessageTests(unittest.TestCase):
    def test_init_connect_json(self):
        registry = PortRegistry()
        registry.apply_scan([("usb-FTDI_FT232R_A1B2-if00", "A1B2")])
        registry.apply_scan([])
        body = json.loads(build_init_connect("PI-1", registry).model_dump_json(by_alias=True))
        self.assertEqual(
            body,
            {
                "type": "initConnect",
                "piSerial": "PI-1",
                "ports": [
                    {
                        "usbSlot": "usb-FTDI_FT232R_A1B2-if00",
                        "serialCode": "A1B2",
                        "online": False,
                    }
                ],
            },
        )


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_init_connect_and_updates_when_usb_changes(self):
        import tempfile

        messages: list[dict] = []

        async def handler(websocket):
            async for raw in websocket:
                messages.append(json.loads(raw))

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _link(directory, "usb-FTDI_FT232R_AAA-if00")
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
                    await _wait_until(lambda: len(messages) >= 1)
                    self.assertEqual(messages[0]["type"], "initConnect")
                    self.assertEqual(messages[0]["piSerial"], "PI-1")
                    self.assertEqual(
                        messages[0]["ports"],
                        [
                            {
                                "usbSlot": "usb-FTDI_FT232R_AAA-if00",
                                "serialCode": "AAA",
                                "online": True,
                            }
                        ],
                    )

                    _link(directory, "usb-FTDI_FT232R_BBB-if00")
                    await _wait_until(lambda: len(messages) >= 2)
                    slots = {item["usbSlot"]: item["online"] for item in messages[-1]["ports"]}
                    self.assertEqual(
                        slots,
                        {
                            "usb-FTDI_FT232R_AAA-if00": True,
                            "usb-FTDI_FT232R_BBB-if00": True,
                        },
                    )

                    (directory / "usb-FTDI_FT232R_AAA-if00").unlink()
                    await _wait_until(
                        lambda: any(
                            item["usbSlot"] == "usb-FTDI_FT232R_AAA-if00" and item["online"] is False
                            for item in messages[-1]["ports"]
                        )
                    )
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for initConnect")
        await asyncio.sleep(0.02)


if __name__ == "__main__":
    unittest.main()
