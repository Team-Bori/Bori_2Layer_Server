from pathlib import Path

SERIAL_PATH = Path("/sys/firmware/devicetree/base/serial-number")
CPUINFO_PATH = Path("/proc/cpuinfo")


def read_pi_serial(
    override: str = "",
    serial_path: Path = SERIAL_PATH,
    cpuinfo_path: Path = CPUINFO_PATH,
) -> str:
    if override.strip():
        return override.strip()

    if serial_path.exists():
        serial = serial_path.read_bytes().split(b"\0", 1)[0].decode().strip()
        if serial:
            return serial

    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text().splitlines():
            if line.startswith("Serial"):
                serial = line.split(":", 1)[1].strip()
                if serial:
                    return serial

    raise RuntimeError("라즈베리파이 시리얼을 읽지 못했습니다.")
