# P001 Chatub Phase 4 로드맵

**작성:** 라이카 | **참고:** 레노버 분석, openclaw-monitor 프로젝트 분석
**기반:** Phase 2(WebSocket) ✅, Phase 3(Adapter + 보안) ✅
**일자:** 2026-04-11

---

## Phase 4 개요

**목표:** openclaw-monitor 프로젝트에서 도입할 가치가 있는 기능을 Chatub에 통합하여 "HTTP 폴링 기반 관제탑"을 **"WebSocket RPC 네이티브 관제탑"**으로 진화.

**핵심 변화:** OpenClaw Gateway와의 통신을 HTTP REST에서 **WebSocket Protocol v3 RPC**로 전환.

---

## 4-1. WebSocket RPC 클라이언트 (P0)

### 현재 문제
- HTTP `/v1/models`로만 상태 확인 → 매 요청마다 TCP 연결/해제
- Gateway의 풍부한 RPC 기능(agents CRUD, sessions, files)을 사용 불가
- 에이전트 상태를 indirect하게만 파악 (모델 수로 추정)

### openclaw-monitor의 해법
```
WebSocket Protocol v3:
  1. connect.challenge (nonce + timestamp)
  2. connect 요청 (Ed25519 디바이스 서명 + token)
  3. hello-ok → 영구 연결 유지
  4. RPC: agents.list, sessions.list, chat.send 등
  5. 이벤트: tick(30s), agent(delta), chat(final/error)
  6. 자동 재연결 (exponential backoff, 최대 30s)
```

### 도입 계획

**백엔드 (라이카):**
- `backend/adapters/openclaw_ws.py` — WebSocket RPC 클라이언트
  - `connect()` — challenge-response 핸드쉐이크
  - `rpc(method, params)` — 요청/응답 매핑 (id 기반)
  - `chat_send(agent_id, message, on_delta)` — 스트리밍
  - `tick_watchdog` — 30s tick 타임아웃 감지
  - 자동 재연결 (1s → 2s → 4s → ... → 30s)
- `backend/adapters/openclaw.py`(기존)과 병행 사용
  - ws 연결 성공 → RPC 사용
  - ws 실패 → HTTP fallback (기존 방식)

**에이전트 CRUD (신규):**
```python
# 현재: 읽기 전용
GET /v1/models → 모델 목록

# Phase 4: WebSocket RPC
agents.list → 에이전트 목록 (id, name, emoji, workspace)
agents.create(name, workspace, emoji) → 에이전트 생성
agents.delete(agent_id) → 에이전트 삭제
agents.files.list(agent_id) → 파일 목록
agents.files.get(agent_id, name) → 파일 읽기
agents.files.set(agent_id, name, content) → 파일 쓰기
sessions.list → 전체 세션 (key, status, tokens, model, channel)
sessions.get(key, limit) → 세션 메시지 히스토리
chat.send(session_key, message) → SSE 스트리밍
chat.abort(session_key) → 채팅 중단
models.list → 사용 가능 모델
config.get → Gateway 설정 조회
cron.list → 크론 작업 목록
```

### Termux 제약 대응
- Ed25519 디바이스 서명 → `cryptography` 패키지 빌드 불가
- **대안 1:** Bearer 토큰만 사용 (device 필드 생략, `auth.token`만 전달)
- **대안 2:** VPS 배포 후 `cryptography` 설치 가능 → Ed25519 활성화
- **대안 3:** `pynacl` 또는 `pure-python-ed25519` 시도

### API 라우트 (신규)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/gateways/:id/agents` | 에이전트 목록 |
| `POST` | `/api/gateways/:id/agents` | 에이전트 생성 |
| `DELETE` | `/api/gateways/:id/agents/:agentId` | 에이전트 삭제 |
| `GET` | `/api/gateways/:id/agents/:agentId/files` | 파일 목록 |
| `GET` | `/api/gateways/:id/agents/:agentId/files/:name` | 파일 읽기 |
| `PUT` | `/api/gateways/:id/agents/:agentId/files/:name` | 파일 쓰기 |
| `GET` | `/api/gateways/:id/sessions` | 세션 목록 |
| `GET` | `/api/gateways/:id/sessions/:key` | 세션 메시지 |

