# P001-Chatub 작업 분배 v2.1

## 담당 영역

### 라이카 — PM/통합/테스트
- [x] CP1 기획 완료
- [x] DESIGN.md v2.1 관제탑 리브랜딩
- [ ] CP2 통합 테스트
- [ ] CP5 블로그 포스팅 (관제탑 소개)

### 샤오미 — 백엔드/인프라
- [x] CP1 FastAPI + HTTP 프록시
- [ ] CP2 Gateway REST API 연동
  - [ ] `agents.list` → `/api/agents` 엔드포인트
  - [ ] `sessions.list` → `/api/sessions` 엔드포인트
  - [ ] 토큰/상태 집계 API
- [ ] CP4 WebSocket 브리지 (Gateway → 프론트엔드)

### 레노버 — UI/UX/프론트엔드
- [x] CP1 index.html 모던 리팩토링
- [x] v2.1 UI 컨셉 프로토타입
- [ ] CP3 3-Panel 레이아웃 적용
  - [ ] 좌측: 에이전트 목록 + 포럼 토픽
  - [ ] 중앙: 채팅 / 대시보드 (탭 전환)
  - [ ] 우측: 관제 패널 (상태/차트/로그)
- [ ] 픽셀 오피스 뷰 (CSS 애니메이션)
- [ ] 다크모드 + 반응형

## 파일 소유권

| 파일/디렉토리 | 주 담당 | 리뷰어 |
|--------------|---------|--------|
| backend/ | 샤오미 | 라이카 |
| frontend/ (index.html) | 레노버 | 라이카 |
| DESIGN.md | 라이카 | 전원 |
| STATUS.md | 라이카 | 주인님 |
| TASKS.md | 라이카 | 전원 |

## Push 순서

1. **샤오미** (backend/) → commit & push
2. **레노버** (frontend/) → `git pull --rebase` → commit & push
3. **라이카** (STATUS/TASKS) → `git pull --rebase` → commit & push
