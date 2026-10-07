from pathlib import Path


def serial_from_slot_name(name: str) -> str:
    base = name.split("-if", 1)[0]
    if "_" not in base:
        return ""
    return base.rsplit("_", 1)[-1]


def scan_ports(by_id_dir: Path) -> list[tuple[str, str]]:
    if not by_id_dir.is_dir():
        return []
    found: list[tuple[str, str]] = []
    for entry in sorted(by_id_dir.iterdir(), key=lambda item: item.name):
        if entry.name.startswith(".") or entry.is_dir():
            continue
        found.append((entry.name, serial_from_slot_name(entry.name)))
    return found
