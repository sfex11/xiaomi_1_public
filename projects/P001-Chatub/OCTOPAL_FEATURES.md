# Octopal 기능 도입 계획 — CP16~CP18

**작성일:** 2026-04-15  
**참고:** [Octopal](https://github.com/gilhyun/Octopal) — Claude Code 기반 에이전트 워크스페이스

---

## CP16: @멘션 라우팅 + 에이전트 체인 반응

### 사양
- `@없음` → 기존대로 전체 브로드캐스트
- `@에이전트명` → 해당 에이전트만 전송
- `@all` → 전체 전송
- 에이전트 응답에 `@다른에이전트` 있으면 연쇄 전송
- 오프라인 에이전트 → 스킵 (대기하지 않음)
- 1.2초 디바운싱 (연속 메시지 버퍼링)

### 구현

**백엔드 (gateways.py)**
- `POST /api/gateway-chat` 수정: `messages` 파싱하여 `@mentions` 추출
- `gateway_id`가 `all`이면 기존 broadcast 로직
- 특정 에이전트면 해당 GW만 전송
- 에이전트 응답에서 `@` 패턴 감지 → 연쇄 전송 (최대 3단계, 루프 방지)
- 디바운싱: 동일 사용자의 연속 메시지 1.2s 버퍼 → 한 번에 전송

**프론트엔드 (index.html)**
- 채팅 input에 `@` 타이핑 시 자동완성 팝업
- 등록된 에이전트 목록 표시 (이름 + 이모지)
- 키보드 선택 (↑↓ + Enter)

### 복잡도: 중간 | 담당: 라이카(백엔드) + 래노버(프론트)

---

## CP17: 이미지/파일 첨부 → GitHub 업로드

### 사양
- 최대 10MB
- GitHub 레포에 업로드 → 파일 URL 반환
- URL을 에이전트에 텍스트로 전달 ("첨부: https://raw.githubusercontent.com/...")
- 드래그앤드롭 + 클립보드 붙여넣기
- 채팅에 파일 프리뷰 (이미지 썸네일, 파일명+크기)

### 구현

**백엔드 (routers/upload.py 신규)**
- `POST /api/upload` — 파일 수신
- `gh api`로 GitHub에 업로드:
  ```
  gh api repos/sfex11/xiaomi_1_public/contents/uploads/{date}/{filename} \
    --input base64.json
  ```
- 응답: `{"ok": true, "url": "https://raw.githubusercontent.com/...", "name": "...", "size": 12345}`
- 10MB 초과 시 413 에러
- 이미지/텍스트 파일만 허용

**프론트엔드 (index.html)**
- 채팅 input에 드롭존 추가 (dragover/drop 이벤트)
- 첨부 버튼 → file input
- 전송 시 파일을 먼저 upload API로 업로드 → URL을 메시지에 포함
- 메시지 버블에 이미지 프리뷰 또는 파일 아이콘

### 복잡도: 중간 | 담당: 라이카

---

## CP18: GitHub 기반 공유 위키

### 사양
- 레포 내 `docs/wiki/` 디렉토리에 마크다운 파일 저장
- GitHub에서 확인: `github.com/sfex11/xiaomi_1_public/tree/main/docs/wiki/`
- 모든 사용자가 편집 가능
- CRUD API + 마크다운 렌더링 + 실시간 미리뷰

### 구현

**백엔드 (routers/wiki.py 신규)**
- `GET /api/wiki` — 문서 목록 (git ls-tree로 docs/wiki/ 파일 목록)
- `GET /api/wiki/{slug}` — 문서 내용 (git show로 읽기)
- `PUT /api/wiki/{slug}` — 문서 저장 (git commit: gh api)
- `DELETE /api/wiki/{slug}` — 문서 삭제
- slug: 파일명에서 확장자 제거 (예: `chatub-architecture.md` → `chatub-architecture`)

**프론트엔드 (index.html)**
- 관제탑에 "📝 위키" 탭 추가
- 좌측 문서 목록 + 우측 편집기
- 실시간 마크다운 미리보기 (split view)
- 검색 기능

### 복잡도: 중간 | 담당: 라이카(백엔드) + 래노버(프론트)

---

## 로드맵

| 순서 | CP | 내용 | 복잡도 | 선행 조건 |
|------|----|------|--------|----------|
| 1 | CP16 | @멘션 라우팅 + 체인 | 중간 | 없음 |
| 2 | CP17 | 파일 첨부 + GitHub 업로드 | 중간 | gh CLI |
| 3 | CP18 | 공유 위키 | 중간 | gh CLI + git |

CP16→17→18 순서로 진행. CP17과 CP18은 gh CLI 의존이 있으나 Termux에 이미 설치됨.

---

*라이카 🐕 | 2026-04-15*
