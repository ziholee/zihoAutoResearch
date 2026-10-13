# 처음 설치한 뒤 기록·중단·재개하기

CLI는 실험을 실행하거나 프로세스 생존 여부를 확인하지 않습니다. 아래 절차는 기존 에이전트가 실제 관측을 기록하는 순서입니다. 연습에는 합성 관측만 사용하며 실제 학습을 호출하지 않습니다. [CLI 입력 레시피](../skills/ziho-autoresearch/references/cli-recipes.md)와 함께 사용합니다.

## 1. 설치와 작업 경로

[uv 설치 안내](uv-installation.md)에 따라 CLI를 설치하고 `zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json`으로 스킬을 새 폴더에 추출합니다. uv 설치 버전은 `uv tool list`로 확인합니다. pip 가상환경을 사용했다면 다시 열 때 같은 환경을 활성화하고 `python -m pip show ziho-autoresearch`로 확인합니다. 새로운 대상 프로젝트 폴더는 먼저 생성하고, 도구 소스 폴더와 구분합니다.

```sh
zar --help --json
zar init --project <target-root> --json
zar status --project <target-root> --json
```

`status`가 성공해도 `ready:false`일 수 있습니다. 생성된 `.autoresearch/project.json`을 초안으로 복사하고 목표·비교 조건·환경·명령·예산·수정 허용 경로를 채웁니다. `.autoresearch/drafts/`는 init이 만들지 않으므로 사용한다면 먼저 생성합니다. 원본 JSON을 직접 덮어쓰지 않습니다.

```sh
zar project set --project <target-root> --file <project-draft.json> --json
zar check --project <target-root> --json
```

새 비교 조건은 새 comparison ID를 사용합니다. 설정 초안의 revision을 직접 올리지 않고 매 저장 후 원본을 다시 읽습니다.

## 2. 기준 결과와 다음 실험 기록

초기 baseline은 kind=baseline, parent_id/baseline_id=null로 생성합니다. 코드·설정 식별자와 immutable run_context(scope/seed/budget_ref)를 선언합니다. 관측 후 전체 실험 문서를 초안으로 복사하고 execution만 수정해 `experiment update`에 전달합니다. 실행 사실·점수·근거는 임의로 채우지 않습니다.

근거와 비교 타당성을 확인한 뒤 `experiment decide`로 keep을 기록하고, 채택하려면 별도로 `project set`의 selected_experiment_id를 설정합니다. 다음 후보는 그 기준 ID를 parent_id/baseline_id에 연결합니다. 정확한 입력 모양은 레시피의 Plan/Record/Compare 절을 사용합니다.

## 3. 상태 확인이 끊긴 경우

실행 시작이 관측됐다면 running에 started_at을 기록합니다. 이후 상태를 확인할 수 없게 되면 같은 ID의 execution을 unknown으로 기록하고, 확인 불가 사유와 당시 근거를 남깁니다. unknown은 종료나 미실행을 의미하지 않습니다. 프로그램 종료가 확인된 interrupted와 구분합니다.

- 같은 실험을 다시 시작하거나 새 ID를 만드는 것으로 unknown을 해소하지 않습니다.
- next_action에 확인할 로그·프로세스·담당자의 위치를 기록합니다.
- 상태를 확인할 수 없다면 unknown으로 남기고 해당 실행을 보류합니다.

CLI 호출 자체가 중단되어 잠금이 남은 문제는 별도입니다. 소유 프로세스 종료를 확인하기 전 잠금을 지우지 않습니다. [README의 잠금 안내](../README.md)를 따릅니다.

## 4. 새 세션에서 재개

```sh
zar context --project <target-root> --json
zar status --project <target-root> --json
zar check --project <target-root> --json
```

context의 생략 수·미완료 집계를 읽고, status의 unfinished에서 대상 ID를 확인합니다. context는 근거 파일을 검사하지 않습니다. 실제 코드/설정 상태도 별도로 확인합니다.

기존 실험의 최신 원본을 읽어 전체 업데이트 초안을 만듭니다. **기존 execution.evidence를 순서 그대로 유지하고 새 확인 근거를 뒤에 추가**해야 unknown을 해소할 수 있습니다. CLI가 요구하는 것은 새 근거 항목의 기록이며, 그 항목이 실제로 새로운 사실을 증명하는지는 에이전트가 확인합니다.

- 결과가 확인됐다면 같은 ID를 succeeded/failed/interrupted로 갱신하고 실제 관측 시각·결과를 기록합니다.
- 아직 실행 중임이 확인됐다면 새 근거와 함께 running으로 갱신합니다.
- 미실행이 확인됐고 시작 시각이 null인 경우에만 cancelled로 갱신할 수 있습니다.
- 이전 시작 시각을 바꾸거나 근거를 삭제하지 않습니다. revision 충돌 시 최신 원본을 다시 읽고 변경을 재검토합니다.

## 5. 숫자 개선과 채택을 구분

`experiment compare`가 `comparable:false`를 반환해도 명령 자체는 성공(exit 0)일 수 있습니다. proxy/full이 다르면 개선값이 null이며 해당 숫자로 채택하지 않습니다.

근거 해시가 바뀐 경우 `check`와 compare가 **exit 0과 evidence_changed 경고**를 반환할 수 있습니다. 숫자 메타데이터의 comparable=true 또는 meets_min_delta=true는 근거 확인을 대신하지 않습니다. `evidence read`는 해당 해시 불일치에서 종료 3으로 원문 반환을 거부합니다. 경고를 없애기 위해 기록된 해시를 현재 파일에 맞춰 바꾸지 않습니다.

근거가 미확인이라면 hold와 다음 확인 행동을 기록하고 유효한 기존 선택을 유지합니다. 마지막으로 check/status에서 미완료 상태·예산·선택을 확인하고 report를 만듭니다. 도구가 실제 코드 채택이나 학습 종료를 대신 수행했다고 보고하지 않습니다.

## 학습 없는 두 세션 연습

v0.1.1 이상 소스 배포본 또는 이 변경이 포함된 체크아웃에서, CLI가 설치된 Python으로 실행합니다. 각 명령은 별도 프로세스이며 prepare가 종료된 뒤 resume를 실행합니다. `<new-project>`는 기존 상위 폴더 아래의 새 경로입니다.

```sh
python examples/mock-resume.py prepare --root <new-project> --scope full
python examples/mock-resume.py resume --root <new-project>
```

proxy/full 불일치도 확인하려면 다른 새 경로로 prepare의 `--scope proxy`를 사용합니다. 예제는 실행 시간·로그·점수를 합성해 기록하고, 근거 파일 변경을 주입한 뒤 보류합니다. 마지막 복원은 예제가 보관한 정확한 원본 바이트의 복구이며 CLI의 자동 복구 기능이 아닙니다. 실제 학습·프로세스 강제 종료·실행 상태 탐지는 하지 않습니다. 기록한 명령을 수동 실행하지 마세요.
