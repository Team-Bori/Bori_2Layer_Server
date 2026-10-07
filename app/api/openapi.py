from pydantic import BaseModel, Field

from app.schema.messages import BoriExceptionMessage, Command, InitConnect, Report

SLOT = "usb-FTDI_FT232R_A1B2-if00"
PI_SERIAL = "10000000abcd1234"


class ReportPayload(BaseModel):
    cpu_pct: float | None = Field(default=None, alias="cpuPct", description="CPU(%). 측정할 수 없으면 null")
    mem_pct: float | None = Field(default=None, alias="memPct", description="메모리(%). 측정할 수 없으면 null")
    fps: float | None = Field(default=None, alias="fps", description="추론 FPS. 시작 전에는 null")
    temp_c: float | None = Field(default=None, alias="tempC", description="온도(℃). 측정할 수 없으면 null")
    power_w: float | None = Field(default=None, alias="powerW", description="전력(W). 센서가 없으면 null")
    error_rate: float | None = Field(default=None, alias="errorRate", description="실패 비율(%). 정확도가 아니다")

    model_config = {"populate_by_name": True}


def build_openapi() -> dict:
    schemas = _component_schemas(InitConnect, Command, Report, BoriExceptionMessage, ReportPayload)
    schemas["Report"]["properties"]["payload"] = {"$ref": "#/components/schemas/ReportPayload"}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Bori 2Layer",
            "version": "1.0.0",
            "description": (
                "파이 5 중계 서버의 WebSocket 메시지이다. "
                "파이가 SPRING_WS_URL로 스프링에 접속하고, 아래 JSON을 그 소켓으로 주고받는다. "
                "압축 파일은 command의 artifactUrl을 파이가 HTTP GET으로 받는다."
            ),
        },
        "tags": [
            {"name": "WebSocket", "description": "파이와 스프링이 이미 연 소켓의 JSON 프레임"},
        ],
        "paths": {
            "/ws/initConnect": _frame(
                "initConnect",
                "파이 → 스프링. 연결 직후, 그리고 USB가 바뀔 때 보낸다.",
                "InitConnect",
                {
                    "type": "initConnect",
                    "piSerial": PI_SERIAL,
                    "ports": [{"usbSlot": SLOT, "serialCode": "A1B2", "online": True}],
                },
            ),
            "/ws/command": _frame(
                "command",
                "스프링 → 파이. 파이는 시리얼과 USB 칸을 확인한 뒤 artifactUrl을 HTTP GET으로 받아 보드에 쓴다.",
                "Command",
                {
                    "type": "command",
                    "serialCode": "A1B2",
                    "usbSlot": SLOT,
                    "payload": {
                        "artifactUrl": "https://spring.example/artifacts/job-123",
                        "sha256": "",
                        "size": 0,
                        "exec": {},
                    },
                },
            ),
            "/ws/report": _frame(
                "report",
                "보드 → 파이 → 스프링. 파이는 payload를 바꾸지 않는다. 스프링이 받은 시각을 metric_sample.sampled_at에 적는다.",
                "Report",
                {
                    "type": "report",
                    "piSerial": PI_SERIAL,
                    "usbSlot": SLOT,
                    "serialCode": "A1B2",
                    "payload": {
                        "cpuPct": None,
                        "memPct": None,
                        "fps": None,
                        "tempC": None,
                        "powerW": None,
                        "errorRate": None,
                    },
                },
            ),
            "/ws/BoriException": _frame(
                "BoriException",
                "파이 → 스프링. command가 보드에 닿기 전에 거절되면 보낸다.",
                "BoriException",
                {
                    "type": "BoriException",
                    "piSerial": PI_SERIAL,
                    "usbSlot": SLOT,
                    "code": "UNKNOWN_PORT",
                },
            ),
        },
        "components": {"schemas": schemas},
    }


def _component_schemas(*models: type[BaseModel]) -> dict:
    components: dict = {}
    for model in models:
        piece = model.model_json_schema(ref_template="#/components/schemas/{model}")
        components.update(piece.pop("$defs", {}))
        name = "BoriException" if model.__name__ == "BoriExceptionMessage" else model.__name__
        piece["title"] = name
        components[name] = piece
    return components


def _frame(summary: str, description: str, schema_name: str, example: dict) -> dict:
    return {
        "post": {
            "tags": ["WebSocket"],
            "summary": summary,
            "description": description,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{schema_name}"},
                        "example": example,
                    }
                },
            },
            "responses": {
                "200": {"description": "소켓으로 전달되는 JSON 프레임이다."},
            },
        }
    }
