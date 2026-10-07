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

## 2026-10-07 — SoL-Pi 적용

[공식 저장소](https://github.com/NVlabs/SoL-Pi)와 [연구 설명](https://nvlabs.github.io/SoL-Pi/), 근거 검증 코드를 참고해 [조회 구조](context-and-evidence.md)를 구현했습니다. 원본 JSON을 재사용하는 제한된 context와 해시를 검사하는 원문 줄 조회, 명령별 공통 기록 스냅샷입니다. 별도 모델·Pi 런타임·자동 압축은 추가하지 않았습니다.

#6의 제한된 context export는 이번 구현으로 일부 충족하지만, 환경별 실패 기억의 작성·정정·재사용 정책은 남아 있습니다. 현재 실패 조회는 명시한 비교/환경 조건으로 정렬하는 기능이며 실패 원인을 학습하거나 일반화하지 않습니다. #5의 계보 전용 그래프, #8의 후보 선택 이유 확장, review/submission/report도 후속 범위입니다. 이전 절의 “나머지 기능 미구현”은 10월 4일 기준의 기록입니다.

효율성은 출력 바이트와 실제 읽기 동작으로 검증하고 기존 진단·판정 조건을 보존합니다. SoL-Pi의 비용 절감 또는 벤치마크 결과를 이 도구의 성과로 사용하지 않습니다.

## RRSI 적용: 실행 전 점검

2026-10-07 공식 [RRSI 저장소](https://github.com/google-research/rrsi), [사전 검토](https://github.com/google-research/rrsi/blob/main/rrsi/critic.py), [변경 이력](https://github.com/google-research/rrsi/blob/main/rrsi/history.py), [변경 예산](https://github.com/google-research/rrsi/blob/main/rrsi/schedule.py), [선택 규칙](https://github.com/google-research/rrsi/blob/main/rrsi/selection.py)을 확인했습니다. RRSI는 고정 모델의 에이전트 실행 구조를 개선하는 연구이며, 아래는 ML 프로젝트 연구 절차에 원리를 옮긴 설계 판단입니다.

우선순위로 기존 v1 계약의 `review add`를 구현했습니다. 스킬은 실행 전 선언한 변경·가설과 실제 diff, 평가 누수·조건 변경을 점검하고 Finding의 관측·근거·한계를 등록합니다. 실험의 기존 review_ids로 연결하므로 새 스키마나 기억 저장소는 필요하지 않습니다. 같은 코드·데이터의 활성 점검은 새 ID로 정정하고 원본과 기존 실험 참조를 유지합니다. 등록은 기록 검증이며 자동 critic, 실행 차단 정책 또는 ML 타당성 보증은 아닙니다. 근거 누락·변경 경고가 있으면 스킬이 이를 미확인으로 다룹니다.

과거 비교 가능한 실패를 읽고 재시도의 새 근거를 설명하며, 확인 단계에서 독립 변경 수를 줄이는 지침을 반영했습니다. 묶음 평가를 각 변경의 인과 효과로 간주하지 않습니다. RRSI의 변경 수 스케줄·정체 탐지·가지치기·노이즈/비용 선택식은 구현하지 않았습니다. 비용 미측정은 미확인으로 보존하며 자동 정책에 넣지 않습니다. 연구 성능이나 비용 절감은 이 도구에서 재현·측정한 결과가 아닙니다.

이전 절의 review 미구현 표기는 해당 시점의 기록입니다. 현재 남은 v1 명령은 submission add와 report이며, 실패 기억 정책·계보 전용 조회·후보 선택 확장도 후속 범위입니다.

## 제출 결과 기록 구현

후속 단계에서 기존 v1 계약의 submission add를 구현했습니다. 성공한 실험의 등록 산출물과 이미 관측된 외부 점수를 연결하고, 같은 외부 결과의 정정은 새 기록으로 남깁니다. 외부 제출·점수 조회·선택 변경은 수행하지 않습니다. 위 절의 submission 미구현 표기는 당시 상태이며, 남은 v1 명령은 report입니다.
