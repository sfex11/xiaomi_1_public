# 📊 Chatub 관제탑 반응 속도 분석 보고서

> 작성: 레노버 😇 | 날짜: 2026-04-12

---

## 1. 현재 아키텍처의 성능 병목

### 1.1 `fetchGateways()` — 가장 큰 병목 ⚠️

**문제:** `GET /api/gateways/` 호출 시 **게이트웨이마다 순차 health check** 수행

```
게이트웨이 3개 × health check 2회 호출(/v1/models + /tools/invoke)
= 최소 6회 순차 HTTP 요청
```

**코드 위치:** `backend/routers/gateways.py` `list_gateways()`
```python
for row in rows:
    health = await _health_check_async(full)  # ← 각 게이트웨이마다 2회 HTTP
    # + token stats DB 쿼리 1회
```

**측정:** 각 health check에 약 200~500ms 소요 → 3개 게이트웨이 = **1~1.5초** 지연

### 1.2 자동 폴링(30초) 매번 전체 재조회

```
setInterval(fetchGateways, 30000)
→ fetchGateways() → renderTopBarStats() + renderSideList() + renderDetailView()
→ 전체 DOM innerHTML 재생성
```

**문제:** 
- DOM 전체 재생성 (innerHTML)은 비효율적
- 변경이 없어도 전체 리렌더

### 1.3 Files 탭 — 5회 순차 HTTP 요청

**코드 위치:** `backend/adapters/openclaw.py` `list_files()`
```python
GATEWAY_FILES = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "TOOLS.md", "USER.md"]
for fname in self.GATEWAY_FILES:  # ← 5회 순차 요청
    r = await c.post(f"{base}/tools/invoke", ...)
```

파일 5개 × 게이트웨이당 = **5회 순차 HTTP 요청** (병렬 처리 안 됨)

### 1.4 Sessions 탭 — sessions_list 툴 의존

`/tools/invoke`에 `sessions_list` 툴을 호출하지만, OpenClaw Gateway의 툴 이름이 다를 수 있어 "sessions endpoint not available" 반환

### 1.5 auto-detect 라우트 중복 정의

`gateways.py`에 `POST /auto-detect`가 **두 번 정의**됨 (L88 + L194). FastAPI는 첫 번째만 등록하므로 두 번째는 무효 코드.

### 1.6 채팅 SSE 파싱 오류

프론트엔드에서 SSE 스트림을 `JSON.parse()`로 파싱 시, `data: ` 접두어 뒤의 JSON이 여러 줄로 분할되면 파싱 실패
→ "Unexpected token 'd', \"data: {\"er\"... is not valid JSON"

---

## 2. 병목 시각화

```
[사용자가 관제탑 열기]
   │
   ├─ fetchGateways() 
   │   ├─ GET /api/gateways/ ─────────────────── ~1.5s (3개 health check 순차)
   │   │   ├─ gw1: /v1/models (300ms) + /tools/invoke (200ms)
   │   │   ├─ gw2: /v1/models (300ms) + /tools/invoke (200ms)  
   │   │   └─ gw3: /v1/models (300ms) + /tools/invoke (200ms)
   │   └─ renderSideList() + renderDetailView() ─── 50ms (DOM 재생성)
   │
   ├─ [게이트웨이 선택 → 상세 뷰]
   │   └─ renderDetailBody()
   │       ├─ sessions 탭: loadDetailSessions() ─── 500ms (추가 HTTP)
   │       ├─ files 탭: loadDetailFiles() ──────── 1~2s (5회 순차 HTTP)
   │       └─ chat 탭: ctrlLoadChatHistory() ────── 200ms (DB 쿼리)
   │
   └─ [30초마다 자동 폴링]
       └─ 전체 반복 ────────────────────────────── 1.5s마다 DOM 재생성
```

---

## 3. 대책

### 대책 A: Health Check 병렬화 (P0, 효과: 큼)

**현재:** 순차 `for` 루프 → **변경:** `asyncio.gather()` 병렬

