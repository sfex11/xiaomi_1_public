Chatub에 3가지 기능 도입 계획 문서를 작성해줘.
출력: ~/xiaomi_1_public/projects/P001-Chatub/OCTOPAL_FEATURES.md

## 확정된 사양

### CP1: @멘션 라우팅 + 체인 반응
- @없으면 기존대로 전체 브로드캐스트 유지
- @에이전트명 있으면 해당 에이전트에게만 전송
- @all로 전체 전송
- 에이전트 응답에서 다른 에이전트 @mention 시 연쇄 전송
- 오프라인 에이전트는 스킵 (대기하지 않음)
- 1.2초 디바운싱
- 프론트엔드 input에 @자동완성 팝업

### CP2: 이미지/파일 첨부
- 파일을 GitHub 레포에 업로드 (gh api)
- 최대 10MB
- 업로드 후 파일 URL을 에이전트에 텍스트로 전달
- 드래그앤드롭 + 클립보드 붙여넣기 지원
- 채팅 UI에 파일 프리뷰

### CP3: GitHub 기반 공유 위키
- 레포 내 docs/wiki/ 디렉토리에 마크다운 파일로 저장
- github.com/sfex11/xiaomi_1_public/tree/main/docs/wiki/ 에서 확인
- CRUD API 제공
- 모든 사용자가 편집 가능
- 마크다운 렌더링 + 실시간 미리보기

## 기존 구조 참고
- 백엔드: ~/xiaomi_1_public/projects/P001-Chatub/backend/
- 프론트엔드: ~/xiaomi_1_public/projects/P001-Chatub/src/index.html
- 기존 기능 유지, CP 단위 로드맵, 복잡도/담당자 명시
