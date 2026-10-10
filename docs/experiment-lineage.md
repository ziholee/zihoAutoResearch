# 실험 계보 조회

갱신: 2026-10-11 · [CLI 계약](cli-and-file-contract.md)과 [Git 연구 이력](git-research-history.md)을 따릅니다.

## 용도와 범위

`lineage`는 `.autoresearch/experiments/`의 기존 JSON에서 전체 실험 관계를 읽습니다. 별도 저장소·그래프 DB·런타임 의존성을 추가하지 않고, JSON·선택 상태·예산을 변경하지 않습니다. 비Git 프로젝트와 수동 코드 식별자도 지원합니다.

```sh
zar lineage --project /path/to/ml-project --json
zar lineage --project /path/to/ml-project --format mermaid
zar lineage --project /path/to/ml-project --format mermaid --json
```

`--format`은 json(기본) 또는 mermaid입니다. 기본 형식은 그래프 JSON이며 `--json`을 주면 공통 `{ok, data, diagnostics}` 응답으로 감쌉니다. Mermaid 형식은 `--json` 없이 차트 원문을 출력하고, `--json`과 함께 쓰면 data의 그래프 필드에 mermaid 문자열을 추가합니다. 성공한 non-JSON 모드의 진단은 stderr에 출력하여 stdout의 JSON/차트 원문과 분리합니다. Mermaid를 렌더링하는 프로그램은 별도로 필요합니다.

조회는 기록의 형식·참조 등 메타데이터를 검사합니다. 근거 파일 내용·해시를 읽거나 URL에 접속하거나 Git 명령을 실행하지 않습니다. 근거 검증은 `check` 또는 `evidence read`로 수행합니다. 그래프 전체를 반환하므로 페이지·출력 바이트 제한이 없습니다. 에이전트의 제한된 재개 입력에는 `context`를 사용합니다.

## 관계의 의미

모든 간선 방향은 **참조된 원본(source) → 참조한 기록(target)** 입니다.

| type | 원본 필드 | 의미 |
|---|---|---|
| parent | target의 parent_id | 계획이 어느 실험에서 파생됐는지 |
| baseline | target의 baseline_id | 어느 실험을 비교 기준으로 지정했는지 |
| correction | target의 correction 원본 ID | 같은 실행의 관측을 어느 기록에서 정정했는지 |

하나의 쌍에 parent와 baseline이 함께 있으면 두 관계를 유지합니다. 부모와 baseline이 같아야 한다고 가정하지 않습니다. 정정으로 대체된 원본도 삭제하지 않고, 기존 참조를 최신 정정본으로 바꾸지 않습니다. source_superseded는 그 간선의 원래 source가 정정으로 대체됐는지 표시하며, 자동 비교 가능성이나 유효성을 판정하는 값은 아닙니다.

code_ref는 원본 문자열을 그대로 제공합니다. Git SHA일 수 있으나 커밋의 존재·부모 관계·실제 실행 일치를 검증하지 않습니다. 두 실험이 같은 code_ref를 가져도 같은 실행으로 합치지 않습니다. 같은 실행의 정정은 correction 연결로만 구분합니다. 점검·제출·실패 기억·후보는 이 그래프의 노드가 아닙니다.

## JSON 출력

| 필드 | 의미 |
|---|---|
| view | experiment_lineage |
| project_id | 조회한 프로젝트 ID |
| selected_experiment_id | 현재 기록상 선택. 과거 선택 이력이나 작업 폴더 상태가 아님 |
| nodes | ID 순으로 정렬한 모든 실험 기록 |
| edges | source, target, type 순으로 정렬한 관계 목록 |
| counts | 원본 기록 및 정정 계보 집계 |
| git_verified / evidence_checked | 모두 false. Git 객체와 근거 파일은 검증하지 않음 |
| limitations | 근거·Git·실제 실행 검증 범위의 한계 |
| mermaid | mermaid 형식으로 요청했을 때 추가되는 차트 문자열 |

노드에는 id, revision, source(원본 경로), kind, parent_id, baseline_id, correction_of, code_ref, execution_status, decision_status, decision_validity가 있습니다. 상태가 없는 판단 값은 미기록으로 남깁니다. superseded와 corrected_by는 후속 정정을 표시하고 execution_id는 같은 실행 정정 계보의 최초 ID, active_record_id는 마지막 정정 끝점 ID입니다. selected는 현재 프로젝트의 선택 ID와 해당 기록 ID가 같은지 표시합니다.

간선에는 type, source, target, source_superseded가 있습니다. Mermaid는 같은 관계와 상태를 표시하는 파생 표현이며 원본은 JSON입니다. 출력 순서는 저장 디렉터리의 열거 순서에 의존하지 않습니다. 없는 실험 참조, 갈라진 정정, 부모·비교 기준·정정을 함께 따라가며 생기는 순환은 오류로 거부하며 부분 그래프를 성공으로 내보내지 않습니다.

## 집계 해석

| counts 필드 | 의미 |
|---|---|
| record_count | 정정 원본을 포함한 실험 JSON 기록 수 |
| execution_count | 같은 실행의 정정 계보를 한 번씩 세는 논리적 실행 ID 수 |
| correction_count | 정정으로 추가한 기록 수 |
| superseded_count | 후속 정정으로 대체된 원본 수 |
| cancelled_count | 활성 정정 끝점 중 cancelled인 수 |
| status_counts | 활성 정정 끝점의 실행 상태별 수 |

**execution_count는 실제로 실행한 횟수가 아닙니다.** planned와 실행하지 않은 cancelled도 각각 하나의 계보입니다. 실패·중단·unknown도 지우지 않으며 정정은 별도 실행으로 중복 집계하지 않습니다. 집계에서 실행 시간·자원 소비·예산 사용량·성능을 추정하지 않습니다. 그런 판단에는 원본의 실행 상태와 기존 예산·비교 계약을 확인해야 합니다.

## 검증

`tests/test_lineage_core.py`와 `tests/test_lineage.py`가 관계 구분·원본 참조·정정 끝점과 집계·출력 형식·읽기 전용 동작을 검증합니다. 설치 후 다음 합성 예제로 전체 조회를 확인할 수 있습니다.

```sh
python examples/mock-lineage.py --output /tmp/zar-mock-lineage
```

예제는 임시 로컬 Git 이력을 만들므로 Git 설치가 필요합니다. 출력은 상위 폴더가 존재하는 새 경로를 사용하며 Windows에서는 해당 환경의 임시 경로로 바꿉니다. 설치 패키지 검사에도 포함합니다. 이 검증은 실제 ML 실행, Git 조상 일치, 연구 판단의 타당성이나 비용 절감을 입증하지 않습니다.