```python
# 변경 전
for row in rows:
    health = await _health_check_async(full)

# 변경 후
import asyncio
tasks = [_health_check_async(full) for full in all_gws]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**예상 효과:** 1.5초 → **0.5초** (병렬화로 가장 느린 1개만 대기)

### 대책 B: Health Check 결과 캐싱 (P0, 효과: 큼)

```python
from functools import lru_cache
import time

_health_cache = {}  # {gw_id: (result, timestamp)}
CACHE_TTL = 25  # 초

async def _cached_health(gw):
    cached = _health_cache.get(gw["id"])
    if cached and (time.time() - cached[1]) < CACHE_TTL:
        return cached[0]
    result = await _health_check_async(gw)
    _health_cache[gw["id"]] = (result, time.time())
    return result
```

**예상 효과:** 폴링 시 health check 스킵 → **API 응답 <100ms**

### 대책 C: Files 병렬 조회 (P1, 효과: 중간)

```python
async def list_files(self, url, token):
    tasks = [self._check_file(base, token, fname) for fname in self.GATEWAY_FILES]
    return await asyncio.gather(*tasks)
```

**예상 효과:** 1~2초 → **0.3초**

### 대책 D: 프론트엔드 차분 업데이트 (P1, 효과: 중간)

전체 `innerHTML` 대신 변경된 부분만 업데이트:
- SidePanel: 카드 상태 배지만 갱신
- TopBar: stats 숫자만 갱신
- DetailView: 선택된 게이트웨이가 변경된 경우만 리렌더

### 대책 E: 채팅 SSE 파서 버퍼 개선 (P0, 버그 수정)

현재 프론트엔드 SSE 파서가 청크 경계에서 JSON이 잘리는 것을 처리하지 않음:

```javascript
// 버퍼 기반 SSE 파서로 변경
var sseBuffer = '';
// ... chunk 수신 시
sseBuffer += decoder.decode(chunk.value, { stream: true });
var lines = sseBuffer.split('\n');
sseBuffer = lines.pop(); // 마지막 불완전한 라인 보존
for (var line of lines) {
    if (!line.startsWith('data: ')) continue;
    try { JSON.parse(line.slice(6)); } catch(e) { continue; }
}
```

### 대책 F: auto-detect 중복 라우트 제거 (P2, 코드 정리)

`gateways.py` L88의 첫 번째 `auto_detect` 제거 (L194의 완전한 버전 사용)

---

## 4. 우선순위 매트릭스

| 대책 | 복잡도 | 효과 | 소요 시간 | 우선순위 |
|------|--------|------|----------|---------|
| A: Health 병렬화 | 낮음 | 1.5s→0.5s | 10분 | P0 |
| B: Health 캐싱 | 낮음 | 폴링<100ms | 15분 | P0 |
| E: SSE 버퍼 수정 | 낮음 | 버그 수정 | 10분 | P0 |
| C: Files 병렬 | 낮음 | 1~2s→0.3s | 10분 | P1 |
| D: 차분 DOM | 높음 | UX 향상 | 1시간+ | P2 |
| F: 중복 라우트 제거 | 낮음 | 코드 정리 | 5분 | P2 |

---

## 5. 장기 개선 방안 (Phase 4+)

### WebSocket Protocol v3 도입
현재 HTTP REST 방식 → WebSocket 영구 연결 + RPC로 전환
- `openclaw-monitor`의 `openclaw-gateway.ts` 참고
- 단일 연결로 health, sessions, files, chat 모두 처리
- 서버 푸시 기반 상태 업데이트 (폴링 불필요)
- **예상 효과:** 초기 연결 후 모든 응답 <50ms

### Gateway Connection Pool
- 각 게이트웨이에 WebSocket 영속 연결 유지
- `openclaw-monitor`의 `gateway-pool.ts` 참고
- 재연결 자동 처리 + exponential backoff

---

## 6. 핵심 요약

> **현재 병목의 80%는 "게이트웨이별 순차 health check"와 "파일별 순차 조회"입니다.** 
> 이 두 가지만 `asyncio.gather()`로 병렬화해도 체감 속도가 크게 향상됩니다.
> 장기적으로는 WebSocket Protocol v3 도입으로 폴링 자체를 제거하는 것이 근본 해결입니다.
