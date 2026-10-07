import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.registry import PortRegistry
from app.schema.messages import build_report
from app.service.report import ReportReader
from app.service.usb_link import device_path

Send = Callable[[str], Awaitable[None]]


async def watch_reports(
    by_id_dir: Path,
    registry: PortRegistry,
    reader: ReportReader,
    pi_serial: str,
    interval: float,
    send: Send,
) -> None:
    while True:
        await asyncio.sleep(interval)
        for link in registry.ports():
            if not link.online:
                continue
            device = device_path(by_id_dir, link.usb_slot)
            if device is None:
                continue
            for payload in reader.read_board_reports(link.usb_slot, device):
                report = build_report(pi_serial, link.usb_slot, link.serial_code, payload)
                await send(report.model_dump_json(by_alias=True))
