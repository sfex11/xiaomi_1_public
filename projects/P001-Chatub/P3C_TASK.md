~/xiaomi_1_public/projects/P001-Chatub/src/index.html 세션 탭에 세션 뷰어 추가.

현재 세션 탭은 목록만 표시. 세션 클릭 시 메시지 히스토리 보여주기:
- 세션 목록에서 세션 클릭 → 해당 세션의 메시지 로드
- GET /api/gateways/{id}/sessions/{sessionKey} 백엔드 라우트 필요
- 메시지 목록 표시 (user/assistant 구분, 시간 표시)
- "뒤로" 버튼으로 목록으로 복귀

백엔드 gateways.py에 GET /{gateway_id}/sessions/{session_key} 라우트 추가.
adapter.openclaw.py에 get_session(url, token, session_key) 메서드 추가.

관제탑 영역만 수정.
