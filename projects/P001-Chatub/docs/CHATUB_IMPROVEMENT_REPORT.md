# Chatub 서비스 개선 연구 보고서

> 작성자: 샤오미1 | 날짜: 2026-04-14

---

## 1. 현재 서비스 점검 결과

### 1.1 API 상태 (2026-04-14 기준)

| 엔드포인트 | 상태 | 응답시간 | 비고 |
|-----------|------|---------|------|
| `GET /api/gateways/` | ✅ 200 OK | 3.4초 | 4개 Gateway 등록됨 |
| `GET /{id}/sessions` | ✅ 200 OK | 1.8쨰 | ★ 이전 "not available" → 해결됨 |
| `GET /{id}/agents` | ⚠️ 부분 | 1.8초 | 모델 ID 반환, 에이전트 이름 미매핑 |
| `GET /{id}/files` | ❌ 오류 | 1.2초 | 5개 파일 모두 `exists: false` |
| `POST /api/gateway-chat` | ✅ 정상 | — | POST only |
| `POST /api/gateways/auto-detect` | ✅ 정상 | — | POST only |
| `GET /register1/2/3` | ✅ 정상 | 0.6~0.7초 | 3개 등록 페이지 정상 |

### 1.2 Gateway 연결 상태

| Gateway | 상태 | 비고 |
|---------|------|------|
| Hermes (192.168.0.103:8642) | 🟢 online | capabilities: chat/stream/tools ✅ |
| 레노버 (192.168.0.110:18789) | 🔴 offline | 네트워크 연결 불안정 |
| 라이카 (127.0.0.1:18789) | 🟢 online | pairing_status: connected |
| 샤오미 (192.168.0.109:18789) | 🟢 online | pairing_status: connected |

### 1.3 확인된 버그

1. **files API**: 감지 방식 오류 — `/v1/models` 기반 파일 감지가 작동하지 않음
2. **agents API**: 시스템 모델 ID(`openclaw`, `openclaw/default`, `openclaw/main`) 반환, 실제 에이전트 이름 미표시
3. **capabilities**: auto-detect 전 등록된 Gateway에 빈 `{}` 반환
4. **sessions 응답 구조**: `data.content[0].text`에 JSON 중첩 → 프론트 파싱 어려움
5. **WebSocket 재연결 버그** (레노버 발견): 캐시된 닫힌 WS를 재사용하는 문제

---

## 2. 경쟁 서비스 분석

### 2.1 Open WebUI (⭐ 103k)
- **강점**: 완전한 오프라인 동작, RAG 내장, 15+ 검색 엔진, PWA, Markdown/LaTeX, 음성/영상 통화
- **주요 기능**: 
  - 🐍 Native Python Function Calling (BYOF)
  - 💾 Persistent Artifact Storage
  - 🛡️ RBAC + LDAP/SSO
  - 📱 PWA for Mobile
  - 🎨 이미지 생성 (DALL-E, ComfyUI, AUTOMATIC1111)
- **Chatub 도입 포인트**: 
  - **PWA 지원** → 모바일에서 네이티브 앱 같은 경험
  - **RAG 도입** → 문서 기반 채팅 (SOUL.md, 매뉴얼 등)
  - **Function Calling UI** → 에이전트 툴 호출 시각화

### 2.2 LobeHub / Lobe Chat (⭐ 56k)
- **강점**: 에이전트 팀워크, 10,000+ MCP 플러그인, 개인 메모리 시스템
- **주요 기능**:
  - 👥 Agent Groups (병렬 협업)
  - 📅 Schedule (예약 실행)
  - 📁 Project/Workspace 구조
  - 🧠 Personal Memory (에이전트가 사용자 학습)
  - 🔀 Branching Conversations
  - 🎨 Custom Themes
- **Chatub 도입 포인트**:
  - **에이전트 브랜칭 채팅** → 한 채팅에서 여러 에이전트 병렬 질문
  - **예약 실행** → 특정 시간에 에이전트에게 작업 지시
  - **Personal Memory** → 에이전트가 사용자 선호 학습

### 2.3 Claude Code (Anthropic)
- **강점**: 터미널 기반 코딩 에이전트, 코드베이스 이해, git 워크플로우
- **주요 기능**: 자연어 명령, 플러그인 시스템, GitHub @claude 통합
- **Chatub 도입 포인트**:
  - **터미널 인터페이스** → CLI에서 Chatub 채팅 가능
  - **코드베이스 연동** → 파일 컨텍스트 포함 채팅

