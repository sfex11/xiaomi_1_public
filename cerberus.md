---
layout: page
title: CERBERUS
---
# 🛡️ CERBERUS

**Context Error Responsibility & Backtracking Engine for Unifying Surveillance**

> LLM 기반 멀티에이전트 시스템의 컨텍스트 오류를 사전 감시, 추적, 자동 정화하는 엔진.

## 왜 이 프로젝트인가?

2026년 3월, 회장님이 말씀하셨습니다.

> *"대화 이력에도 고쳐야 할 게 있는지 감시하는 건 어떨까?"*

이 한 줄이 모든 시작이었습니다. 학계에서는 이를 **"Contextual Drag"**라고 부르고 있었습니다 — 컨텍스트 내 오류가 후속 응답을 구조적으로 유사한 오류로 끌어가는 현상. 하지만 아무도 해결책을 내놓지 못했습니다.

## 핵심 기술

<div class="project-card">
  <h3>🔍 Context Watchdog</h3>
  <p>4종 감지기가 대화 이력을 사전 스캔 — 날짜/숫자 불일치, 논리 모순, 참조 무결성, 자기 모순 패턴</p>
</div>

<div class="project-card">
  <h3>📊 Turn Influence Score</h3>
  <p>의미 유사도 + 시간 가중치 + 참조 횟수로 각 턴의 영향도 수치화</p>
</div>

<div class="project-card">
  <h3>👤 Responsibility Scorer</h3>
  <p>멀티에이전트 환경에서 "어떤 에이전트가 오류의 루트 원인인지" 자동 식별</p>
</div>

<div class="project-card">
  <h3>🧹 Auto Sanitizer</h3>
  <p>Soft → Hard → Full 3단계 정화 + 비용-오류 트레이드오프로 자동 결정</p>
</div>

## 성능

| 지표 | 결과 | 목표 | 상태 |
|---|---|---|---|
| Recall (감지율) | 100.0% | ≥80% | <span class="status status-done">PASS</span> |
| Precision (정밀도) | 74.3% | ≥70% | <span class="status status-done">PASS</span> |
| FPR (오탐지율) | 24.8% | ≤20% | <span class="status status-wip">개선중</span> |
| 단위 테스트 | 125 passed | — | <span class="status status-done">PASS</span> |
| 특허 | 청구항 13항 | — | <span class="status status-done">완료</span> |

## 데모: 멀티에이전트 연쇄 오류

```
[finance]    매출 500억원              ← 잘못됨
[analysis]   500억 기준 배당 100억       ← 오류 전파
[summary]    100억 기준 주당 5000원      ← 오류 증폭
[finance]    정정합니다. 실제 300억      ← 자기 모순

⚠️ 4개 오류 감지 | CER: 0.2181
👤 책임: finance 49%, summary 8%, analysis 4%
```

루트 원인 에이전트를 정확히 식별했습니다.
