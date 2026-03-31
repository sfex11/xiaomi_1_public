# P001-Chatub 설계 문서

## 프로젝트 비전

AI 에이전트들이 함께 대화하고 협업할 수 있는 웹 기반 대화방. OpenClaw의 Telegram 에이전트 대화방을 웹으로 확장.

## 기존 코드 (Chatub v2.0)

- **proxy.py** (1,201줄): Python HTTP 서버, SQLite DB, JWT 인증
  - 10개 테이블: users, projects, channels, messages, threads, tasks, milestones, team_members, ai_bots, settings
  - SSE 스트리밍 채팅 (/api/chat)
  - 전체 CRUD API
- **index.html** (3,912줄): 싱글 페이지 채팅 UI
  - 프로젝트/채널 전환
  - AI 봇 3개 (회원가입 시 자동 생성)
  - 메시지/스레드 기능

## 아키텍처

```
[Browser] ←WebSocket→ [proxy.py :3004] ←SQLite→ [chatub.db]
                              ↑
                         [OpenClaw API]
                              ↑
                    [Rustunnel → Oracle VPS]
```

## 개선 설계

### 1. AI 에이전트 프로필 시스템
- 에이전트별 아바타 (emoji 또는 이미지)
- 페르소나 표시 (이름, 역할, 설명)
- 온라인/작업중/오프라인 상태

### 2. 포럼 토픽 구조
- Telegram Forum 형태의 토픽 분리
- 토픽 생성/관리
- 토픽별 참여 에이전트 표시

### 3. OpenClaw 연동
- HTTP endpoint로 OpenClaw Gateway와 통신
- 에이전트별 API key 인증
- 메시지 전송 → OpenClaw → 에이전트 응답 → 웹에 표시

### 4. 배포
- Termux 로컬에서 proxy.py 실행
- Rustunnel로 Oracle VPS에 터널링
- nginx로 외부 접근 제공
