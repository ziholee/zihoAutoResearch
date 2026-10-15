# API 연결 연구 세션 사용법

상태: 개발 브랜치 구현 · 미배포 · 공개 v0.3.0에는 `research` 명령이 없습니다.

이 흐름은 기존 로컬 프로젝트의 설정부터 API 모델의 제안, 사용자 승인, 실제 명령 실행과 결과 기록을 연결합니다. 기존 기록 명령은 계속 LLM 없이 사용할 수 있습니다. 이번 검증은 모의 공급자와 결정적 로컬 프로그램 기준이며 실제 클라우드 API, Windows 실행, 실제 ML 개선 효과는 미검증입니다.

## 준비

개발 소스 환경에서 `python -m zar research --help`로 지원 여부를 확인하세요. 아래 `zar`는 해당 개발 소스에서 설치한 실행 파일을 뜻합니다. 터미널에서는 아래 `research setup`으로 JSON을 직접 편집하지 않고 설정부터 첫 계획까지 진행할 수 있습니다. 자동화에서는 기존 `init`·`project set`과 `research start`를 사용합니다. 수동 JSON 설정 방법은 [처음 사용 안내](first-run-and-resume.md)를 따릅니다.

프로젝트에는 이름이 유일한 실행 명령(`argv`, 프로젝트 상대 `cwd`), 비교 조건, 실제 환경 식별자, 예산과 수정 가능한 **파일 경로**가 필요합니다. 실행 명령은 사용자가 설정합니다. 모델이 셸 명령을 생성하거나 임의 도구를 호출하지 않습니다. 지표는 명령이 새 JSON 파일에 쓰는 최상위 유한 숫자 키를 사용합니다. 예: `{"score": 0.5}`. 상대 지표 경로는 프로젝트 루트 기준이며 부모 폴더가 이미 있어야 합니다.

API 키는 환경변수에만 넣습니다. 연결 설정에는 키 값 대신 환경변수 이름을 지정합니다. 예시는 OpenAI 호환 Chat Completions 서버 주소를 사용하며 특정 모델이나 공급자의 호환성을 보장하지 않습니다.

## 질문에 답해 첫 계획 만들기

기존 학습 코드와 데이터가 있는 프로젝트 폴더를 지정하세요. 프로젝트 루트, 학습 프로그램이나 데이터 분할을 새로 만드는 기능은 아닙니다.

```sh
zar research setup --project ./my-ml-project
```

질문에 따라 다음 값을 입력합니다. 기존 프로젝트 설정은 기본값으로 표시됩니다.

- 프로젝트 이름·목표, 데이터·분할·평가 방식의 식별자, 지표·방향·최소 개선량
- 실행 환경, 실험 횟수·시간 한도, 실행 명령 이름·작업 폴더
- 명령의 인자 개수와 각 인자, 수정 허용 파일과 API로 보낼 파일
- 서버 주소·모델·키를 읽을 환경변수 이름, 새 지표 파일·키, 비교 범위·seed·예산 식별자와 세션 호출·시간 한도

예를 들어 `python train.py --output metrics/run-001.json`은 인자 4개로 입력합니다: `python`, `train.py`, `--output`, `metrics/run-001.json`. 각 질문에 인자 하나를 그대로 입력하며 셸용 따옴표를 추가하지 않습니다. 평가 식별자와 실행 명령은 사용자가 지정한 실제 조건이어야 합니다. CLI가 적절한 평가 방법이나 학습 코드를 자동으로 만들어 주지는 않습니다.

API 키 값은 질문하지 않습니다. 실제 호출 전에 지정한 환경변수를 설정하세요. 서버·모델 설정만으로 호환성이 확인되는 것은 아닙니다.

설정 요약을 확인한 뒤 **저장에 동의**하면 설정과 세션을 저장합니다. 이어서 전송 대상과 파일 범위를 확인하고 **전송에 별도로 동의**하면 분석 → 평가 검토 → 설계 → 구현 제안 → 변경 검토를 호출합니다. 두 확인 모두 기본값은 거절입니다. 정상 계획은 `awaiting_approval`에서 멈추며, 설정 명령은 변경 적용·실험 실행·승인을 수행하지 않습니다. 모델의 누락 설정·hold/invalid 판단이나 API 실패가 있으면 출력 상태를 확인하세요.

저장 전 `:cancel`, EOF 또는 Ctrl-C로 취소하면 초기화·설정 쓰기를 하지 않습니다. 저장 후 전송을 거절하거나 취소하면 저장된 설정과 세션은 유지됩니다. 세션 ID로 `research status`를 확인하고 필요할 때 `advance --send`로 이어갑니다. 질문 도중 다른 프로세스가 설정·기록을 바꾸면 덮어쓰지 않고 중단하므로 상태를 확인한 뒤 다시 시작하세요. 기존 비교 조건을 바꾸려면 새로운 비교 ID가 필요합니다.

