# 보고서 필드와 JSON 원본 매핑

갱신: 2026-10-07 · [보고서 양식](../templates/experiment.md) · [v1 계약](cli-and-file-contract.md)

`report`는 프로젝트 전체 JSON에서 Markdown을 생성합니다. 원본 필드는 경로와 함께 표시하고, 파생 비교·기록된 경과 시간은 저장 필드와 구분합니다. 활성 기록을 먼저 표시하되 대체된 기록과 전체 정정 계보도 남깁니다. `E`는 대상 `experiments/<id>.json`, `P`는 `project.json`, `R`은 `E.review_ids`로 찾은 review, `S`는 `S.experiment_id == E.id`인 submission입니다. 배열은 원본 순서를 보존합니다. 원본 문자열은 Markdown/HTML 구문으로 실행되지 않게 이스케이프하며 표시되는 값은 보존합니다. 생성 시각을 제외한 결과는 동일한 기록·진단에서 재현됩니다. Evidence는 kind/ref/locator/sha256을 그대로 표시하며 임의의 외부 문서·로그에서 값을 자동 추출하지 않습니다. 정정 계보는 전체 같은 종류의 JSON을 조회해 계산합니다.

모든 null·생략·출처 없는 항목은 “미기록”입니다. `execution.status == unknown`은 상태명 “상태 불명”으로 표시하고 관련 미확인 값은 “미기록”으로 둡니다. 값이 없는 이유를 원본 note/evidence가 설명하면 함께 표시합니다. 예산·지표·다음 행동을 program.md에서 파싱하지 않습니다.