---

## 4-2. 페어링 상태 4단계 분류 (P0)

### 현재 문제
- online/offline/error 3가지만 구분
- 미승인 디바이스를 online으로 잘못 표시 가능

### 도입 계획
```
connected        → 🟢 정상 연결 (RPC 동작)
pairing-required → 🟡 페어링 필요 (openclaw devices approve 안내)
error            → 🔴 연결 오류 (원인 표시)
disconnected     → ⚪ 연결 끊김
```

### UI 변경 (래노버)
- Gateway 카드 상태 표시 4색 분기
- `pairing-required` 시 안내 카드 표시:
  ```
  ⚠️ 이 디바이스는 승인 대기 중입니다.
  아래 명령어를 실행하세요:
  openclaw devices approve <requestId>
  [복사 버튼]
  ```

---

## 4-3. 응답 지연(Latency) 측정 (P1)

### 현재 문제
- health check는 성공/실패만 반환
- 느린 응답을 감지할 수 없음

### 도입 계획
```python
async def health(self, conn):
    start = time.monotonic()
    # ... probe ...
    latency_ms = (time.monotonic() - start) * 1000
    return HealthStatus(latency_ms=round(latency_ms), ...)
```

### UI 변경 (래노버)
- Gateway 카드에 latency 표시: `45ms` / `1200ms` / `timeout`
- 색상 분기: <100ms 초록, <500ms 노랑, >500ms 빨강

---

## 4-4. 에이전트 파일 편집기 (P1)

### 현재 문제
- 에이전트 설정(SOUL.md, IDENTITY.md 등)을 관제탑에서 볼 수 없음

### 도입 계획
- 프론트엔드: DetailView에 "Files" 탭 추가
- 파일 목록 → 클릭 → 텍스트 편집기 (monospace textarea)
- 저장 시 `agents.files.set` RPC 호출

### UI 변경 (래노버)
```
[Agents 탭]
  에이전트 목록 (클릭)
    → 에이전트 상세
      → Files 섹션
        SOUL.md  IDENTITY.md  AGENTS.md  TOOLS.md  [클릭]
          → 편집기 (textarea, monospace)
            → [저장] [취소]
```

---

## 4-5. 세션 히스토리 뷰어 (P1)

### 현재 문제
- 채팅 로그는 Chatub 자체 DB에만 저장
- 실제 세션 메시지를 볼 수 없음

### 도입 계획
- `sessions.list` RPC → 세션 목록
- `sessions.get(key, limit)` → 메시지 히스토리
- ChatBubble 컴포넌트로 role별 시각화

### UI 변경 (래노버)
```
[Sessions 탭]
  세션 목록
    agent:main:telegram:-100xxx  done  1,234 tok  09:30
    agent:main:webchat           done  567 tok    10:15
    [클릭]
      → 메시지 히스토리
        🧑 user: "안녕!"
        🤖 assistant: "안녕하세요! 무엇을 도와드릴까요?"
```

---

## 4-6. SidePanel 리사이즈 (P2)

### openclaw-monitor 참고
- 드래그로 좌측 패널 폭 조절 (280px ~ 520px)
- 접기/펼치기 토글

### UI 변경 (래노버)
- 좌측 에이전트 목록 패널에 드래그 핸들 추가
- CSS `resize` 또는 JavaScript mousedown/mousemove 구현

---

## 4-7. i18n 다국어 지원 (P2)

### openclaw-monitor 참고
- en/ko/ja/zh 4개국어
- 브라우저 `navigator.language` 자동 감지

### 도입 계획
- 프론트엔드: `lib/i18n/` 패턴 차용
- 현재는 한국어만 → 영어/일본어 추가
- 백엔드 메시지는 그대로 한국어 유지

