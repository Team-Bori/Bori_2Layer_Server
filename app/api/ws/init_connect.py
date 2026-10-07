import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.registry import PortRegistry
from app.core.usb_scan import scan_ports
from app.schema.messages import build_init_connect

Send = Callable[[str], Awaitable[None]]


async def send_init_connect(send: Send, pi_serial: str, registry: PortRegistry) -> None:
    message = build_init_connect(pi_serial, registry)
    await send(message.model_dump_json(by_alias=True))


async def watch_ports(
    by_id_dir: Path,
    registry: PortRegistry,
    interval: float,
    send: Send,
    pi_serial: str,
) -> None:
    while True:
        await asyncio.sleep(interval)
        if registry.apply_scan(scan_ports(by_id_dir)):
            await send_init_connect(send, pi_serial, registry)
