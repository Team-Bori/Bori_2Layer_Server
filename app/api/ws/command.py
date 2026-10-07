import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.registry import PortRegistry
from app.service.command import handle_command
from app.service.report import ReportReader

log = logging.getLogger(__name__)

Send = Callable[[str], Awaitable[None]]


async def on_command(
    raw: str,
    *,
    send: Send,
    pi_serial: str,
    registry: PortRegistry,
    by_id_dir: Path,
    max_bytes: int,
    report_reader: ReportReader,
) -> None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        log.exception("스프링 메시지가 JSON이 아닙니다.")
        return
    if not isinstance(message, dict):
        return
    rejection = await handle_command(
        message,
        pi_serial=pi_serial,
        registry=registry,
        by_id_dir=by_id_dir,
        max_bytes=max_bytes,
        report_reader=report_reader,
    )
    if rejection is None:
        return
    await send(rejection.model_dump_json(by_alias=True))
