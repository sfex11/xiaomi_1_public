~/xiaomi_1_public/projects/P001-Chatub/src/index.html 파일 탭에 편집 기능 추가.

현재 파일 탭은 읽기 전용으로 파일 목록만 표시. 클릭 시 편집 가능하게:
- 파일 클릭 → 내용을 textarea에 표시
- "저장" 버튼 추가 → POST /api/gateways/{id}/files/save (body: {filename, content})

백엔드 ~/xiaomi_1_public/projects/P001-Chatub/backend/routers/gateways.py에:
POST /{gateway_id}/files/save 라우트 추가
adapter.openclaw.py에 save_file(url, token, filename, content) 메서드 추가
→ POST /tools/invoke {"tool":"files_write","args":{"path":filename,"content":"..."}} 

관제탑 영역만 수정. 기존 기능 변경 금지.
