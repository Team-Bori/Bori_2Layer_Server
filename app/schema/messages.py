from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.registry import PortRegistry


class PortStatus(BaseModel):
    usb_slot: str = Field(alias="usbSlot", description="/dev/serial/by-id 이름")
    serial_code: str = Field(alias="serialCode", description="보드 시리얼. cloud_board.serial_code와 같다")
    online: bool = Field(description="지금 꽂혀 있으면 true")

    model_config = {"populate_by_name": True}


class InitConnect(BaseModel):
    type: Literal["initConnect"] = "initConnect"
    pi_serial: str = Field(alias="piSerial", description="파이 시리얼")
    ports: list[PortStatus] = Field(default_factory=list, description="지금 꽂힌 USB 보드. 없으면 빈 배열")

    model_config = {"populate_by_name": True}


class CommandPayload(BaseModel):
    artifact_url: str = Field(alias="artifactUrl", description="압축 파일 주소. 파이가 HTTP GET으로 받는다. 보드에는 넘기지 않는다")
    sha256: str = Field(description="파일 해시")
    size: int = Field(description="파일 바이트 수. 0보다 작거나 ARTIFACT_MAX_BYTES를 넘으면 OVERSIZE")
    exec: dict[str, Any] = Field(default_factory=dict, description="보드에 전달할 실행 형식. 파이는 해석하지 않는다")

    model_config = {"populate_by_name": True}


class Command(BaseModel):
    type: Literal["command"]
    serial_code: str = Field(alias="serialCode", description="학생이 고른 보드 시리얼")
    usb_slot: str = Field(alias="usbSlot", description="그 보드가 꽂힌 USB 칸. 스프링이 initConnect로 알아 둔 값")
    payload: CommandPayload

    model_config = {"populate_by_name": True}


class BoriExceptionMessage(BaseModel):
    type: Literal["BoriException"] = "BoriException"
    pi_serial: str = Field(alias="piSerial", description="파이 시리얼")
    usb_slot: str | None = Field(default=None, alias="usbSlot", description="대상 칸")
    code: Literal["UNKNOWN_PORT", "PORT_CLOSED", "OVERSIZE"] = Field(
        description="UNKNOWN_PORT: 칸이 없거나 시리얼이 다름. PORT_CLOSED: 꺼져 있거나 장치 경로가 없음. OVERSIZE: 크기가 범위를 벗어남"
    )

    model_config = {"populate_by_name": True, "title": "BoriException"}


class Report(BaseModel):
    type: Literal["report"] = "report"
    pi_serial: str = Field(alias="piSerial", description="파이가 붙인다")
    usb_slot: str = Field(alias="usbSlot", description="파이가 붙인다")
    serial_code: str = Field(alias="serialCode", description="보드 시리얼. 파이가 붙인다")
    payload: dict[str, Any] = Field(description="보드가 측정한 값. 파이는 바꾸지 않는다. 측정할 수 없으면 null")

    model_config = {"populate_by_name": True}


def build_report(
    pi_serial: str,
    usb_slot: str,
    serial_code: str,
    payload: dict[str, Any],
) -> Report:
    return Report(
        pi_serial=pi_serial,
        usb_slot=usb_slot,
        serial_code=serial_code,
        payload=payload,
    )


def build_init_connect(pi_serial: str, registry: PortRegistry) -> InitConnect:
    ports = [
        PortStatus(
            usb_slot=link.usb_slot,
            serial_code=link.serial_code,
            online=link.online,
        )
        for link in registry.ports()
    ]
    return InitConnect(pi_serial=pi_serial, ports=ports)