`setup`에는 대화형 터미널 입력이 필요하므로 파이프 입력은 거부합니다. `--json` 사용 시 질문·안내는 stderr, 최종 `{ok, data, diagnostics}` 객체 하나는 stdout에 출력합니다. 에이전트의 비대화형 도구에서는 아래 명시적 명령 흐름을 사용하세요.

## 설정된 프로젝트에서 명시적으로 시작하기

`status`의 `ready` 및 `check` 결과를 확인한 프로젝트에서 사용합니다.

```sh
export MY_LLM_API_KEY='사용자가 발급한 키'
zar research start --project ./my-ml-project \
  --base-url https://your-provider.example/v1 \
  --model your-model --api-key-env MY_LLM_API_KEY \
  --goal '현재 평가 조건을 유지하며 실험 하나를 진행한다' \
  --read train.py --command train \
  --metric-file metrics/run-001.json --metric-key score \
  --scope full --seed 42 --budget-ref fixed-protocol-v1 \
  --max-calls 9 --session-seconds 1800 --json
```

`--read`는 반복 지정할 수 있습니다. 지정한 기존 UTF-8 파일만 소스 본문으로 전송하며 모델 수정도 전송한 파일과 `editable_paths`의 교집합에 한정합니다. 숨김 경로·심볼릭 링크·크기 초과 파일은 거부합니다. 새 파일 생성은 현재 세션 흐름에서 지원하지 않습니다. `.env`, 데이터셋 전체, 저장소 전체를 자동 수집하지 않습니다. 사용자가 지정한 파일 자체에 민감한 정보가 없는지 확인하세요.

연결 플래그 대신 `--profile profile.json`을 사용할 수 있습니다. 프로필 필드는 `base_url`, `model`, `api_key_env`, 선택적 `timeout_seconds`, `max_output_tokens`, `max_response_bytes`입니다. HTTPS 또는 로컬 루프백 HTTP만 허용합니다. 모델은 JSON 응답 형식과 해당 API 필드를 지원해야 합니다. 자동 공급자 대체나 자동 재시도는 없습니다.

## 제안부터 실행까지

`start`는 세션을 저장할 뿐 API나 실험을 실행하지 않습니다. 출력의 세션 ID, 전송 대상·파일·프로젝트 설정·제한된 기록 범위를 확인합니다. 아래 `SESSION_ID`, `TOKEN`은 실제 출력 값으로 바꿉니다.

```sh
zar research status SESSION_ID --project ./my-ml-project --json
zar research advance SESSION_ID --send --project ./my-ml-project --json
```

`--send`가 API 전송 동의입니다. 분석 → 평가 검토 → 설계 → 구현 제안 → 변경 검토를 각각 별도 호출합니다. 누락 설정이나 hold/invalid 판정은 차단합니다. 정상적으로 끝나면 `awaiting_approval`과 실제 diff, 명령, 승인 토큰을 반환합니다. 같은 모델의 재검토는 독립적인 코드 검증이 아닙니다.

```sh
zar research approve SESSION_ID --token TOKEN --project ./my-ml-project --json
zar research run SESSION_ID --project ./my-ml-project --json
```

`approve`는 실행하지 않습니다. 명시적인 `run`이 승인된 변경을 적용하고 명령 한 번을 실행합니다. `reject`로 실행 전 거절할 수 있습니다. 입력이 달라지면 이전 승인으로 실행하지 않습니다. 로컬 명령은 셸 없이 실행하지만 OS 샌드박스가 아니므로 승인한 프로그램 자체가 접근할 수 있는 파일·네트워크를 제한하는 기능은 아닙니다.

역할 검토는 canonical review에 `unverifiable`로 보존하고 실험에 연결합니다. LLM의 pass를 독립적인 타당성 검증으로 기록하지 않습니다. 실제 실행 로그와 지표를 보관하고 canonical experiment에 연결합니다. 종료 코드가 0이어도 지표가 없거나 유효한 숫자가 아니면 성공 점수를 기록하지 않습니다. 실행 상태가 unknown이면 재실행하지 않습니다. 실행·API 횟수·시간 제한이 있으며 실제 금액 한도를 보장하지 않습니다. API 대기 마감 후에도 원격 서버가 요청을 처리·과금할 수 있습니다. 실행 로그는 종료 시 저장하므로 CLI를 강제 종료하면 로그가 비어 있을 수 있습니다. API 사용량이 없으면 미확인으로 남깁니다.

## 해석, 판단 확정, 기억

```sh
zar research advance SESSION_ID --send --project ./my-ml-project --json
# awaiting_decision의 새 토큰과 제안 근거 확인
zar research decide SESSION_ID --token TOKEN --project ./my-ml-project --json
# remembering: 확정 판단을 입력으로 기억 역할 호출
zar research advance SESSION_ID --send --project ./my-ml-project --json
```

