# P001 Chatub Phase 3 로드맵

**작성:** 라이카 | **참고:** 레노버 분석, 라이카 분석, OpenClaw Office 분석
**기반:** Phase 2A(WebSocket 실시간 상태) ✅, Phase 2B(WebSocket RPC + 토큰 통계) ✅
**일자:** 2026-04-11

---

## Phase 3 개요

**목표:** Chatub를 "OpenClaw 전용 채팅 앱"에서 **"멀티 런타임 에이전트 관제탑"**으로 격상.

**핵심 철학:** 새로운 에이전트 런타임(Hermes 등)이 추가되어도 최소한의 코드 변경으로 연결 가능.

---

## 3-1. Agent Adapter 패턴 (P0)

### 현재 문제
- `gateways.py`와 `app.py`에 OpenClaw 전용 로직이 직접 작성됨
- 새 런타임 추가 시 여러 파일 수정 필요

### 구조

```
backend/adapters/
├── __init__.py
├── base.py           # AgentAdapter 공통 인터페이스
├── openclaw.py       # OpenClaw Gateway 어댑터 (현재 로직 이동)
├── hermes.py         # Hermes 어댑터 (미래)
└── generic_openai.py # OpenAI-compatible 범용 어댑터
```

### 인터페이스

```python
class AgentAdapter(ABC):
    kind: str  # "openclaw" | "hermes" | "openai-compatible"

    async def probe(self, conn: AgentConnection) -> ProbeResult:
        """연결 테스트 — URL, 토큰 유효성, 기능 감지"""

    async def health(self, conn: AgentConnection) -> HealthStatus:
        """상태 확인 — online/offline + 5가지 상태"""

    async def send_message(self, conn, messages, stream=False) -> AgentResponse:
        """채팅 전송 — 단일/브로드캐스트"""

    async def list_models(self, conn) -> list[ModelInfo]:
        """모델 조회"""

    async def list_sessions(self, conn) -> list[SessionInfo]:
        """세션 목록"""

    async def get_capabilities(self, conn) -> dict:
        """지원 기능 반환"""
```

### 연결 모델

```python
class AgentConnection:
    id: str
    name: str
    kind: str              # "openclaw" | "hermes" | "openai-compatible" | "auto"
    base_url: str          # "http://192.168.0.109:18789"
    api_key: str           # 암호화 저장
    capabilities: dict     # {"chat":true, "streaming":true, "tools":true, ...}
    status: str            # "online" | "offline" | "error"
    state: str             # "idle" | "working" | "speaking" | "tool_calling" | "error"
    stats: dict            # {"prompt_tokens":0, "completion_tokens":0, "messages":0}
```

### 적용 범위
- `gateways.py` → `adapters/openclaw.py`로 이관
- `app.py`의 broadcast/gateway-chat → Adapter 경유로 변경
- `gateways` DB 테이블에 `kind`, `capabilities` 컬럼 추가

---

## 3-2. 연결 마법사 — Auto Detect (P0)

### 현재 문제
- 등록이 수동 curl 또는 API 호출로만 가능
- 연결 실패 시 원인 불명확

### 흐름

```
사용자 입력: Base URL + API Key (선택)
    ↓
[1단계] Auto Detect
    GET /v1/models → OpenAI-compatible 확인
    GET /health    → 런타임 종류 판별
    ↓
[2단계] 기능 감지
    스트리밍 테스트 → streaming capability
    도구 호출 테스트 → tools capability
    세션 조회 테스트 → sessions capability
    ↓
[3단계] 결과
    ✅ "OpenClaw 감지됨 — Chat ✅ Stream ✅ Tools ✅ Sessions ❌"
    ❌ "인증 실패" / "CORS 차단" / "타임아웃" / "미지원 API"
    ↓
[4단계] 자동 저장
    capabilities + stats 초기화
```

