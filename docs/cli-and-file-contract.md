# v1 사용 흐름·CLI·파일 계약

상태: 구현 기준 v1 · 2026-10-03

이 문서는 만들 CLI의 계약입니다. `init`, `project set`, `status`, `check`, `experiment create/update`와 JSON 저장·검증 기반을 구현했습니다. 나머지 명령은 후속 구현 범위입니다. 이번 제품 개발에서는 실제 ML 학습·대회 제출을 하지 않으며, 샘플 파일과 모의 결과로 도구를 검증합니다. 완성 후 실제 프로젝트 적용은 사용자가 수행합니다.

## 1. 역할과 사용자 경험

제품은 LLM용 스킬과 로컬 CLI `zar`로 구성합니다. 사용자는 기존 코딩 에이전트에 프로젝트 점검·실험 작업을 요청합니다. 스킬은 코드를 이해하고 연구 지침·점검 근거·가설을 작성하며 CLI로 기록합니다. CLI는 LLM을 호출하거나 ML 코드를 실행하지 않습니다.

| 단계 | 사용자/스킬의 행동 | CLI의 역할 |
|---|---|---|
| 초기화 | 대상 폴더에서 시작 | 폴더·빈 설정·지침 템플릿 생성 |
| 이해 | 코드·데이터·대회 문서를 읽어 목표와 명령 파악 | 구조화된 프로젝트 설정 저장·누락 표시 |
| 점검 | 코드·실행 근거를 보고 판정 | 근거가 연결된 점검 기록 저장 |
| 실험 준비 | 가설·변경·비교 기준·코드 상태 기록 | planned 실험 생성 |
| 실행 결과 기록 | 사용 시 기존 도구로 실행하고 결과 확인 | 실행 상태·점수·로그 참조 갱신 |
| 비교·판단 | LLM/사용자가 근거를 보고 판단 | 비교 가능성·수치 차이 계산, 판단 저장 |
| 제출 결과 | 사용자가 받은 점수를 입력하거나 스킬이 정리 | 제출 파일과 실험에 점수 연결. 제출 자체는 하지 않음 |
| 보고·재개 | 현재 상황과 다음 작업 파악 | 기록 요약·누락·현재 선택·미완료 상태 출력 |

개발 검증에서는 실행 단계를 가짜 로그와 결과 입력으로 대체합니다. 스킬이 실제 사용 중 실행을 수행하는 범위는 사용자의 지시·도구 권한을 따릅니다. 초기화나 기록 명령이 학습을 시작하지 않습니다.

## 2. 파일 배치와 원본

```text
<target-project>/
  .autoresearch/
    project.json
    program.md
    reviews/<review-id>.json
    experiments/<experiment-id>.json
    submissions/<submission-id>.json
    reports/                 # 요청 시 생성하는 파생 Markdown
```

- JSON은 설정·점수·상태·근거 참조의 원본입니다. Markdown을 읽어 JSON을 자동 수정하지 않습니다.
- `program.md`는 프로젝트 해석·연구 절차·불확실성·다음 행동을 적는 편집 가능한 지침입니다. 지표·예산·선택 ID·명령은 `project.json`을 참조하며 값의 별도 사본을 유지하지 않습니다.
- `reports/`는 언제든 JSON에서 재생성합니다. 보고서 수정은 원본 상태에 반영되지 않습니다.
- 코드·데이터·모델·로그는 기존 위치에 두고 경로·내용 식별자로 연결합니다. CLI가 대용량 파일을 복사하거나 모델을 로드하지 않습니다.
- 기존 루트 `program.md`, `AGENTS.md`, 사용자 코드와 설정은 자동 수정하지 않습니다. 스킬은 기존 지침도 읽고 충돌을 드러냅니다.

## 3. 명령

모든 명령은 `--project <root>`를 받습니다. 생략하면 현재 디렉터리를 사용하며 상위 폴더를 임의 탐색하지 않습니다. `init` 외 명령은 `.autoresearch/project.json`이 없으면 오류입니다.

