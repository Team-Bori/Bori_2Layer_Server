import json
from pathlib import Path


def device_path(by_id_dir: Path, usb_slot: str) -> Path | None:
    if not usb_slot or usb_slot in {".", ".."} or "/" in usb_slot:
        return None
    return by_id_dir / usb_slot


def send_to_board(
    device: Path,
    sha256: str,
    size: int,
    exec_info: dict,
    file_path: Path,
) -> None:
    header = json.dumps(
        {"sha256": sha256, "size": size, "exec": exec_info},
        separators=(",", ":"),
    ).encode()
    with device.open("wb") as port:
        port.write(header + b"\n")
        port.write(file_path.read_bytes())