| 보고서 항목 | JSON 경로·출력 규칙 |
|---|---|
| 제목, 실험 ID·유형 | `E.id`, `E.kind` |
| 가설과 예상 관측 | `E.hypothesis`; 별도 예상값 추정 없음 |
| 부모·비교 기준 | `E.parent_id`, `E.baseline_id`; 해당 ID와 대체 여부 표시 |
| 비교 구간 | `E.comparison.id` |
| 변경 내용과 파일 | `E.hypothesis`에 실제 적힌 내용, `E.execution.evidence[]`의 명시적 변경 근거. 별도 구조화된 변경 목록 필드는 없음 |
| 실행 코드 식별자 | `E.code_ref`; `git:`이면 전체 SHA를 표시하되 실행 일치가 검증됐다고 단정하지 않음 |
| 실행 직전 코드 일치·Git 밖 입력 | `E.execution.evidence[]`를 확인 근거 참조로 표시. 독립적인 코드 일치 결과 필드는 없으므로 일치 판정은 미기록이며 현재 Git 상태로 과거 사실을 보완하지 않음 |
| 데이터·분할·평가 | `E.comparison.dataset_ref`, `.split_ref`, `.evaluation_ref` |
| 설정·시드 | `E.config_ref`, `E.run_context.seed`; scope/budget_ref도 선언 조건으로 표시. 미기록 시 추정하지 않으며 실제 사용량은 evidence/note의 명시된 원문만 표시 |
| 환경·장치 | `E.environment.os`, `.runtime`, `.device` |
| 명령·작업 디렉터리 | `E.command.argv`, `.cwd`; 계획 명령임을 표시하고 실제 실행 일치는 `E.execution.evidence[]`에 있을 때만 별도 표시 |
| 시작·종료·시간 | `E.execution.started_at`, `.finished_at`; 둘 다 있으면 차이를 계산해 “기록된 경과 시간”으로 표시. 자원 사용 시간은 추정하지 않음 |
| 로그·모델·예측 산출물 | `E.execution.artifacts[]`의 `role/path/sha256/code_ref/config_ref/evidence`; 로그 참조는 `E.execution.evidence[]`에도 있을 수 있음 |
| 점검: 항목·조건 | `R.items[].topic`, `.applicability` |
| 점검: 근거 | `R.code_ref`, `R.data_ref`, `R.items[].evidence[]` |
| 점검: 관측·판정 | `R.items[].observation`, `.assessment` |
| 점검: 한계·다음 검사 | `R.items[].limitation`, `.next_action` |
| 점검 대체 여부 | 다른 review의 `supersedes_id == R.id` 여부; 원래 review ID를 보존 |
| 실행 상태·exit code·이유·근거 | `E.execution.status`, `.exit_code`, `.note`, `.evidence[]` |
| 로컬 지표·방향·실측값 | `E.comparison.metric`, `.direction`, `E.execution.score`; score가 null이면 “미기록” |
| 비교 가능 여부와 이유 | `E.decision.validity`, `.reason`, `.evidence[]`; 판단이 없으면 미기록. compare의 파생 검사는 저장 판단과 구분하며 계약의 전체 조건을 적용 |
| 반복 결과·변동·미확인 사유 | `E.execution.evidence[]`, `E.decision.evidence[]`, `E.execution.note`, `E.decision.reason`에 명시된 내용. compare의 repeats는 명시적 confirmation 부모 연결과 조건 일치에 한해 산출하며 그 밖의 숫자·횟수 추정 금지 |
| 유지·되돌리기·보류·근거·이력 | `E.decision.status`, `.reason`, `.evidence[]`, `E.decision_history[].decided_at/decision`; 미기록 판단을 보완하지 않음 |
| 현재 기록상 선택·코드·산출물 | `P.selected_experiment_id`와 그 ID의 `code_ref`, `execution.artifacts[]`; 실행 당시 선택이나 실제 폴더 상태라는 뜻이 아님 |
| 실제 폴더 상태·보류 후보 보존 위치 | `E.execution.evidence[]`, `E.decision.evidence[]`의 명시적 관측·위치와 관측 당시 시점. 최신 상태가 확인되지 않으면 현재 상태는 미기록 |
| 다음 행동 | 현재 프로젝트: `P.next_action`; 실험 판단 당시: `E.decision.next_action`으로 따로 표시 |
| 실험 정정 계보·대체 여부 | `E.correction.supersedes_id/reason/evidence`; 다른 실험의 `correction.supersedes_id == E.id`이면 대체됨. correction 생략/null은 정정 아님 |
| 제출 파일·해시 | `S.artifact.path`, `.sha256` |
| 제출 연결 실험·코드·설정 | `S.experiment_id`와 그 원래 실험의 `code_ref/config_ref`; 정정 끝점으로 자동 교체하지 않음 |
| 제출 ID·시각 | `S.id`, `S.external_id`, `S.submitted_at` |
| 제출 점수 종류·지표·방향·값·확인·출처 | `S.competition`, `.leaderboard`, `.metric`, `.direction`, `.score`, `.observed_at`, `.evidence[]` |
| 로컬과 제출 차이 관측·가설 | `S.evidence[]`, `E.decision.evidence[]`에 명시된 관측·해석만 출처와 함께 표시. 별도 가설 필드는 없고 인과관계를 자동 생성하지 않음 |
| 제출 정정 계보·연결 실험 대체 여부 | `S.supersedes_id`, 다른 submission의 `supersedes_id == S.id`, 연결된 원래 실험을 대체하는 correction 존재 여부 |

## 근거와 과거 상태

Evidence의 `kind/ref/locator/sha256`을 함께 표시합니다. 선택적 근거가 문서·로그의 내용을 연결하면 그 참조 위치를 표시합니다. 전용 값 필드가 없으면 참조와 JSON의 note/reason 원문만 보여주고 구조화된 값은 미기록으로 둡니다. 로그를 읽어 의미를 추론하는 것은 보고서 생성기의 역할이 아닙니다. 이를 위해 새 필수 JSON 필드를 추가하지 않습니다. 사용자 전달·해시 누락·파일 부재는 검증 한계로 표시합니다.

보고서 생성 시각은 실행 관측 시각이 아닙니다. 지금 확인한 Git 상태, 선택 ID, 프로세스 상태로 과거 실행 직전 상태·시드·보류 위치를 채우지 않습니다. 과거 provenance가 없으면 미기록을 유지합니다. 보고서는 기존 ID 참조와 전체 정정 계보를 보존하며 활성 끝점·대체된 기록을 구분합니다.
