# 다음 실험 후보: 근거·예측·선택 이유

갱신: 2026-10-11 · [v1 계약](cli-and-file-contract.md) · [맥락·근거 조회](context-and-evidence.md)

후보는 실행 전 작성자가 관측을 어떻게 해석했고 왜 다음 실험으로 선택하거나 보류했는지를 보존하는 불변 JSON입니다. 전처리·모델·부스팅 종류의 가중치나 자동 점수는 만들지 않습니다. 기존 에이전트가 근거와 비용·불확실성을 판단하고 CLI는 기록·연결·조회만 수행합니다. selected는 다음 시도의 의도이며 성공한 실험의 keep 판정이나 프로젝트의 selected_experiment_id와 다릅니다.

## 입력과 근거

```sh
zar candidate add --project /path/to/project --file candidate-draft.json --json
zar context --project /path/to/project --candidates --json
zar evidence read --project /path/to/project --kind candidate --id candidate-1 --pointer /evidence/0 --revision 1 --json
```

candidate add는 아래 작성자 필드만 받습니다. 정확한 JSON 예시는 [CLI 레시피](../skills/ziho-autoresearch/references/cli-recipes.md#record-the-next-experiments-rationale)를 따릅니다. Evidence가 없는 탐색 후보에서는 존재하지 않는 `/evidence/0`을 조회하지 않습니다.

| 필드 | 의미 |
|---|---|
| id | 새 후보 ID |
| supersedes_id | 정정·상태 변경 대상 후보 ID 또는 새 계보이면 null |
| status | proposed, selected, deferred, retired |
| hypothesis | 비어 있지 않은 시험할 가설 |
| parent_id | 출발점인 원본 실험 ID 또는 null |
| analysis | 관측의 해석과 후보가 나온 이유 |
| evidence | Evidence 배열. 비어 있으면 exploratory_reason 필수 |
| exploratory_reason | 근거 없이 탐색할 이유 또는 null |
| expected_effect | 예상되는 관측·효과를 설명하는 문자열. 측정 결과가 아님 |
| expected_cost | `{run_seconds, note}`. 시간은 0 이상 유한 number 또는 null, note는 비어 있지 않은 예상 근거·한계 |
| uncertainty | 예상과 다른 결과를 낳을 수 있는 불확실성 |
| decision_reason | 선택·보류·폐기한 이유 |
| reconsideration | `{trigger, reason}`. trigger는 initial/failure/stagnation/other, reason은 비어 있지 않은 재고 이유 |
| memory_ids | 참고한 원본 실패 기억 ID 배열. 중복 금지 |

id·참조·열거값 이외 설명 문자열은 비어 있을 수 없습니다. CLI는 schema_version/revision=1, 같은 created_at/updated_at과 등록 당시 프로젝트의 environment/comparison을 복사한 conditions를 생성합니다. 설정이 미완료일 때도 후보를 적을 수 있으며 미기록 조건을 추정하지 않습니다. 동일한 비교 ID는 후보의 conditions.comparison을 포함한 프로젝트 기록 전체에서 같은 비교 조건을 뜻해야 합니다. 예측 비용은 프로젝트 예산을 대체하거나 늘리는 값이 아닙니다. 저장은 설명의 사실성·인과관계·유용성을 검증하지 않습니다.

## 실행 연결과 정정

실험 생성 본문에 선택적 candidate_id를 지정하면 대체되지 않은 selected 후보의 정확한 ID여야 합니다. 실험의 hypothesis·parent_id와 생성 시 복사하는 environment·comparison은 후보 값과 같아야 합니다. 현재 조건이 달라졌다면 후보를 재평가하고 새 버전으로 기록합니다. 같은 후보를 여러 번 시험할 수 있지만 각 신규 실험은 기존 횟수 예산을 소모하며 시간 한도도 유지합니다. candidate add 자체는 학습·제출·코드 변경을 실행하지 않습니다.

`.autoresearch/candidates/<id>.json`은 덮어쓰지 않습니다. 수정·상태 변경은 supersedes_id로 기존 계보의 끝점을 가리키는 새 ID로 기록합니다. 가설과 부모 실험은 보존하고 새 예측·근거·상태·등록 당시 조건은 새 버전에 남깁니다. 다른 가설이나 부모이면 새 계보를 만듭니다. retired는 이전 후보를 가진 폐기 기록이며 계보의 종점입니다. 분기·순환·중복 ID는 거부합니다.

이미 연결된 실험은 후보가 정정된 뒤에도 원래 selected 버전을 가리킵니다. 대체 경고를 표시하며 최신 예측으로 과거 의도를 덮지 않습니다. 실험 결과 정정도 candidate_id를 보존합니다. 부모 실험이나 실패 기억이 대체·폐기되어도 원래 ID를 자동 변경하지 않고 경고·stale_refs로 표시합니다.

## 재개와 재평가

기본 context에는 후보가 있을 때 집계와 조회 안내가 포함됩니다. --candidates는 --memories와 별도 페이지이며 limit/offset/max-bytes/snapshot 계약을 공유합니다. 대체된 원본·retired는 활성 카드에서 제외하고 집계에는 남깁니다. selected → proposed → deferred 순, 같은 상태는 created_at·ID 역순입니다. 중요도나 예상 효과의 자동 순위가 아닙니다.

카드는 현재 버전의 작성자 예측과 해당 계보의 이전 버전까지 연결된 실험 관측을 구분합니다. 관측의 candidate_id와 source로 당시 예측을 확인합니다. failed/interrupted/unknown/non_improving은 활성 연결 실험의 사실 집계입니다. non_improving은 기존 비교 계약상 비교 가능하고 min_delta에 미달한 관측만 셉니다. 정정된 실험 원본은 별도 출처로 남기며 활성 집계에 중복 포함하지 않습니다. 이 횟수만으로 같은 버그·정체·원인·독립적인 반복 검증을 주장하지 않습니다.

실패나 정체가 의심되면 에이전트는 원본 근거·실패 기억·현재 조건을 확인하고 어떤 새 관측 또는 변경이 재시도를 정당화하는지 reconsideration.reason에 적습니다. CLI는 이유의 존재만 검사하며 설명의 타당성을 대신 판단하지 않습니다. unknown 실행을 미실행으로 가정해 재시도하지 않습니다. 관측별 forecast_timing은 후보 생성 시각과 기록된 실행 시작 시각을 대조한 before_execution/recorded_after_execution/unknown입니다. 이미 실행한 관측을 나중에 기록한 후보에 연결하면 경고합니다. 이 표시는 저장된 시각의 대조일 뿐 실제 사전 예측이었다는 외부 증명이 아닙니다.

모르는 실제 비용은 actual_cost_state=unknown으로 남기며 예상 시간이나 기록된 경과 시간으로 자원 사용량·절감률을 만들어내지 않습니다.

긴 설명은 160문자 미리보기이며 근거·기억·활성 관측은 각각 최대 3개와 생략 수를 제공합니다. evidence_checked/workspace_verified는 false입니다. 전체 맥락과 근거는 원본 JSON·evidence read로 확인합니다. 보고서는 폐기·대체 원본까지 전체 필드와 원래 연결을 표시합니다.

## 호환성과 검증 한계

기존 프로젝트는 candidates 폴더와 실험 candidate_id를 생략할 수 있습니다. 새 init은 폴더를 준비하며 첫 candidate add는 필요한 폴더를 생성합니다. 기존 program.md를 덮어쓰거나 마이그레이션하지 않습니다. 이 확장을 관리할 때는 candidate 명령을 지원하는 CLI를 사용합니다.

모의 회귀 검증은 입력·원본 보존·정정·폐기·실험 연결·제한 조회·보고서 계약을 확인합니다. 실제 모델 선정 성능, 비용 절감, 실패 방지율이나 자동 연구의 품질은 별도의 실제 실험 전 주장하지 않습니다.

저장소 또는 소스 배포본의 모의 흐름은 설치된 CLI로 실행합니다. 출력은 존재하지 않는 경로이고 상위 폴더는 존재해야 합니다. Windows에서는 해당 환경의 임시 경로를 사용합니다.

```sh
python examples/mock-candidates.py --output /tmp/zar-mock-candidates
```

합성 기준 관측 → selected 후보와 예측 → 개선되지 않은 합성 관측 → deferred 정정 → 근거 조회·보고서·검사를 연결합니다. 원래 예측과 실험 참조·현재 채택·예산 보존 및 학습 미실행을 검사하며 실제 ML 효과를 검증하지 않습니다.
