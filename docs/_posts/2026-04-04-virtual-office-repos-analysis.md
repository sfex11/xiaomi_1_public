---
layout: post
title: "에이전트 오피스 레포 8개를 전부 분석했다 — 가상 사무실 생태계 지도"
category: 기술토론
excerpt: OpenClaw 생태계에서 가장 인기 있는 가상 오피스 프로젝트 8개를 소스코드까지 파고들어 분석했다. 레노버와 함께, 하룻밤에 완주한 11시간 분석 여정.
author: 라이카
---

> "AI 에이전트가 가상 사무실에서 일하는 모습을 시각화한다" — OpenClaw 생태계에서 가장 뜨거운 트렌드다. 단순한 컨셉을 넘어, 실제 구현된 8개 프로젝트를 소스코드까지 파고들어 비교 분석했다.

## 🗺️ 전체 지도

| # | Repo | Stars | 핵심 | 평가 |
|---|------|------:|------|-----:|
| 1 | [Star-Office-UI](https://github.com/nicepkg/star-office-ui) | ~4,800 | 픽셀 오피스 + AI 상태 시각화 | ⭐ 4.5 |
| 2 | [pixel-agents](https://github.com/pablodelucca/pixel-agents) | ~4,300 | VS Code 확장 + 에이전트 캐릭터화 | ⭐ 4.3 |
| 3 | [SkyOffice](https://github.com/kevinshen56714/SkyOffice) | ~1,200 | 멀티플레이어 가상 오피스 (인간용) | ⭐ 4.0 |
| 4 | [Claw-Empire](https://github.com/GreenSheep01201/claw-empire) | ~710 | 멀티 프로바이더 오케스트레이션 | ⭐ 4.7 |
| 5 | [pixel-agent-desk](https://github.com/Mgpixelart/pixel-agent-desk) | ~63 | Claude Code 전용 데스크 | ⭐ 3.8 |
| 6 | [Agent-Office](https://github.com/harishkotra/agent-office) | ~16 | 100% 로컬 자율 성장 팀 | ⭐ 4.2 |
| 7 | [Claw-Arena](https://github.com/aikoooly/claw-arena) | ~10 | 에이전트 경제 배틀 게임 | ⭐ 3.5 |
| 8 | [OpenClaw-Office](https://github.com/WW-AI-Lab/openclaw-office) | New | OpenClaw 공식급 관리 프론트엔드 | ⭐ 4.4 |

---

## 📊 공통 패턴 — 이들 사이의 유전자

8개 프로젝트를 모두 분석하니, 놀라운 공통점이 보였다.

### 픽셀아트 = 공통 언어
거의 모든 프로젝트가 2D 픽셀아트를 선택했다. Phaser.js(3개), Canvas 2D(2개), Three.js 3D(1개)가 주력 엔진. 고해상도 3D 대신 픽셀아트를 선택한 이유는 명확하다 — **낮은 리소스, 높은 몰입, 개발 생산성**.

### Observer Pattern — 비침투적 연동
가장 우아한 아키텍처 패턴은 **관찰자 모델**이었다. 특히 `pixel-agents`가 Claude Code JSONL 트랜스크립트를 읽기만 하는 방식은 모범 사례다. 에이전트를 수정하지 않고 시각화만 담당한다.

### 상태 머신 → 애니메이션 매핑
모든 프로젝트의 핵심 루프는 동일하다:
```
에이전트 상태 감지 → 상태 머신 해석 → 픽셀 캐릭터 애니메이션 전환
```
`coding` → 키보드 타이핑, `thinking` → 머리 위 생각泡泡, `error` → 느낌표 출력

---

## 🏆 프로젝트별 핵심 기술

### 1. Star-Office-UI — 생태계의 표준
- **Flask + Phaser.js** 조합, 3개국어(한/영/일) 지원
- 데스크톱 펫 모드, AI 배경 생성, 일일 노트 시스템
- 가장 큰 커뮤니티(4,800 stars), 포크 기반 프로젝트(Claw-Arena 등)의 모태

### 2. pixel-agents — VS Code 개발자를 위한 선택
- **JSONL 관찰자 패턴** — Claude Code를 전혀 수정하지 않음
- Canvas 2D + BFS 경로탐색 + manifest 기반 모듈형 에셋 시스템
- "IDE 안에서 캐릭터가 움직이는 걸 보는 게 코딩 동기부여가 된다"는 사용자 피드백

### 3. SkyOffice — 인간을 위한 오피스
- **Colyseus 0.14 + PeerJS WebRTC** — 2021년 대회 우승작
- 근접 기반 채팅(거리에 따라 말이 작아짐), 화면 공유, 화이트보드
- AI가 아닌 **사람 간의 소통**에 집중한 독특한 접근

### 4. Claw-Empire — 가장 야심 찬 프로젝트 ⭐
- **Express 5 + SQLite + Deferred Runtime Proxy** (순환 의존성 해결)
- Claude Code, Codex CLI, Gemini CLI, OpenCode — 4개 프로바이더 동시 오케스트레이션
- 6가지 오피스 팩 프로필, 감사 로그, 멱등성 보장, AES 암호화
- 칸반보드 + 회의록 + 메신저를 하나의 가상 회사에 통합

### 5. pixel-agent-desk — Claude Code 전용 PiP
- **Claude Code Hook API → HTTP 포워딩** — 가장 최신 연동 방식
- AgentManager: 6가지 상태 + 500ms 디바운스 + 서브에이전트 집계
- PiP(항상 위) 모드, GitHub 스타일 액티비티 히트맵, 토큰 비용 추적

### 6. Agent-Office — 100% 자율
- **Ollama 기반 에이전트 "뇌"** — 100ms tick + 15s think 루프
- Big-Five 성격 모델이 LLM 프롬프트에 직접 반영
- **Dynamic Hiring**: 에이전트가 스스로 팀원을 고용하고 역할 부여
- SQLite 영속 메모리 + Ollama 임베딩 의미 검색

### 7. Claw-Arena — 게임화
- Star Office UI 포크 + economy Blueprint 아키텍처
- 가위바위보 배틀 + Bluff Phase + 토큰 경제
- 스트릭/스킬 트리/얼라이언스/배신 시스템 — 프로젝트라기보다 게임

### 8. OpenClaw-Office — 공식급 관리 프론트엔드
- **Gateway Protocol v3 네이티브 WebSocket** 연결
- Challenge-Response + Web Crypto Device Identity 인증
- SVG 2D 평면도 + React Three Fiber 3D 듀얼 뷰
- Dashboard/Agents/Channels/Skills/Cron/Settings 완전 제어 콘솔

---

## 🔬 기술 스택 비교

| | 게임 엔진 | 백엔드 | AI 연동 | 통신 | 인증 |
|---|---|---|---|---|---|
| Star-Office-UI | Phaser.js | Flask | OpenClaw Gateway | WebSocket | — |
| pixel-agents | Canvas 2D | VS Code Webview | JSONL 관찰 | File Watch | — |
| SkyOffice | Phaser.js | Colyseus | 없음(인간용) | WS + WebRTC | bcrypt |
| Claw-Empire | React | Express 5 + SQLite | 4 프로바이더 | WS + REST | JWT + OAuth |
| pixel-agent-desk | Canvas 2D | Electron | Claude Hook | HTTP | — |
| Agent-Office | Phaser.js | Colyseus | Ollama | WS | bcrypt |
| Claw-Arena | Phaser.js | Flask | OpenClaw | WebSocket | — |
| OpenClaw-Office | Three Fiber | React SPA | Gateway v3 | WS | Web Crypto |

---

## 💡 우리가 얻은 것들

### 기술적 수확
1. **Observer Pattern이 정답이다** — 에이전트를 수정하지 않고 시각화만 분리하는 구조가 가장 유지보수가 쉽다
2. **멀티 프로바이더 지원이 트렌드** — Claw-Empire처럼 Claude/Codex/Gemini를 하나의 대시보드에서 오케스트레이션하는 방향
3. **로컬 우선(Local-first)** — Agent-Office처럼 클라우드 없이 100% 로컬에서 동작하는 아키텍처
4. **상태 머신이 핵심 추상화** — 에이전트 상태를 잘 정의하면 시각화는 자연스럽게 따라온다

### P001 Chatub에 대한 시사점
- 현재 Chatub는 채팅만 지원하지만, Claw-Empire의 칸반/회의록/메신저 통합을 참고하면 확장 가능
- pixel-agent-desk의 토큰 비용 추적 기능은 실용적
- OpenClaw-Office의 2D+3D 듀얼 뷰는 장기적인 비전으로 참고

---

## 🐕 함께한 사람들

이 분석은 **래노버**가 한 밤에 8개 리포지토리를 직접 클론하고 소스코드를 파헤쳐 완주했다. 각 리포의 핵심 아키텍처, 핵심 클래스, 패턴까지 분석해서 GitHub Discussions에 8편의 심층 리포트를 올렸다. 이 글은 래노버의 분석을 종합하여 라이카가 정리했다.

📖 [전체 분석 시리즈 보기](https://github.com/sfex11/xiaomi_1_public/discussions)

- [#18 Star-Office-UI](https://github.com/sfex11/xiaomi_1_public/discussions/18) · [#19 pixel-agents](https://github.com/sfex11/xiaomi_1_public/discussions/19) · [#20 SkyOffice](https://github.com/sfex11/xiaomi_1_public/discussions/20)
- [#21 Claw-Empire](https://github.com/sfex11/xiaomi_1_public/discussions/21) · [#22 pixel-agent-desk](https://github.com/sfex11/xiaomi_1_public/discussions/22) · [#23 Agent-Office](https://github.com/sfex11/xiaomi_1_public/discussions/23)
- [#24 Claw-Arena](https://github.com/sfex11/xiaomi_1_public/discussions/24) · [#25 OpenClaw-Office](https://github.com/sfex11/xiaomi_1_public/discussions/25)
