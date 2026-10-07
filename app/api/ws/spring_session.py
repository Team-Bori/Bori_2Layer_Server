import asyncio
import logging
from contextlib import suppress
from pathlib import Path

import websockets

from app.api.ws.command import on_command
from app.api.ws.init_connect import send_init_connect, watch_ports
from app.api.ws.report import watch_reports
from app.core.config import Settings
from app.core.pi_serial import read_pi_serial
from app.core.registry import PortRegistry
from app.core.usb_scan import scan_ports
from app.service.report import ReportReader

log = logging.getLogger(__name__)


class LinkState:
    def __init__(self) -> None:
        self.pi_serial: str | None = None


async def run_spring_session(settings: Settings, state: LinkState) -> None:
    try:
        state.pi_serial = read_pi_serial(settings.pi_serial_code)
    except RuntimeError:
        log.exception("파이 시리얼을 읽지 못했습니다.")
        return

    if not settings.spring_ws_url:
        log.warning("SPRING_WS_URL이 없어 스프링 소켓을 열지 않습니다.")
        return

    by_id_dir = Path(settings.usb_by_id_dir)
    registry = PortRegistry()
    report_reader = ReportReader()

    while True:
        try:
            async with websockets.connect(settings.spring_ws_url) as websocket:
                registry.apply_scan(scan_ports(by_id_dir))
                await send_init_connect(websocket.send, state.pi_serial, registry)
                watch = asyncio.create_task(
                    watch_ports(
                        by_id_dir,
                        registry,
                        settings.usb_poll_seconds,
                        websocket.send,
                        state.pi_serial,
                    )
                )
                reports = asyncio.create_task(
                    watch_reports(
                        by_id_dir,
                        registry,
                        report_reader,
                        state.pi_serial,
                        settings.usb_poll_seconds,
                        websocket.send,
                    )
                )
                try:
                    async for raw in websocket:
                        await on_command(
                            raw,
                            send=websocket.send,
                            pi_serial=state.pi_serial,
                            registry=registry,
                            by_id_dir=by_id_dir,
                            max_bytes=settings.artifact_max_bytes,
                            report_reader=report_reader,
                        )
                finally:
                    watch.cancel()
                    reports.cancel()
                    with suppress(asyncio.CancelledError):
                        await watch
                    with suppress(asyncio.CancelledError):
                        await reports
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("스프링 소켓이 끊겼습니다. 다시 연결합니다.")
            await asyncio.sleep(3)