| 명령 | 정확한 동작 |
|---|---|
| `zar init` | `.autoresearch`와 revision 1의 미설정 project.json, program.md 생성. 프로젝트 ID는 `project-<UUID>`로 생성. 재호출 시 기존 파일 보존·변경 없음; 부분 초기화는 진단하고 중단 |
| `zar project set --file <json>` | 현재 project.json의 수정본을 검증해 교체. 입력 revision이 현재와 같아야 함 |
| `zar status` | 준비 상태, 누락, 선택 실험, 마지막 실험, planned/running/unknown, 다음 행동 표시 |
| `zar check` | 모든 JSON의 형식·참조·상태·근거 가용성 검사. ML 타당성을 자동 판정하는 명령이 아님 |
| `zar review add --file <json>` | 새 점검 기록 생성. 같은 ID의 덮어쓰기 금지 |
| `zar experiment create --file <json>` | planned 상태의 새 실험 생성. 동일 ID는 오류 |
| `zar experiment update <id> --file <json>` | 현재 레코드의 수정본으로 실행 상태/관측 갱신. revision 일치 필수; 판단은 변경하지 않음 |
| `zar experiment compare <base-id> <candidate-id>` | 로컬 비교 조건을 검사하고 차이 표시. 코드 변경·판단 저장 없음 |
| `zar experiment decide <id> --file <json>` | revision·판단·근거·후속 행동을 담은 입력으로 판단 저장. keep/discard가 실제 파일을 변경하지 않음 |
| `zar submission add --file <json>` | 이미 확인된 제출 결과 기록. 외부 서비스 호출·제출 없음 |
| `zar report --output <path>` | `.autoresearch/reports/` 기준 상대 경로에 Markdown 생성. 기존 파일이 있으면 오류; `--overwrite`는 아래 소유 표식이 있는 보고서만 교체 |

project set으로 `selected_experiment_id`를 바꿀 수 있습니다. 해당 실험이 유효하고 keep 판단이며 현재 비교 조건에 속하는지 검사합니다. 이것은 기록상 선택이며 작업 폴더의 코드를 바꾸지 않습니다. decide와 선택 갱신은 별도 한 파일 변경이므로 중간 상태에도 “keep 후보이나 아직 선택되지 않음”을 표시할 수 있습니다.

report의 `--output`은 `summary.md`처럼 reports 폴더 안의 `.md` 상대 경로만 받습니다. 절대 경로·`..`·심볼릭 링크 등으로 reports 밖에 쓰는 경로는 거부하며 reports 폴더 자체와 상위 저장 경로도 링크로 다른 위치에 연결돼 있으면 거부합니다. 출력의 첫 줄은 `<!-- zar-report:v1 project_id=<현재 프로젝트 ID> -->`입니다. `--overwrite`는 동일 프로젝트의 이 표식이 있는 일반 파일에만 허용합니다. 표식 없는 사용자 문서와 JSON 원본은 덮어쓰지 않습니다. 경로·표식 조건 위반은 종료 코드 3이며 파일을 변경하지 않습니다.

기본 출력은 사람이 읽는 텍스트입니다. `--json`을 주면 성공·실패 모두 stdout에 `{ok, data, diagnostics}` 객체 하나를 출력합니다. diagnostics 항목은 `{severity, code, path, message}`입니다. JSON 모드에 설명 문장·색상·로그를 섞지 않습니다.

종료 코드: `0` 성공(경고 가능), `2` 인자·JSON 형식 오류, `3` ID·revision·상태·비교 조건 충돌, `4` 파일 접근·저장·잠금 오류. 미설정 프로젝트의 `status`는 0과 누락 목록을 반환하고, `check`는 실행 준비에 필요한 값이 없으면 3을 반환합니다.

## 4. 공통 파일 규칙