### 구현
- **백엔드:** `POST /api/gateways/auto-detect` 엔드포인트
- **프론트엔드:** 관제탑 "에이전트 추가" 버튼 → 마법사 UI (래노버 협업)
- **에러 코드 구조화:**
  ```python
  class ConnectionError(Enum):
      AUTH_FAILED = "auth_failed"
      CORS_BLOCKED = "cors_blocked"
      TIMEOUT = "timeout"
      UNSUPPORTED_API = "unsupported_api"
      NETWORK_ERROR = "network_error"
      UNKNOWN = "unknown"
  ```

---

## 3-3. Capability Flag 기반 UI 분기 (P1)

### 현재 문제
- 모든 Gateway를 동일하게 취급
- 미지원 기능도 버튼이 활성화됨

### 적용
- 관제탑 에이전트 카드에 **기능 배지** 표시
  ```
  🟢 Chat  🟢 Stream  🟢 Tools  ⚪ Sessions
  ```
- 미지원 기능 → 버튼 비활성화 + 툴팁 "이 에이전트는 미지원"
- Adapter가 반환한 capabilities를 프론트엔드에 전달

---

## 3-4. 스트리밍 중계 (P1)

### 현재 문제
- Gateway 응답을 전체 받아서 JSON 반환
- 긴 응답 시 체감이 느림

### 구현
```
Gateway SSE (/v1/chat/completions stream:true)
    ↓ httpx AsyncClient stream
FastAPI StreamingResponse
    ↓
WebSocket → 프론트엔드 실시간 표시
```

- `AgentAdapter.send_message(conn, messages, stream=True)` → `AsyncIterable[str]`
- 브로드캐스트 시 여러 에이전트 응답을 병렬 스트림으로 WebSocket에 푸시
- **Stream Multiplexer:** 여러 스트림을 하나의 WebSocket에 인터리빙

---

## 3-5. 보안 강화 (P1)

### 5-1. API Key 암호화
```python
from cryptography.fernet import Fernet
# DB 저장 시 암호화, 사용 시 복호화
# 키는 환경변수 또는 .env
```

### 5-2. Rate Limiting
```python
from slowapi import Limiter
# /api/gateway-broadcast → 30/minute
# /api/gateway-chat → 60/minute
```

### 5-3. CORS 정책 강화
```
현재: 모든 Origin 허용
개선: VPS 도메인만 허용
```

---

## 3-6. 운영 기능 (P2)

### 6-1. 연결 로그
- 각 Gateway 연결/해제/실패 이벤트를 DB에 기록
- 관제탑에서 타임라인으로 표시

### 6-2. 알림
- 에이전트가 오프라인 → 알림
- 토큰 사용량 임계치 초과 → 알림
- WebSocket으로 프론트엔드에 푸시

### 6-3. 설정 내보내기/가져오기
- 등록된 Gateway 목록을 JSON으로 내보내기/가져오기
- 새 기기에서 빠른 복구

---

## 체크포인트

| CP | 내용 | 담당 | 우선순위 |
|----|------|------|---------|
| CP6 | Agent Adapter 패턴 + DB 마이그레이션 | 라이카 | P0 |
| CP7 | 연결 마법사 (Auto Detect) | 라이카+래노버 | P0 |
| CP8 | 스트리밍 중계 (Stream Multiplexer) | 라이카 | P1 |
| CP9 | Capability Flag UI | 래노버 | P1 |
| CP10 | 보안 강화 (암호화, Rate Limit) | 라이카 | P1 |
| CP11 | 운영 기능 (로그, 알림) | 라이카+래노버 | P2 |

---

## 파일 소유권 (업데이트)

| 파일/디렉토리 | 주 담당 | 리뷰어 |
|--------------|---------|--------|
| `backend/adapters/` | 라이카 | 레노버 |
| `backend/routers/` | 라이카 | 샤오미 |
| `backend/app.py` | 라이카 | 전원 |
| `src/index.html` | 래노버 | 라이카 |
| `DESIGN.md` | 라이카 | 전원 |
| `STATUS.md` | 라이카 | 회장님 |
| `TASKS.md` | 라이카 | 전원 |

## Push 순서 (변경 없음)

1. **래노버** (frontend/) → commit & push
2. **라이카** (backend/ + docs) → `git pull --rebase` → commit & push
3. **샤오미** (테스트/리뷰) → 이슈 리포트