### 2.4 OpenClaw Control UI (공식)
- **강점**: WebSocket Protocol v3, Ed25519 인증, 세션/노드 관리
- **주요 기능**: 브라우저 대시보드, 채팅, 설정, 모바일 노드 페어링
- **Chatub 관계**: Chatub은 Control UI의 독립 대안 + 다중 Gateway 관제탑

---

## 3. Chatub 도입 제안 (우선순위순)

### 🔴 P0: 즉시 수정 필요

| # | 제안 | 참고 | 복잡도 | 효과 |
|---|------|------|--------|------|
| 1 | **files API 수정** | `/v1/models` → `/tools/invoke agents.files.list` 변경 | 낮음 | 파일 편집기 활성화 |
| 2 | **WebSocket 재연결 버그** | 닫힌 WS 재사용 문제 수정 | 낮음 | 채팅 안정화 |
| 3 | **health timeout 추가** | `asyncio.wait_for(check, timeout=3)` | 낮음 | 오프라인 GW로 인한 지연 방지 |
| 4 | **agents API 매핑** | 모델 ID → 에이전트 이름/이모지 변환 | 중간 | UX 개선 |

### 🟡 P1: 단기 개선 (1~2주)

| # | 제안 | 참고 서비스 | 복잡도 | 효과 |
|---|------|-----------|--------|------|
| 5 | **PWA 지원** | Open WebUI | 중간 | 모바일 홈화면 추가 가능 |
| 6 | **Markdown 렌더링** | Open WebUI, 기존 `renderMarkdown()` | 낮음 | 코드블록/리스트 표시 |
| 7 | **동적 폴링 간격** | LobeHub | 낮음 | 화면 보는 중=15초, 백그라운드=60초 |
| 8 | **에이전트 병렬 채팅** | LobeHub Agent Groups | 높음 | 한 질문→다중 에이전트 동시 응답 |
| 9 | **capabilities 마이그레이션** | — | 낮음 | 기존 GW에 re-probe 실행 |

### 🟢 P2: 중기 도입 (1~2달)

| # | 제안 | 참고 서비스 | 복잡도 | 효과 |
|---|------|-----------|--------|------|
| 10 | **RAG 도입** | Open WebUI | 높음 | 문서 기반 채팅 |
| 11 | **에이전트 메모리 시스템** | LobeHub Personal Memory | 높음 | 에이전트가 사용자 학습 |
| 12 | **예약 실행** | LobeHub Schedule | 중간 | 특정 시간 작업 지시 |
| 13 | **브랜칭 채팅** | LobeHub | 중간 | 응답 분기 비교 |
| 14 | **CLI 인터페이스** | Claude Code | 중간 | 터미널에서 채팅 |
| 15 | **툴 호출 시각화** | Open WebUI Function Calling | 중간 | 에이전트 행동 추적 |

### 🔵 P3: 장기 연구

| # | 제안 | 참고 서비스 | 복잡도 | 효과 |
|---|------|-----------|--------|------|
| 16 | **MCP 플러그인 시스템** | LobeHub 10,000+ MCP | 매우 높음 | 외부 도구 통합 |
| 17 | **Function Calling UI** | Open WebUI BYOF | 높음 | 커스텀 파이썬 함수 연동 |
| 18 | **이미지 생성 통합** | Open WebUI (DALL-E, ComfyUI) | 높음 | 채팅 중 이미지 생성 |
| 19 | **음성/영상 통화** | Open WebUI | 매우 높음 | 음성 대화 지원 |
| 20 | **Multi-Provider 토큰 사용량 추적** | — | 중간 | 비용 모니터링 |

---

## 4. 핵심 교훈

> **"경쟁 서비스의 강점은 Chatub의 로드맵이다."**

1. **Open WebUI**는 오프라인/자체 호스팅 AI 플랫폼의 표준 → PWA, RAG, Function Calling이 핵심 차별화
2. **LobeHub**는 에이전트 협업의 미래 → 병렬 채팅, 메모리, 예약 실행이 다음 단계
3. **Chatub의 고유 가치**는 "다중 Gateway 관제탑" — 이것을 더 강화하면서 위 기능들을 점진적으로 도입

## 5. 실행 로드맵 제안

```
Week 1:  P0 버그 수정 (files API, WS 재연결, health timeout, agents 매핑)
Week 2:  P1 기본 (PWA, Markdown, 동적 폴링, capabilities 마이그레이션)
Week 3-4: P1 고급 (에이전트 병렬 채팅)
Month 2: P2 도입 (RAG, 메모리 시스템, 예약 실행)
Month 3+: P3 연구 (MCP, 이미지, 음성)
```

---

*이 보고서는 Chatub 서비스 개선을 위한 연구 결과입니다. 토론 환영합니다! 📋*