- UTF-8 JSON, 객체 하나, `schema_version: 1`. 알 수 없는 필드·중복 키·NaN·Infinity는 거부합니다. 각 필드 표의 필드는 모두 존재하며 미정값은 허용한 곳에서만 null입니다.
- 모든 레코드는 `id`(소문자 영문/숫자/하이픈, 1~64자), `revision`(1 이상 정수), `created_at`, `updated_at`(UTC RFC 3339)을 가집니다. 프로젝트 ID는 init이 생성하고, review/experiment/submission ID는 작성자가 지정합니다. UUID는 init의 생성 방식이며 공통 ID 검증의 필수 형식이 아닙니다. 따라서 예제의 `project-demo`도 유효합니다. CLI는 공통 형식·중복·경로 이탈을 검사합니다.
- 생성 입력에는 본문과 id를 제공합니다. CLI가 만드는 메타데이터는 schema_version·revision·created_at·updated_at 네 필드입니다. 실행 시각·제출 시각은 관측한 작성자가 제공하며 CLI가 추정하지 않습니다. project set/experiment update는 현재 파일 전체의 수정본을 받습니다. 수정 시 CLI가 revision을 1 증가시키고 updated_at을 갱신합니다.
- ID와 created_at, 실험의 계획 필드는 불변입니다. updated_at은 CLI가 갱신하며 실행 시각은 상태 전이에 따라 설정합니다. 이미 설정한 실행 시각은 수정하지 않습니다. 새 실험에는 새 ID를 씁니다. review/submission은 생성 후 불변이며 정정은 새 ID와 `supersedes_id`로 연결합니다. 대체된 기록도 보존합니다.
- 경로는 대상 프로젝트 기준 `/` 구분 상대 경로를 기본으로 합니다. 기존 외부 데이터 경로는 절대 경로도 기록할 수 있으나 이동 시 가용성 재검사 대상입니다. 기록 경로에 `..`나 저장 폴더 밖 쓰기는 허용하지 않습니다.
- 근거 객체 `Evidence`는 `{kind, ref, locator, sha256}`입니다. kind는 `file|url|user_report|fixture`, locator와 sha256은 null 가능. file/fixture는 경로, url은 URL, user_report는 전달한 사람/메시지 등 추적 가능한 출처입니다.
- 해시 미기록·파일 부재·사용자 전달은 검증 수준을 낮춰 표시합니다. `check`는 URL에 접속하지 않습니다. 파일을 직접 확인하지 않은 정보를 검증됨으로 올리지 않습니다.
- created_at ≤ updated_at, 실행 started_at ≤ finished_at, 제출 submitted_at ≤ observed_at을 검사합니다. 입력 시각은 시스템 현재 시각을 추정해 보정하지 않습니다.

review/submission의 supersedes_id는 같은 종류의 존재하는 활성 기록만 참조할 수 있습니다. 하나의 기록을 두 갈래로 정정하거나 이미 대체된 기록을 다시 정정할 수 없습니다. 활성 기록은 자신을 대체하는 후속 기록이 없는 최신 끝점입니다. report는 끝점을 기본 표시하고 전체 계보도 조회 가능하게 출력합니다. review 정정은 같은 code_ref·data_ref의 기록에 한정하고, 코드/데이터가 달라지면 별도 점검으로 생성합니다. submission 정정은 competition·external_id·leaderboard가 같아야 합니다. 기존 실험이 참조한 review ID는 자동 교체하지 않고 대체됨을 표시합니다.

## 5. project.json

| 필드 | 자료형과 의미 |
|---|---|
| `name`, `objective` | string 또는 null. init 직후 미정 가능 |
| `comparison` | null 또는 아래 Comparison 객체 |
| `environment` | `{os, runtime, device}`. 각 값 string 또는 null; OS는 windows/linux/macos/other |
| `commands` | Command 배열. 미설정 시 [] |
| `budget` | `{max_experiments, max_run_seconds}`. 각 값 양의 정수 또는 null |
| `editable_paths` | string 배열. 자동 추정해 허용 범위를 넓히지 않음 |
| `selected_experiment_id` | string 또는 null. 같은 프로젝트의 유효한 keep 실험 |
| `next_action` | string 또는 null. 재개할 작업 요약 |

Comparison은 `{id, dataset_ref, split_ref, metric, direction, evaluation_ref, min_delta}`입니다. 모든 값은 비어 있지 않은 string이며 direction은 `minimize|maximize`, min_delta만 0 이상 number입니다. dataset_ref·split_ref·evaluation_ref는 해당 버전/내용을 구분할 수 있는 식별자입니다. 비교 ID만 같고 실제 필드가 다르면 충돌입니다.

Command는 `{name, argv, cwd}`입니다. name은 `train|validate|predict|other`, argv는 비어 있지 않은 string 배열, cwd는 string입니다. CLI는 이 명령을 실행하거나 셸로 해석하지 않습니다.

실험 생성에 필요한 설정은 objective, comparison, runtime, 적어도 하나의 명령, 두 budget 값, editable_paths입니다. 누락 중에도 init·status·review 기록은 가능합니다. command나 보호 범위를 포함한 승인된 작업 범위는 스킬이 사용자 지시와 함께 확인합니다.

max_experiments는 이 프로젝트 기록 안의 생성된 실험 수 한도이며 baseline·실패·확인 실행도 포함합니다. create 시 한도 도달을 검사합니다. max_run_seconds는 스킬이 외부 실행에 적용할 요청 한도이고 CLI가 프로세스를 감시·강제 종료한다고 보장하지 않습니다. 한도 변경은 project set에 명시적으로 기록하며 스킬이 임의로 늘리지 않습니다.

