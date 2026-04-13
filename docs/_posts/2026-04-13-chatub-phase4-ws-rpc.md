---
title: "Chatub Phase 4: WebSocket RPC 도입 + 관제탑 UI 고도화"
date: 2026-04-13
category: "Chatub"
tags: [chatub, openclaw, websocket, 관제탑, ui]
excerpt: "HTTP REST에서 WebSocket Protocol v3로 전환하며, 관제탑의 반응 속도와 기능을 대폭 개선했습니다."
---

## 개요

Phase 2+3에서 구축한 Chatub 관제탑을 더 빠르고 강력하게 만들었습니다. 성능 최적화, WebSocket RPC 도입, UI 고도화까지 한 번에 진행했습니다.

## 성능 최적화 (P0~P1)

### 문제: 28초 걸리던 Health Check

4개 Gateway를 순차적으로 조회하니 오프라인 GW 타임아웃까지 포함해 **최대 28초**가 걸렸습니다.

### 해결: 병렬화 + 캐싱

| 대책 | 방식 | 효과 |
|------|------|------|
| Health 병렬화 | `asyncio.gather()` | 28s → 3s |
| Health 캐싱 | 25s TTL 메모리 캐시 | 2회차 이후 <100ms |
| Files 병렬화 | 5개 파일 `asyncio.gather()` | 2s → 0.5s |

> 💡 **핵심**: 순차 HTTP 요청 → `asyncio.gather()` 병렬만으로도 **10배 빨라집니다**. asyncio는 Python에서 가장 쉽고 강력한 최적화 도구입니다.

## WebSocket Protocol v3 도입 (CP12~CP15)

기존 HTTP REST에서 OpenClaw Gateway의 WebSocket Protocol v3으로 전환했습니다.

### CP12: WebSocket RPC 클라이언트

`backend/adapters/openclaw_ws.py` (459줄) — Python WebSocket RPC 클라이언트:

- Bearer 토큰 인증
- 요청→응답 id 매칭, 60s 타임아웃
- 자동 재연결 (exponential backoff)
- 7개 RPC 메서드: `sessions.list`, `sessions.get`, `agents.list`, `agents.files.list/get`, `chat.send`, `health`

### CP13: 페어링 상태 4단계

| 상태 | 의미 | 표시 |
|------|------|------|
| `connected` | 정상 | 🟢 초록 |
| `pairing-required` | 토큰 없음/인증 실패 | 🟡 노랑 |
| `error` | 서버 에러 | 🔴 빨강 |
| `disconnected` | 연결 불가 | ⚪ 회색 |

### CP14: 채팅 WebSocket 스트리밍

기존 SSE 방식의 JSON 파싱 오류를 근본 해결:

```
Before: fetch POST → SSE stream → "not valid JSON" ❌
After:  WebSocket → RPC chat.send → delta events → 실시간 표시 ✅
```

### CP15: 세션/파일 WebSocket RPC

REST API는 유지하면서 WebSocket으로도 동일 기능 제공:

- `/ws/rpc` 엔드포인트로 5개 RPC 메서드 추가
- HTTP와 WS 병존 (점진적 마이그레이션 가능)

> 💡 **교훈**: HTTP REST와 WebSocket RPC는 병존 가능합니다. 폴링은 HTTP로, 실시간 기능은 WS로 분리하면 점진적 마이그레이션이 쉽습니다.

## UI 고도화 (P3)

### 다크모드 토글

TopBar에 🌙 버튼 추가. `data-theme` 속성 토글 + `localStorage` 저장.

### 파일 편집기

파일 탭에서 SOUL.md, IDENTITY.md 등을 **읽고 편집하고 저장**할 수 있습니다.

### 세션 뷰어

세션 목록에서 클릭 → 해당 세션의 메시지 히스토리를 user/assistant 구분하여 표시.

### DOM 최적화

30초마다 전체 `innerHTML` 교체 → 변경된 부분만 diff 업데이트.

## Claude Code 활용 팁

이번 작업에서 Claude Code를 효율적으로 활용한 방법:

1. **소스코드 경로만 전달** — 프롬프트에 코드를 넣지 않고 경로만 알려주면 Claude가 직접 읽음
2. **작업을 작게 분할** — P3를 A/B/C로 나눠서 SIGTERM 방지
3. **태스크 파일** — 긴 지시사항은 파일로 작성하고 경로만 전달

```
❌ 코드 전체를 프롬프트에 붙여넣기 → SIGTERM
✅ "경로/파일.js의 X기능을 Y로 수정해줘" → 2~3분 완료
```

## 기여

| 에이전트 | 역할 |
|----------|------|
| **라이카** | 백엔드 (API, 어댑터, WebSocket), P1~P3 전체 구현 |
| **래노버** | 프론트엔드 리팩토링, 성능 분석 보고서, openclaw-monitor 참고 |
| **샤오미** | E2E 테스트, API 엔드포인트 검증, 문서 정리 |

## 다음 계획

- Ed25519 디바이스 인증 (VPS 환경 필요)
- VPS 배포로 안정성 확보
- 관제탑 i18n (한국어/영어/일본어/중국어)

---

HTTP REST에서 WebSocket Protocol v3으로 전환하는 것은 순차→병렬만큼이나 간단하고, 10배 이상의 반응 속도 개선을 가져옵니다.
