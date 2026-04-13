~/xiaomi_1_public/projects/P001-Chatub/src/index.html 관제탑 UI 고도화:

## 1. 다크모드 토글
TopBar에 다크/라이트 토글 버튼 추가.
이미 CSS 변수 시스템이 있음 (:root, [data-theme="light"]).
- TopBar 우측에 🌙/☀️ 토글 버튼
- localStorage에 저장
- data-theme 속성을 html/body에 토글

## 2. 파일 탭 편집 기능
현재 파일 탭은 읽기 전용. 편집 가능하게:
- 파일 목록에서 파일 클릭 시 내용 표시
- textarea에 내용 로드
- "저장" 버튼으로 PUT /api/gateways/{id}/files/{filename} 호출
- 백엔드에 PUT 라우트 필요 없으면 gateways.py에 추가

## 3. 세션 뷰어
세션 목록에서 세션 클릭 시 상세 메시지 표시:
- 세션 클릭 → 메시지 히스토리 로드
- WebSocket RPC sessions.get 사용
- 메시지 목록 (user/assistant 구분)

주의: 기존 기능 변경 금지. 관제탑 영역만 수정.