comparison을 바꾸면 선택 ID는 null 또는 새 비교 구간에 속하는 keep ID여야 합니다. 기존 실험의 comparison 사본은 바뀌지 않습니다. environment만 바꾼 경우도 새 실험에는 현재 환경 사본을 저장하고, 다른 환경끼리의 자동 수치 비교는 보류합니다.

## 6. reviews/<id>.json

| 필드 | 자료형과 의미 |
|---|---|
| `supersedes_id` | string 또는 null. 정정 대상 review |
| `code_ref`, `data_ref` | string. 점검 당시 코드·데이터 식별자 |
| `items` | 1개 이상 Finding 배열 |

Finding은 `{id, topic, applicability, observation, assessment, evidence, limitation, next_action}`입니다. evidence는 Evidence 배열, 나머지는 string이며 limitation/next_action은 null 가능합니다. assessment는 `confirmed_issue|suspected|passed_in_scope|unverifiable|not_applicable`입니다.

confirmed_issue와 passed_in_scope에는 비어 있지 않은 evidence가 필요합니다. unverifiable에는 limitation, suspected에는 next_action, not_applicable에는 applicability의 이유가 필요합니다. 자동 코드/데이터 추적을 구현하지 않으므로 현재 파일 상태와 연결을 확인하지 못하면 최신성 미확인으로 출력합니다. 근거 경로에 해시가 있으면 변경 여부를 확인합니다.

## 7. experiments/<id>.json

| 필드 | 자료형과 의미 |
|---|---|
| `kind` | `baseline|validity_fix|performance|confirmation` |
| `hypothesis` | string. 기준 실행도 목적 명시 |
| `parent_id`, `baseline_id` | string 또는 null. 계획 계보와 비교 대상은 별개 |
| `comparison`, `environment` | 생성 시 project.json에서 복사. 이후 불변 |
| `code_ref`, `config_ref` | string. 실행할 코드/설정 상태 식별자 |
| `command` | Command. 실행에 사용할 명령의 사본 |
| `review_ids` | string 배열. 존재하는 점검 기록 참조 |
| `execution` | 아래 Execution 객체 |
| `decision` | null 또는 아래 Decision 객체 |
| `decision_history` | DecisionHistory 배열. 생성 시 []; CLI만 갱신 |

생성 본문에는 kind, hypothesis, parent_id, baseline_id, code_ref, config_ref, command, review_ids와 id를 제공합니다. CLI는 comparison/environment를 현재 프로젝트에서 복사하고 execution을 planned로 초기화하며 decision은 null로 둡니다. parent/baseline은 이미 존재해야 하고 자기 참조는 금지합니다. baseline은 baseline_id가 null이고, performance/confirmation은 같은 비교 구간의 baseline_id가 필수입니다. validity_fix는 새 비교 구간이면 baseline_id가 null일 수 있습니다.

Execution은 `{status, started_at, finished_at, exit_code, score, evidence, artifacts, note}`입니다. status는 `planned|running|succeeded|failed|interrupted|unknown`. 시각·exit_code·score·note는 null 가능, evidence는 Evidence 배열입니다. Artifact는 `{role, path, sha256, code_ref, config_ref, evidence}`이며 role/path/code_ref/config_ref는 string, sha256은 64자리 소문자 16진수 또는 null입니다. 단, `role=submission`은 최초 등록부터 sha256이 필수이며 null을 거부합니다. evidence는 Evidence 배열입니다. score는 유한한 number 또는 null이며 로컬 지표는 comparison을 따릅니다.

상태 전이: planned → running → succeeded/failed/interrupted/unknown. unknown → running/succeeded/failed/interrupted는 기존 execution.evidence와 구별되는 새 확인 근거가 필요합니다. 이미 완료된 결과 입력은 planned → 종료 상태를 허용하되 실제 실행 시각·출처를 요구합니다. 동일 학습을 다시 실행하면 새 실험 ID를 만듭니다. 종료 상태의 원시 결과(status·시각·exit_code·score·evidence·note)는 불변입니다.

