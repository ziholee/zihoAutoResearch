# 그래프 기반 연구 도구 조사와 적용 판단

조사일: 2026-10-04. 일반 그래프 신경망 모델보다 이 프로젝트와 가까운 **실험 탐색 트리·연구 에이전트·근거 기억**을 중심으로 검색했습니다. arXiv 원문과 공식 저장소를 확인했으며, 아래 목록이 분야 전체를 빠짐없이 포함한다는 뜻은 아닙니다.

## 확인한 1차 자료

| 자료 | 확인한 제출·개정일 | 가져올 메커니즘 |
|---|---|---|
| [AIDE: AI-Driven Exploration in the Space of Code](https://arxiv.org/abs/2502.13138) | 2025-02-18 | 코드 후보의 탐색 트리와 유망한 후보 재사용 |
| [The AI Scientist-v2](https://arxiv.org/abs/2504.08066) | 2025-04-10 | 실험 단계·탐색 트리·확인/분석 관계 |
| [ML-Master 2.0: Toward Ultra-Long-Horizon Agentic Science](https://arxiv.org/abs/2601.10402) | 2026-01-15; v5 2026-03-25 | 실행 세부 기록과 축적된 지식을 분리하는 문맥 관리 |
| [AIRA₂: Overcoming Bottlenecks in AI Research Agents](https://arxiv.org/abs/2603.26499) | 2026-03-27; v2 2026-04-13 | 탐색 과정의 평가 신호 일관성과 비교 조건 |
| [Recovering Wasted Compute in Autoresearch Agents](https://arxiv.org/abs/2608.10424) | 2026-08-11 | 반복 오류·튜닝 누락·탐색 비효율·분석과 후속 결정 단절의 점검 |
| [AIBuildAI-2.5](https://arxiv.org/abs/2609.25047) | 2026-09-06 | 후보의 예상 개선·근거·실행 가능성을 분리하는 선택 기록 |
| [Karpathy autoresearch 공식 저장소](https://github.com/karpathy/autoresearch) | 2026-10-04 조회 | 기존 코딩 에이전트·Git·작은 결과 파일을 이용한 bounded 반복 |

arXiv 게시·개정일과 학회 검증 상태는 다릅니다. 특히 2026년 8~9월 자료는 최근 preprint로 취급합니다. 서로 다른 모델·예산·벤치마크 조건의 점수를 직접 비교하지 않으며, 논문의 성능이 이 도구에 그대로 재현된다고 주장하지 않습니다. tabular 실패 분석을 모든 ML 분야로 일반화하지 않습니다.

## 현재 설계에 반영한 판단

아래는 자료에서 얻은 동기를 이 도구에 적용한 **설계 추론**입니다. 논문 시스템을 구현하거나 성능을 측정한 결과가 아닙니다.

- JSON과 Git을 원본으로 유지하고 기존 parent_id/baseline_id/code_ref/correction 관계를 활용합니다. 계보 조회를 위해 그래프 DB나 실행 엔진을 먼저 도입하지 않습니다.
- 동일 실행의 정정과 실제 재실행을 구분합니다. 원본·실패·취소 이력을 보존하고, 정정 후에도 과거 참조를 조용히 바꾸지 않습니다.
- 모델의 예상 효과와 실측 점수를 구분합니다. 보고서는 출처 없는 값·과거 상태를 보완하지 않고 미기록으로 표시합니다.
- CLI의 역할은 기록·검사·요약이며 LLM 호출·GPU 스케줄링·Docker 격리는 초기 범위 밖입니다.

이번 코드 수정은 설계 감사에서 발견한 취소·unknown·정정 문제를 해결한 것입니다. 아래 논문 기반 후속 기능은 이슈로 분리했습니다. #7의 비교·판정은 이후 구현했으며 실행 조건·반복 통계·정정 baseline 제한을 파일 계약에 반영했습니다. 나머지 기능은 아직 미구현입니다.

## 후속 이슈와 완료 범위

1. [#5 기존 JSON과 Git SHA로 실험 계보 그래프 조회](https://github.com/ziholee/zihoAutoResearch/issues/5): 기존 관계부터 조회하고 다중 부모 스키마는 필요가 확인되면 추가합니다. 그래프 실행기는 만들지 않습니다.
2. [#6 실패 기억과 제한된 context export](https://github.com/ziholee/zihoAutoResearch/issues/6): 환경별 적용 조건·원문 근거·정정 가능한 기억과 출력 크기 제한을 설계합니다.
3. [#7 비교·판정 및 평가 조건 검증](https://github.com/ziholee/zihoAutoResearch/issues/7): 이미 있는 Comparison을 확장 없이 먼저 활용하고 proxy/full·확인 실험·정정 baseline의 비교 조건을 검토합니다.
4. [#8 후보 선택 이유 기록](https://github.com/ziholee/zihoAutoResearch/issues/8): 가설·분석 근거·예상 비용·보류 이유를 연결하되 LLM의 기대 점수를 실측 성능으로 취급하지 않습니다.

실행 순서는 현재 수명주기 보완 → 비교·판정/근거 기록의 사용 가능한 최소 루프 → 계보 조회와 실패 기억입니다. 논문 기능 수를 늘리는 것보다 기존 프로젝트에 적용할 수 있는 한 사이클을 우선합니다. 모든 개발 검증은 모의 파일·로그·점수로 수행하며 실제 ML 실행은 사용자가 도구를 적용할 때 진행합니다.
