import json
from pathlib import Path

METRIC_KEYS = {"cpuPct", "memPct", "fps", "tempC", "powerW", "errorRate"}


class ReportReader:
    def __init__(self) -> None:
        self._offset: dict[str, int] = {}

    def skip_to_end(self, usb_slot: str, device: Path) -> None:
        self._offset[usb_slot] = device.stat().st_size if device.exists() else 0

    def read_board_reports(self, usb_slot: str, device: Path) -> list[dict]:
        if not device.exists():
            return []
        size = device.stat().st_size
        if usb_slot not in self._offset or size < self._offset[usb_slot]:
            self._offset[usb_slot] = size
            return []
        offset = self._offset[usb_slot]
        if size == offset:
            return []
        with device.open("rb") as port:
            port.seek(offset)
            chunk = port.read(size - offset)
        if not chunk.endswith(b"\n"):
            newline = chunk.rfind(b"\n")
            if newline < 0:
                return []
            self._offset[usb_slot] = offset + newline + 1
            chunk = chunk[: newline + 1]
        else:
            self._offset[usb_slot] = size
        reports: list[dict] = []
        for line in chunk.splitlines():
            payload = _read_board_report(line)
            if payload is not None:
                reports.append(payload)
        return reports


def _read_board_report(line: bytes) -> dict | None:
    text = line.strip()
    if not text:
        return None
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict) or not METRIC_KEYS.intersection(body):
        return None
    return body