---

## 4-8. 외부 등록 스크립트 개선 (P2)

### openclaw-monitor 참고
- `register-termux.sh` — Termux 전용 IP 자동 탐지
- `register.sh` — Linux/macOS/Windows
- 중복 URL 체크

### 도입 계획
- 현재 register3 페이지를 보조하는 CLI 스크립트
- `scripts/register.sh` 추가:
  ```bash
  # IP 자동 탐지 + curl 등록
  bash scripts/register.sh --name "라이카" --token "xxx"
  ```

---

## 체크포인트

| CP | 내용 | 담당 | 우선순위 | 의존 |
|----|------|------|---------|------|
| CP12 | WebSocket RPC 클라이언트 | 라이카 | P0 | — |
| CP13 | 페어링 상태 4단계 | 라이카+래노버 | P0 | CP12 |
| CP14 | Latency 측정 | 라이카 | P1 | CP12 |
| CP15 | 에이전트 CRUD API | 라이카 | P1 | CP12 |
| CP16 | 에이전트 파일 편집기 | 래노버 | P1 | CP15 |
| CP17 | 세션 히스토리 뷰어 | 래노버 | P1 | CP15 |
| CP18 | SidePanel 리사이즈 | 래노버 | P2 | — |
| CP19 | i18n 다국어 | 래노버 | P2 | — |
| CP20 | 등록 스크립트 | 라이카 | P2 | — |

---

## Phase 1~4 전체 진행도

| Phase | 상태 | 완료율 |
|-------|------|--------|
| Phase 1 | ✅ 완료 | 100% |
| Phase 2 | ✅ 완료 | 100% |
| Phase 3 | ✅ 완료 (P0/P1) | 100% |
| Phase 4 | 🔄 P0 시작 | 0% |

---

## 파일 소유권 (Phase 4 업데이트)

| 파일/디렉토리 | 주 담당 | 리뷰어 |
|--------------|---------|--------|
| `backend/adapters/openclaw_ws.py` | 라이카 | 레노버 |
| `backend/adapters/openclaw.py` | 라이카 | 레노버 |
| `backend/routers/gateways.py` | 라이카 | 레노버 |
| `backend/app.py` | 라이카 | 전원 |
| `src/index.html` | 래노버 | 라이카 |
| `scripts/register.sh` | 라이카 | 레노버 |
| `DESIGN.md` | 라이카 | 전원 |
| `STATUS.md` | 라이카 | 회장님 |

## Push 순서 (변경 없음)

1. **래노버** (src/) → commit & push
2. **라이카** (backend/ + docs + scripts) → `git pull --rebase` → commit & push

---

## 참고: openclaw-monitor에서 차용한 것

| 항목 | 원본 파일 | 도입 여부 |
|------|----------|----------|
| WebSocket RPC 클라이언트 | `lib/openclaw-gateway.ts` | ✅ CP12 |
| Ed25519 디바이스 인증 | `lib/openclaw-gateway.ts` | ⚠️ VPS 배포 후 |
| 영구 연결 풀 | `lib/gateway-pool.ts` | ✅ CP12 |
| 페어링 안내 | `OpenClawPairingStatusCard.tsx` | ✅ CP13 |
| 에이전트 CRUD | `api/gateways/[id]/agents/*.ts` | ✅ CP15 |
| 파일 편집 | `DetailView.tsx` files 섹션 | ✅ CP16 |
| 세션 뷰어 | `DetailView.tsx` sessions 섹션 | ✅ CP17 |
| DeskRPG UI 컴포넌트 | `ui/Badge,Button,Card...tsx` | 검토 중 |
| SidePanel 리사이즈 | `SidePanel.tsx` | ✅ CP18 |
| i18n | `lib/i18n/` | ✅ CP19 |
| 등록 스크립트 | `scripts/register*.sh` | ✅ CP20 |