experiment update는 모든 상태에서 기존 execution.evidence의 삭제·교체·순서 변경을 거부합니다. 미종료 상태에서는 새 항목만 뒤에 추가할 수 있습니다. 미종료 기록의 잘못된 근거는 원문을 보존하고 note에 대상과 정정 이유를 명시한 뒤 새 근거를 추가합니다. 종료 후 evidence는 계속 불변입니다. 이 검사는 기록 보존과 새 항목 유무만 보장하며 근거 내용의 진실성을 입증하지 않습니다.

종료 후에도 experiment update로 artifacts에 새 항목을 추가할 수 있습니다. 기존 항목 수정·삭제는 금지하며 파일 버전이 달라지면 새 경로로 추가합니다. 각 산출물의 code_ref/config_ref는 해당 실험과 같고 생성 근거 evidence가 필요합니다. 다른 코드에서 생성한 산출물은 그 코드의 별도 실험에 기록합니다. 이는 작성한 계보를 검사하는 것이며 CLI가 모델 생성 과정을 독립적으로 입증한다는 뜻은 아닙니다.

succeeded는 시작/종료 시각, exit_code 0, 유한 score, 결과 evidence가 필요합니다. 실패/중단/unknown에서는 score가 null이고 이유 note가 필요합니다. 종료 상태는 finished_at이 필요하고 planned/running/unknown은 finished_at이 null입니다. 시작 시각은 planned만 null일 수 있습니다. submission 이외 artifacts의 sha256은 null 가능하며 미확인으로 표시합니다. 제출 파일은 해시를 확보한 뒤 등록하므로 나중에 null을 수정하는 별도 절차는 두지 않습니다.

Decision은 `{status, validity, reason, evidence, next_action}`입니다. status는 `keep|discard|hold`, validity는 `valid|invalid|not_comparable`. reason은 비어 있지 않은 string, evidence는 Evidence 배열, next_action은 string 또는 null입니다. decide 입력은 `{revision, decision}`입니다. DecisionHistory는 `{decided_at, decision}`이며 decided_at은 CLI가 기록한 UTC RFC 3339입니다. 최초 판단부터 매 판단을 history에 추가하고, 최상위 decision은 항상 마지막 항목의 decision과 같아야 합니다. 기존 history 항목은 불변입니다.

keep은 succeeded·valid이고 근거가 있어야 합니다. hold는 다음 확인 사항을 남기고 기존 선택을 바꾸지 않습니다. invalid/not_comparable은 keep 불가입니다. 잘못된 비교 기준을 고쳐 점수가 낮아진 validity_fix는 새 유효 기준으로 keep할 수 있고, 이전 무효 점수와의 감소는 discard 사유가 아닙니다.

종료 상태가 아닌 실험은 decide할 수 없습니다. 이미 선택된 실험을 invalid/discard 등으로 재판정하려면 project set으로 선택을 해제한 뒤 변경합니다. 판단의 번복이 원래 실행 결과를 수정하지 않습니다.

## 8. 비교와 submissions/<id>.json

compare는 두 실험이 succeeded, score 존재, 모든 Comparison 필드와 environment 동일, 알려진 invalid/not_comparable 판단 없음일 때 수치 차이를 계산합니다. `raw_delta = candidate - base`, `improvement = direction이 maximize면 raw_delta, minimize면 -raw_delta`입니다.

결과는 개선 폭과 min_delta 충족 여부를 보여주며 자동 keep하지 않습니다. 반복 변동·코드 복잡도·도메인 타당성은 스킬이 근거로 판단합니다. min_delta가 0이어도 동률을 개선으로 출력하지 않습니다. 조건이 다르면 비교 불가 사유를 반환하고 점수 차이를 개선 증거로 출력하지 않습니다.

점수와 min_delta는 JSON 숫자 토큰의 십진 값을 보존해 파싱하고, 차이·경계 비교는 반올림 없는 십진 연산으로 수행합니다. 이진 부동소수점으로 변환한 뒤 다시 십진수로 복원하지 않습니다. 판정식은 `improvement > 0 AND improvement >= min_delta`입니다. 정확히 경계와 같은 개선은 충족하며, epsilon이나 표시용 반올림으로 판정하지 않습니다. 예를 들어 1.2 → 1.1의 최소화 개선은 정확히 0.1이므로 min_delta=0.1을 충족합니다. 저장·JSON 출력도 같은 십진 값을 보존하고, 사람이 읽는 표시를 줄이더라도 판정에는 원래 값을 사용합니다.

