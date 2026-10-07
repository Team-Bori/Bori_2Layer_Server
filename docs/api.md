# Bori 2Layer API

파이 5에서 도는 중계 서버 명세. 이 파일이 스프링·보드 Agent와의 계약이다.

| 항목 | 값 |
|------|----|
| 스프링 소켓 | 환경 변수 `SPRING_WS_URL` (파이 → 스프링, 나가는 연결) |
| Swagger | `http://<파이>:8000/docs` |
| 메시지 형식 | JSON. 필드명은 camelCase |
| 공통 필드 | `type` |

상태 표시: `구현됨` / `예정`. 예정 항목은 필드만 잡아 둔 것이다.

## 한 번 실행할 때

1. 스프링은 학생이 고른 보드(예: Jetson Nano)의 `serialCode`로 `cloud_board`를 찾는다. 그 행의 `pi_id`와 `usbSlot`이, 그 보드가 꽂힌 파이와 USB 칸이다. 이 값은 직전 `initConnect`로 적혀 있다.
2. 스프링은 그 파이와 이미 연결된 WebSocket으로 `command`를 보낸다. 내용에 보드 `serialCode`와 `usbSlot`이 들어 있다.
3. 파이는 그 칸에 지금 그 시리얼이 꽂혀 있는지 확인한 뒤, 파일을 그 USB로 넣는다.
4. 보드 Agent가 건네받은 코드 또는 AI 모델을 실행하고, 성능 추이를 USB로 파이에게 보낸다.
5. 파이는 그 추이를 `report`로 만들어, 스프링과 이미 연결된 그 WebSocket으로 보낸다. 보드가 스프링에 소켓을 따로 열지 않는다.

---

## WebSocket

상태: 연결, `initConnect`, `command`, `report`가 구현됨.

- 파이가 `SPRING_WS_URL`로 접속한다.
- 붙는 즉시 `initConnect`를 보낸다.
- 끊기면 다시 붙고, 붙을 때마다 `initConnect`를 다시 보낸다.
- 파이 번호(`host_pi.id`)는 이 메시지로 받지 않는다. 스프링이 `piSerial`로 찾는다.

### initConnect

상태: 구현됨

방향: 파이 → 스프링

보내는 시점: 소켓 연결 직후. USB가 바뀌면 다시 보낸다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | `"initConnect"` | |
| `piSerial` | string | 파이 시리얼 |
| `ports` | array | 지금 꽂힌 USB 보드. 없으면 `[]` |
| `ports[].usbSlot` | string | `/dev/serial/by-id` 이름 |
| `ports[].serialCode` | string | 보드 시리얼. `cloud_board.serial_code`와 같다 |
| `ports[].online` | boolean | 지금 꽂혀 있으면 true |

```json
{
  "type": "initConnect",
  "piSerial": "10000000abcd1234",
  "ports": [
    {
      "usbSlot": "usb-FTDI_FT232R_A1B2-if00",
      "serialCode": "A1B2",
      "online": true
    }
  ]
}
```

### command

상태: 구현됨

방향: 스프링 → 파이 → 해당 USB 보드

스프링이 보드를 고른 뒤, 그 보드의 시리얼과 USB 칸을 함께 넘긴다. 파이는 둘을 다시 찾지 않는다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | `"command"` | |
| `serialCode` | string | 학생이 고른 보드 시리얼 |
| `usbSlot` | string | 그 보드가 꽂힌 USB 칸. 스프링이 `initConnect`로 알아 둔 값 |
| `payload.artifactUrl` | string | 압축 파일을 받을 주소. 보드에는 넘기지 않는다 |
| `payload.sha256` | string | 파일 해시 |
| `payload.size` | number | 파일 바이트 수 |
| `payload.exec` | object | 보드에 전달할 코드 또는 AI 모델 실행 형식. 필드는 아래에서 채운다 |

```json
{
  "type": "command",
  "serialCode": "A1B2",
  "usbSlot": "usb-FTDI_FT232R_A1B2-if00",
  "payload": {
    "artifactUrl": "https://spring.example/artifacts/job-123",
    "sha256": "",
    "size": 0,
    "exec": {}
  }
}
```

`exec` 필드:

| 필드 | 타입 | 설명 |
|------|------|------|
| | | |

보드가 USB로 받는 값: `size`, `sha256`, `exec`, 압축 파일 바이트.

### report

상태: 구현됨

방향: 보드 → 파이 → 스프링

파이는 `payload`를 바꾸지 않는다. 측정할 수 없는 값은 `null`이다. `0`으로 채우지 않는다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | `"report"` | |
| `piSerial` | string | 파이가 붙인다 |
| `usbSlot` | string | 파이가 붙인다 |
| `serialCode` | string | 보드 시리얼. 파이가 붙인다 |
| `payload.cpuPct` | number \| null | CPU(%) |
| `payload.memPct` | number \| null | 메모리(%) |
| `payload.fps` | number \| null | 추론 FPS. 시작 전에는 null |
| `payload.tempC` | number \| null | 온도(℃) |
| `payload.powerW` | number \| null | 전력(W). 센서가 없으면 null |
| `payload.errorRate` | number \| null | 실패 비율(%). 정확도가 아니다 |

```json
{
  "type": "report",
  "piSerial": "10000000abcd1234",
  "usbSlot": "usb-FTDI_FT232R_A1B2-if00",
  "serialCode": "A1B2",
  "payload": {
    "cpuPct": null,
    "memPct": null,
    "fps": null,
    "tempC": null,
    "powerW": null,
    "errorRate": null
  }
}
```

스프링이 이 메시지를 받은 시각을 `metric_sample.sampled_at`에 적는다.

### BoriException

상태: 구현됨. `command`가 보드에 닿기 전에 거절되면 보낸다.

방향: 파이 → 스프링

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | `"BoriException"` | |
| `piSerial` | string | 파이 시리얼 |
| `usbSlot` | string \| null | 대상 칸 |
| `code` | string | 아래 셋 중 하나 |

| code | 언제 |
|------|------|
| `UNKNOWN_PORT` | 레지스트리에 없는 `usbSlot`이거나, 그 칸의 `serialCode`가 명령과 다름 |
| `PORT_CLOSED` | 칸은 있으나 `online`이 false이거나, 장치 경로가 없음 |
| `OVERSIZE` | `payload.size`가 0보다 작거나 상한을 넘음. 파일을 받지 않음 |

```json
{
  "type": "BoriException",
  "piSerial": "10000000abcd1234",
  "usbSlot": "usb-FTDI_FT232R_A1B2-if00",
  "code": "UNKNOWN_PORT"
}
```

상한(MB):

| 항목 | 값 |
|------|----|
| 파일 크기 상한 | 100MB. 환경 변수 `ARTIFACT_MAX_BYTES`로 바꿈 |

---

## 환경 변수

| 이름 | 필수 | 설명 |
|------|------|------|
| `SPRING_WS_URL` | 예 | 스프링 WebSocket 주소. 없으면 소켓을 열지 않는다 |
| `PI_SERIAL_CODE` | 아니오 | 개발 머신에서만 파이 시리얼을 대신 넣는다. 파이에서는 장치 시리얼을 읽는다 |
