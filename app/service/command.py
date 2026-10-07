import asyncio
import logging
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.core.registry import PortLink, PortRegistry
from app.schema.messages import BoriExceptionMessage, Command
from app.service.artifact import download_artifact, verify_artifact
from app.service.usb_link import device_path, send_to_board

log = logging.getLogger(__name__)


def receive_command(message: dict) -> Command | None:
    if message.get("type") != "command":
        return None
    try:
        return Command.model_validate(message)
    except ValidationError:
        log.exception("command JSON이 명세와 다릅니다.")
        return None


def find_port(registry: PortRegistry, usb_slot: str) -> PortLink | None:
    for link in registry.ports():
        if link.usb_slot == usb_slot:
            return link
    return None


def match_serial(link: PortLink, serial_code: str) -> bool:
    return link.serial_code == serial_code


def check_artifact_size(size: int, limit: int) -> bool:
    return 0 <= size <= limit


def build_bori_exception(
    pi_serial: str,
    usb_slot: str,
    code: str,
) -> BoriExceptionMessage:
    return BoriExceptionMessage(pi_serial=pi_serial, usb_slot=usb_slot, code=code)


async def handle_command(
    message: dict,
    *,
    pi_serial: str,
    registry: PortRegistry,
    by_id_dir: Path,
    max_bytes: int,
    report_reader=None,
) -> BoriExceptionMessage | None:
    command = receive_command(message)
    if command is None:
        return None

    link = find_port(registry, command.usb_slot)
    if link is None or not match_serial(link, command.serial_code):
        return build_bori_exception(pi_serial, command.usb_slot, "UNKNOWN_PORT")
    if not link.online:
        return build_bori_exception(pi_serial, command.usb_slot, "PORT_CLOSED")
    if not check_artifact_size(command.payload.size, max_bytes):
        return build_bori_exception(pi_serial, command.usb_slot, "OVERSIZE")

    device = device_path(by_id_dir, command.usb_slot)
    if device is None or not device.exists():
        return build_bori_exception(pi_serial, command.usb_slot, "PORT_CLOSED")

    with tempfile.TemporaryDirectory() as raw:
        archive = Path(raw) / "artifact"
        await asyncio.to_thread(download_artifact, command.payload.artifact_url, archive)
        if not verify_artifact(archive, command.payload.sha256, command.payload.size):
            log.error("받은 파일의 해시 또는 크기가 명령과 다릅니다.")
            return None
        await asyncio.to_thread(
            send_to_board,
            device,
            command.payload.sha256,
            command.payload.size,
            command.payload.exec,
            archive,
        )
        if report_reader is not None:
            report_reader.skip_to_end(command.usb_slot, device)
    return None
