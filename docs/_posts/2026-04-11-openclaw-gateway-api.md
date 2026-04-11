---
layout: page
permalink: /openclaw-gateway-api/
title: "OpenClaw Gateway API 완전 가이드"
category: 기술토론
---

> OpenClaw Gateway는 WebSocket + HTTP 멀티플렉스 구조로 동작한다. 단일 포트에서 모든 API에 접근할 수 있다. 이 문서는 Chatub 관제탑이 OpenClaw Gateway와 통신하는 데 사용하는 API를 상세히 설명한다.

---

## ⚙️ 기본 설정

### 포트와 주소

```
기본 포트: 18789
기본 주소: http://127.0.0.1:18789
LAN 주소: http://<IP>:18789 (예: http://192.168.0.101:18789)
```

### 인증 (Authentication)

Gateway 토큰으로 Bearer 인증:

```bash
# 환경변수로 확인
echo $OPENCLAW_GATEWAY_TOKEN

# 설정에서 확인
cat ~/.openclaw/openclaw.json | grep token
```

모든 HTTP 요청에 헤더 포함:

```bash
-H "Authorization: Bearer <GATEWAY_TOKEN>"
```

### OpenAI HTTP 엔드포인트 활성화

**기본적으로 비활성화** 되어 있다. `openclaw.json`에서 활성화:

```json
{
  "gateway": {
    "http": {
      "endpoints": {
        "chatCompletions": { "enabled": true }
      }
    }
  }
}
```

---

## 📋 1. 모델 목록 조회 (`GET /v1/models`)

에이전트 목록을 반환한다. **"모델"이 아닌 "에이전트 타겟"**이다.

```bash
curl -s http://127.0.0.1:18789/v1/models \
  -H "Authorization: Bearer <TOKEN>"
```

**응답:**

```json
{
  "object": "list",
  "data": [
    { "id": "openclaw", "object": "model", "owned_by": "openclaw" },
    { "id": "openclaw/default", "object": "model", "owned_by": "openclaw" },
    { "id": "openclaw/main", "object": "model", "owned_by": "openclaw" }
  ]
}
```

**핵심:**
- `openclaw` — 기본 에이전트
- `openclaw/default` — 기본 에이전트의 안정적인 별칭 (환경 간 일관)
- `openclaw/<agentId>` — 특정 에이전트 (예: `openclaw/main`)

---

## 💬 2. 채팅 (`POST /v1/chat/completions`)

OpenAI Chat Completions와 호환되는 엔드포인트.

### 기본 요청

```bash
curl -s http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw/default",
    "messages": [
      {"role": "user", "content": "안녕!"}
    ]
  }'
```

### 응답

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "안녕하세요! 무엇을 도와드릴까요?"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 15,
    "completion_tokens": 8,
    "total_tokens": 23
  }
}
```

### 스트리밍 (SSE)

```bash
curl -N http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw/default",
    "stream": true,
    "messages": [
      {"role": "user", "content": "긴 이야기 해줘"}
    ]
  }'
```

**스트리밍 응답:**
```
data: {"choices":[{"delta":{"content":"한"},"index":0}]}

data: {"choices":[{"delta":{"content":"번"},"index":0}]}

data: [DONE]
```

### 고급 옵션

| 헤더 | 설명 | 예시 |
|------|------|------|
| `x-openclaw-model` | 백엔드 모델 오버라이드 | `openai/gpt-5.4` |
| `x-openclaw-session-key` | 세션 라우팅 | `main`, `custom-session` |
| `x-openclaw-message-channel` | 채널 컨텍스트 | `telegram`, `discord` |
| `x-openclaw-agent-id` | 에이전트 ID (호환) | `main` |

**모델 오버라이드 예:**

```bash
curl -s http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-model: openai/gpt-5.4" \
  -d '{
    "model": "openclaw/default",
    "messages": [{"role":"user","content":"hi"}]
  }'
```

---

## 🔧 3. 도구 직접 호출 (`POST /tools/invoke`)

에이전트를 거치지 않고 **단일 도구를 직접 실행**한다. 항상 활성화되어 있다.

```bash
curl -s http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "sessions_list",
    "action": "json",
    "args": {}
  }'