| 제출 필드 | 자료형과 의미 |
|---|---|
| `supersedes_id` | string 또는 null. 정정 대상 submission |
| `experiment_id` | 존재하는 실험 ID |
| `competition`, `external_id` | string. 대회/외부 제출 식별자 |
| `artifact` | `{path, sha256}`. 제출 파일 경로와 필수 내용 해시 |
| `leaderboard`, `metric`, `direction` | string. direction은 minimize/maximize |
| `score` | 유한 number |
| `submitted_at`, `observed_at` | UTC RFC 3339 |
| `evidence` | 비어 있지 않은 Evidence 배열. 사용자 전달도 출처를 남김 |

점수가 아직 없으면 submission 파일을 만들지 않습니다. 실험 artifacts에 제출 예정 파일만 기록합니다. 같은 competition/external_id/leaderboard의 중복 결과는 거부하고 정정은 supersedes_id를 요구합니다. 다른 leaderboard의 결과는 별도 기록입니다. 제출 추가가 실험의 로컬 점수·판단·선택을 바꾸지 않습니다.

submission add 입력은 위 제출 필드 전부와 id이며 submitted_at/observed_at도 필수입니다. 실험은 succeeded여야 하며 artifact의 path/sha256은 해당 실험의 role=submission 산출물과 정확히 일치해야 합니다. 따라서 제출 파일을 먼저 experiment update로 등록합니다. 파일이 존재하면 해시를 확인하고 불일치는 거부합니다. 외부로 이동해 파일이 없으면 등록된 해시와 제출 출처로 연결하되 현재 파일 확인 불가를 표시합니다.

## 9. 저장·충돌·복구

쓰기 명령은 프로젝트 단위 잠금을 잡고 검증 후 같은 파일시스템의 임시 파일을 원자적으로 교체합니다. 각 명령은 원본 파일 하나만 갱신합니다. 오류 시 대상 원본은 그대로 둡니다. 잠금을 얻지 못하면 자동 삭제하지 않고 충돌을 보고합니다.

저장 파일을 직접 수정한 경우 다음 check에서 형식·참조를 검사합니다. CLI 밖의 동시 편집까지 보장하지 않습니다. project set과 experiment update는 revision 일치로 오래된 수정본을 거부합니다. 삭제·자동 마이그레이션·자동 Git 되돌리기는 v1에 없습니다.

init은 완성된 임시 디렉터리를 옮겨 초기화를 완료하고, 기존 폴더는 덮어쓰지 않습니다. report는 JSON 원본을 바꾸지 않습니다. 원본 기록에 문제가 있으면 보고서 생성 전에 진단합니다.

## 10. 모의 검증으로 확인할 완료 조건

- 기존 program.md·코드를 건드리지 않는 초기화와 재호출.
- 설정 누락, 중복 ID, 잘못된 JSON/버전/유한하지 않은 점수, 오래된 revision 거부.
- planned → running → 성공/실패/unknown 기록 및 잘못된 전이 거부.
- 낮을수록/높을수록 좋은 지표의 비교, 분할/환경 차이의 비교 불가 처리.
- min_delta와 같은 값·바로 아래/위 값·동률·악화·지수 표기 숫자를 십진 값 기준으로 비교.
- 근거 없는 keep 거부, hold의 선택 보존, decide가 Git·코드를 수정하지 않는 동작.
- 리뷰 근거 변경과 누락 표시, 제출 파일/실험/점수 연결과 정정 이력 보존.
- 해시 없는 submission artifact 등록 거부와 기존 해시를 가진 제출 예제의 호환성 확인.
- report 재생성과 JSON 원본 일관성, 중간 쓰기 실패 시 원본 보존.
- reports 밖 경로·링크 경로·표식 없는 파일 덮어쓰기 거부, 동일 프로젝트 보고서의 명시적 교체.
- 모든 명령을 샘플 파일·가짜 로그·가짜 점수로 검증. 실제 학습·외부 제출·LLM API 호출 불필요.

각 파일의 완성 형태는 [예제 폴더](../examples/contract-v1/README.md)에 둡니다. 예제 수치는 모의 데이터이며 실행된 ML 결과가 아닙니다. 현재 CLI 검증 코드는 이 계약의 파일 형식·참조·정적 상태 조건을 검사합니다. 실험 생성·실행 갱신의 상태 전이는 구현했으며, 비교·판정·보고서 명령은 후속 구현 대상입니다. 별도의 JSON Schema 배포 파일은 아직 없습니다.