해석은 실제 관측과 비교 결과를 근거로 keep/discard/hold를 제안합니다. `decide`는 canonical 판단을 확정하며, 유효한 keep를 현재 선택으로 채택하려면 명시적으로 `--select`를 추가합니다. 선택은 코드 체크아웃이나 되돌리기가 아닙니다. discard도 적용한 코드를 자동 복원하지 않습니다.

마지막 호출은 기억 제안과 한계를 세션에 저장하고 `complete`로 끝납니다. 이후 세션은 최근 완료 세션 최대 5개의 기억 제안을 참고합니다. 이는 canonical 실패 기억 레코드를 자동 등록하는 기능이 아닙니다. 검증된 실패 기억을 별도로 관리하려면 기존 `memory add` 계약을 사용합니다. `next_action=continue`도 자동 반복 실행 권한은 아닙니다. 다음 실험은 새 세션·새 승인·새 지표 경로로 시작합니다.

## 중단과 재개

먼저 `research status`와 실제 프로세스·파일·로그를 확인합니다. 저장 중 프로세스를 강제 종료하면 기존 `.autoresearch/.lock`이 남을 수 있습니다. 이 경우 잠금 파일의 PID와 실제 실행 상태를 확인하여 해당 프로젝트를 사용하는 CLI가 모두 종료됐음을 확인한 뒤에만 남은 잠금 파일을 수동 정리하고 복구 명령을 실행합니다. PID 존재 여부만으로 종료를 단정하거나 실행 중인 잠금을 지우지 마세요. 자동 잠금 해제는 제공하지 않습니다.

| 저장 상태 | 처리 |
|---|---|
| planning / observed / remembering | 입력과 남은 예산이 유효하면 `advance --send` |
| awaiting_approval / approved | 구체적 승인 확인 후 approve 또는 run |
| awaiting_decision | 판단 내용 확인 후 decide |
| calling | 이전 CLI가 종료되었는지 확인한 뒤 recover; 이전 API는 처리·과금되었을 수 있음 |
| applying | recover 후 blocked; 부분 변경과 기록을 수동 확인하며 자동 재적용하지 않음 |
| deciding | recover로 이미 확정된 판단을 확인하고 남은 저장 절차 복구 |
| executing / unknown | 실제 실행 확인과 새 근거를 canonical experiment에 기록한 뒤 reconcile |

```sh
zar research recover SESSION_ID --confirm-stopped --project ./my-ml-project --json
zar research reconcile SESSION_ID --project ./my-ml-project --json
```

`--confirm-stopped`는 프로세스를 종료하는 명령이 아니라 사용자의 확인입니다. 실행 중인 CLI에 사용하지 마세요. `reconcile`도 상태를 추측하거나 실행을 재시도하지 않습니다. 실제 확인 없이 unknown을 성공으로 변경하지 않습니다. 입력 동일성 검사는 명시적으로 전달한 소스와 프로젝트 설정·기록·허용된 환경변수에 한정합니다. 외부 데이터나 실행 바이너리 전체를 추적하는 기능은 아닙니다. 프로젝트·소스·기록 변경이나 예산 소진은 재개를 차단할 수 있으며 한도를 자동 늘리지 않습니다.

## 저장과 한계

`.autoresearch/sessions/`는 별도 연구 세션 상태, `.autoresearch/session-artifacts/`는 실행 근거와 입력 자료입니다. canonical v1 experiment/decision이 관측·판단의 원본입니다. 세션 기록에는 허용한 코드와 모델 제안이 포함될 수 있으므로 공개 커밋 전에 내용을 확인하세요. API 키 값과 인증 헤더는 저장하지 않습니다.

`setup`은 정해진 질문으로 설정을 수집합니다. 자유로운 자연어 대화로 평가 방식·학습 코드를 자동 구성하는 기능, 설치된 Codex·Claude Code를 직접 실행하는 어댑터, 무인 연속 실험은 후속 범위입니다. 역할별 API 주입은 구현되어 있지만 실제 공급자 연결 검증과 실사용 효용 비교가 끝난 것으로 표시하지 않습니다. [설계와 검증 범위](llm-experiment-cli.md)를 참고하세요.

## 비용 없이 전체 흐름 확인하기

개발 소스의 `examples/api-loop.py`는 로컬 모의 HTTP API와 고정된 실험 코드를 사용합니다. 설치된 개발 패키지의 Python으로 실행하고 `--output`에는 존재하지 않는 새 경로를 지정하세요.

```sh
python examples/api-loop.py --output ./api-loop-demo
```

예제는 알려진 합성 변경과 명령만 자동 승인합니다. 일반 사용자 프로젝트의 승인을 대신하는 예시가 아닙니다. 7개 역할 호출, 승인 전 미실행, 실제 프로세스의 0.25 관측값, keep·선택·기억 완료를 확인하고 `events.json`과 `summary.json`을 남깁니다. API 비용과 실제 ML 학습은 발생하지 않습니다.