```

### 요청 필드

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `tool` | string | ✅ | 도구 이름 |
| `action` | string | ❌ | 도구 액션 |
| `args` | object | ❌ | 도구 인자 |
| `sessionKey` | string | ❌ | 대상 세션 (기본: `main`) |
| `dryRun` | boolean | ❌ | 예약 (현재 미사용) |

### 유용한 도구 호출 예시

**세션 목록:**
```bash
curl -s http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"tool":"sessions_list","action":"json","args":{}}'
```

**세션 히스토리:**
```bash
curl -s http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"tool":"sessions_history","args":{"sessionKey":"main","limit":10}}'
```

**상태 확인:**
```bash
curl -s http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"tool":"session_status"}'
```

### ⚠️ 보안: 기본 차단 도구

다음 도구는 기본적으로 HTTP에서 차단된다 (RCE 위험):

- `exec`, `spawn`, `shell` — 명령 실행
- `fs_write`, `fs_delete`, `fs_move` — 파일 조작
- `apply_patch` — 파일 수정
- `sessions_spawn`, `sessions_send` — 세션 조작
- `cron` — 자동화
- `gateway` — 게이트웨이 설정
- `nodes` — 노드 제어

**허용/차단 커스터마이징:**

```json
{
  "gateway": {
    "tools": {
      "deny": ["browser"],
      "allow": ["gateway"]
    }
  }
}
```

### 응답 코드

| 코드 | 의미 |
|------|------|
| `200` | 성공 `{ ok: true, result }` |
| `400` | 잘못된 요청 |
| `401` | 인증 실패 |
| `404` | 도구 없음 또는 정책 차단 |
| `429` | Rate limit (`Retry-After` 포함) |
| `500` | 실행 오류 |

---

## 📡 4. OpenResponses API (`POST /v1/responses`)

OpenResponses 호환 엔드포인트. 기본 비활성화.

```json
{
  "gateway": {
    "http": {
      "endpoints": {
        "responses": { "enabled": true }
      }
    }
  }
}
```

```bash
curl -s http://127.0.0.1:18789/v1/responses \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw/default",
    "input": "Hello!"
  }'
```

---

## 📊 5. Embeddings (`POST /v1/embeddings`)

```bash
curl -s http://127.0.0.1:18789/v1/embeddings \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-model: openai/text-embedding-3-small" \
  -d '{
    "model": "openclaw/default",
    "input": ["alpha", "beta"]
  }'
```

---

## 🌐 6. WebSocket 프로토콜

Gateway의 핵심 통신은 WebSocket이다. CLI, Web UI, 모바일 앱 모두 WS로 연결한다.

### 핸드쉐이크

```
1. 클라이언트 → WS 연결
2. 서버 → connect.challenge (nonce + timestamp)
3. 클라이언트 → connect 요청 (token, role, scopes)
4. 서버 → hello-ok (protocol, policy)
```

### 역할 (Roles)

| 역할 | 설명 |
|------|------|
| `operator` | 전체 관리자 접근 |
| `node` | 노드 (모바일/원격 기기) |

### 스코프 (Scopes)

| 스코프 | 설명 |
|--------|------|
| `operator.admin` | 관리자 권한 |
| `operator.approvals` | 승인 권한 |
| `operator.pairing` | 페어링 권한 |
| `operator.read` | 읽기 권한 |
| `operator.write` | 쓰기 권한 |
| `operator.talk.secrets` | 시크릿 접근 |

---

## 🏥 7. 상태 확인

### CLI 명령어

```bash
# 기본 상태
openclaw status

# 전체 진단
openclaw status --all

# 심층 진단 (채널 프로브 포함)
openclaw status --deep

# 게이트웨이 헬스
openclaw health

# JSON 출력
openclaw health --json
```

### HTTP로 상태 확인

```bash
# /v1/models로 간접 확인
curl -s http://127.0.0.1:18789/v1/models \
  -H "Authorization: Bearer <TOKEN>" | head -5

# 응답이 오면 정상
```

---

## 🔗 8. Chatub 관제탑 연동

Chatub는 위 API를 활용하여 관제탑을 구현한다:

| Chatub 기능 | OpenClaw API |
|------------|-------------|
| 에이전트 목록 | `GET /v1/models` |
| 채팅 | `POST /v1/chat/completions` |
| 스트리밍 | `stream: true` |
| 상태 확인 | `GET /v1/models` (모델 수로 판별) |
| 세션 조회 | `POST /tools/invoke` (sessions_list) |
| 세션 히스토리 | `POST /tools/invoke` (sessions_history) |

### 연결 마법사 감지 로직

```
1. /v1/models → 응답 성공 = OpenAI-compatible ✅
2. /tools/invoke (sessions_list) → 성공 = Sessions 지원 ✅
3. /v1/chat/completions (stream:true) → SSE 스트림 = Streaming ✅
4. /tools/invoke (sessions_list) 결과에 도구 = Tools 지원 ✅
```

---

## 🛡️ 보안 주의사항

> **이 API는 전체 운영자 접근 권한을 가진다.**

1. **토큰을 공개하지 마라** — GitHub, 블로그, 채팅에 노출 금지
2. **loopback/tailnet에서만 사용** — 공개 인터넷에 직접 노출 금지
3. **Rate Limit 설정** — `gateway.auth.rateLimit`로 제한
4. **도구 정책 검토** — `/tools/invoke`의 기본 차단 목록 확인

---

## 📝 빠른 참조 카드

```
# 기본 연결 테스트
curl -s http://127.0.0.1:18789/v1/models -H "Authorization: Bearer <TOKEN>"

# 채팅
curl -s http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw/default","messages":[{"role":"user","content":"hi"}]}'

# 스트리밍 채팅
curl -N http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw/default","stream":true,"messages":[{"role":"user","content":"hi"}]}'

# 도구 호출
curl -s http://127.0.0.1:18789/tools/invoke \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"tool":"sessions_list","action":"json","args":{}}'

# 헬스 체크
openclaw health --json
```

---

> 📖 출처: [OpenClaw 공식 문서](https://docs.openclaw.ai) — `/gateway/openai-http-api.md`, `/gateway/tools-invoke-http-api.md`, `/gateway/protocol.md`, `/gateway/health.md`, `/gateway/authentication.md`
