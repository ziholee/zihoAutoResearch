# API·Codex 연결 연구 세션 사용법

상태: 개발 브랜치 구현 · 미배포 · 공개 v0.3.0에는 `research` 명령이 없습니다.

이 흐름은 기존 로컬 프로젝트의 설정부터 API 모델의 제안, 사용자 승인, 실제 명령 실행과 결과 기록을 연결합니다. 기존 기록 명령은 계속 LLM 없이 사용할 수 있습니다. 이번 검증은 모의 HTTP 공급자·모의 Codex 실행 파일과 결정적 로컬 프로그램 기준입니다. 실제 클라우드 API·Codex 추론·인증, Windows 실행, 실제 ML 개선 효과는 미검증입니다.

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

- 프로젝트 이름·목표, 실험 모드(`baseline` 또는 `candidate`), 데이터·분할·평가 방식의 식별자, 지표·방향·최소 개선량
- 실행 환경, 실험 횟수·시간 한도, 실행 명령 이름·작업 폴더
- 명령의 인자 개수와 각 인자, 수정 허용 파일과 API로 보낼 파일
- 연결 방식(`api` 또는 `codex`): API는 서버 주소·모델·키 환경변수 이름, Codex는 신뢰할 수 있는 설치 명령·모델
- 새 지표 파일·키, 비교 범위·seed·예산 식별자와 세션 호출·시간 한도

예를 들어 `python train.py --output metrics/run-001.json`은 인자 4개로 입력합니다: `python`, `train.py`, `--output`, `metrics/run-001.json`. 각 질문에 인자 하나를 그대로 입력하며 셸용 따옴표를 추가하지 않습니다. 평가 식별자와 실행 명령은 사용자가 지정한 실제 조건이어야 합니다. CLI가 적절한 평가 방법이나 학습 코드를 자동으로 만들어 주지는 않습니다.

API 키 값은 질문하지 않습니다. API 방식은 실제 호출 전에 지정한 환경변수를 설정하고, Codex 방식은 기존 Codex 인증을 사용합니다. 설정이나 버전 확인만으로 인증·모델 호환성이 확인되는 것은 아닙니다. `revise`와 `next`는 선택한 연결 프로필을 기본값으로 이어 받습니다.

설정 요약을 확인한 뒤 **저장에 동의**하면 설정과 세션을 저장합니다. 이어서 전송 대상과 파일 범위를 확인하고 **전송에 별도로 동의**하면 분석 → 평가 검토 → 설계 → 구현 제안 → 변경 검토를 호출합니다. 두 확인 모두 기본값은 거절입니다. 정상 계획은 `awaiting_approval`에서 멈추며, 설정 명령은 변경 적용·실험 실행·승인을 수행하지 않습니다. 모델의 누락 설정·hold/invalid 판단이나 API 실패가 있으면 출력 상태를 확인하세요.

저장 전 `:cancel`, EOF 또는 Ctrl-C로 취소하면 초기화·설정 쓰기를 하지 않습니다. 저장 후 전송을 거절하거나 취소하면 저장된 설정과 세션은 유지됩니다. 세션 ID로 `research status`를 확인하고 필요할 때 `advance --send`로 이어갑니다. 질문 도중 다른 프로세스가 설정·기록을 바꾸면 덮어쓰지 않고 중단하므로 상태를 확인한 뒤 다시 시작하세요. 기존 비교 조건을 바꾸려면 새로운 비교 ID가 필요합니다.

`setup`에는 대화형 터미널 입력이 필요하므로 파이프 입력은 거부합니다. `--json` 사용 시 질문·안내는 stderr, 최종 `{ok, data, diagnostics}` 객체 하나는 stdout에 출력합니다. 에이전트의 비대화형 도구에서는 아래 명시적 명령 흐름을 사용하세요.

## 추가 질문과 계획 수정

누락 설정이나 `hold/invalid` 때문에 막혔거나, 실행 전 계획을 거절·수정하려면 먼저 상태와 `next_actions` 안내를 확인합니다.

```sh
zar research status SESSION_ID --project ./my-ml-project --json
zar research revise SESSION_ID --project ./my-ml-project
```

`revise`는 대화형 터미널에서 분석 역할이 남긴 누락 질문에 대한 답과 수정 요청을 받고, 기존 연결·파일 범위·명령·지표 설정을 기본값으로 설정 질문을 다시 보여줍니다. 답변과 피드백도 새 계획의 API 입력에 포함되므로 비밀 키나 민감한 데이터를 입력하지 마세요. 모델의 질문은 확인할 자료이며 명령 실행 지시가 아닙니다. 실제 비교 조건을 바꾸면 설정에서도 수정하고 새로운 비교 ID를 지정합니다.

저장과 전송은 각각 확인하며 기본값은 거절입니다. 저장하면 이전 세션과 연결된 새 세션을 만들고 이전 세션을 `rejected`로 바꾸고 승인 토큰을 제거합니다. `superseded_by`는 새 세션을 가리킵니다. 이전 제안·호출 기록은 남지만 새 계획의 승인으로 재사용하지 않습니다. 새 계획은 분석부터 다시 검토하고 새 토큰으로 승인받아야 하며, `revise` 자체는 코드를 적용하거나 실험을 실행하지 않습니다. 저장 전 취소에는 변경이 없고 저장 후 전송을 거절하면 새 세션은 전송 대기 상태로 남습니다.

저장은 여러 파일을 바꾸며 전체가 하나의 원자적 트랜잭션은 아닙니다. 저장 도중 실패하면 이전 승인은 무효화됐지만 설정이나 새 세션 저장은 일부만 완료됐을 수 있습니다. 이때 자동 재실행하지 말고 이전 세션의 `status`, 프로젝트 설정과 세션 파일을 확인합니다. 이전 세션에 `revision_save_started`가 남아 있으면 저장이 중단된 상태로 취급합니다.

수정 대상은 실험 ID가 없는 실행 전 `planning`, `blocked`, `rejected`, `awaiting_approval`, `approved` 세션입니다. 호출·적용·실행 중이거나 실행 여부가 불명확한 세션, 이미 실험 기록을 만든 세션은 이 경로로 우회하지 않습니다. 적용 중단을 복구한 세션도 부분 변경 검사가 필요하므로 수정 대상에서 제외합니다. 아래 복구 절차로 실제 상태와 근거부터 확인하세요. `next_actions`는 상태에 맞는 명령·선행 조건 안내이며 자동 복구나 실행 권한이 아닙니다. 프로젝트·입력 변경, 남은 예산 및 실제 프로세스를 확인한 뒤 안내를 사용합니다. 안내 명령은 프로젝트 루트에서 실행하거나 `--project`를 추가하세요. 답변·수정 요청은 각각 4,000자, 이전 제안 요약을 포함한 수정 맥락은 총 32KB까지 받습니다.

## 설정된 프로젝트에서 명시적으로 시작하기

`status`의 `ready` 및 `check` 결과를 확인한 프로젝트에서 사용합니다.

```sh
export MY_LLM_API_KEY='사용자가 발급한 키'
zar research start --project ./my-ml-project \
  --base-url https://your-provider.example/v1 \
  --model your-model --api-key-env MY_LLM_API_KEY \
  --mode baseline \
  --goal '원본 실행으로 현재 평가 조건의 기준을 확보한다' \
  --read train.py --command train \
  --metric-file metrics/run-001.json --metric-key score \
  --scope full --seed 42 --budget-ref fixed-protocol-v1 \
  --max-calls 9 --session-seconds 1800 --json
```

`--read`는 반복 지정할 수 있습니다. 지정한 기존 UTF-8 파일만 소스 본문으로 전송하며 모델 수정도 전송한 파일과 `editable_paths`의 교집합에 한정합니다. 숨김 경로·심볼릭 링크·크기 초과 파일은 거부합니다. 새 파일 생성은 현재 세션 흐름에서 지원하지 않습니다. `.env`, 데이터셋 전체, 저장소 전체를 자동 수집하지 않습니다. 사용자가 지정한 파일 자체에 민감한 정보가 없는지 확인하세요.

연결 플래그 대신 `--profile profile.json`을 사용할 수 있습니다. 프로필 필드는 `base_url`, `model`, `api_key_env`, 선택적 `timeout_seconds`, `max_output_tokens`, `max_response_bytes`입니다. HTTPS 또는 로컬 루프백 HTTP만 허용합니다. 모델은 JSON 응답 형식과 해당 API 필드를 지원해야 합니다. 자동 공급자 대체나 자동 재시도는 없습니다.

## 설치된 Codex로 연결하기

개발 소스에서만 지원합니다. 신뢰하는 **Codex CLI 0.162.1 이상**이 설치된 macOS/Linux가 첫 지원 범위입니다. Windows에서는 Codex 어댑터 실행을 거부하므로 API 방식을 사용하세요. `codex --version`으로 버전을 확인하고 기존 Codex 인증을 준비합니다. 도움말·버전 검사는 로그인이나 실제 모델 호출 성공을 검증하지 않습니다.

설정된 프로젝트에서 API 연결 플래그 대신 다음처럼 지정합니다. 실행 명령·평가 조건·파일 범위는 위 API 예시와 같은 계약입니다.

```sh
zar research start --project ./my-ml-project \
  --provider codex --codex-command codex --model your-codex-model \
  --mode baseline --goal '원본 실행으로 현재 평가 조건의 기준을 확보한다' \
  --read train.py --command train \
  --metric-file metrics/run-001.json --metric-key score \
  --scope full --seed 42 --budget-ref fixed-protocol-v1 \
  --max-calls 9 --session-seconds 1800 --json
```

또는 `--profile profile.json`으로 아래 프로필을 전달합니다. Codex 프로필에는 `base_url`, `api_key_env`, `max_output_tokens`를 넣지 않습니다. `command`는 실행 파일 이름 또는 경로 하나이며 셸 문자열이나 추가 옵션을 받지 않습니다. 기존 API 프로필은 변경 없이 사용할 수 있으며 연결 방식 생략 시 API가 기본입니다.

```json
{
  "provider": "codex",
  "command": "codex",
  "model": "your-codex-model",
  "timeout_seconds": 60,
  "max_response_bytes": 1048576
}
```

Codex는 실험을 실행하는 주체가 아니라 **역할별 JSON 제안 공급자**입니다. 역할 지침과 허용한 맥락을 stdin으로 전달하고, 프로젝트 밖 임시 작업 폴더에서 고정 옵션으로 실행합니다. 읽기 전용 샌드박스·승인 요청 금지·ephemeral 모드와 사용자 설정/규칙 무시를 적용하며 셸·훅·다중 에이전트·웹 검색·앱 기능을 끕니다. 임의 옵션이나 승인을 우회하는 실행 모드는 제공하지 않습니다. JSONL 이벤트의 도구 사용·잘못된 형식·실패를 거부하고 출력 크기·호출 시간을 제한하며 중단 시 소유한 프로세스 그룹을 종료하고 최대 1초 동안 정리를 확인합니다. 종료 확인이 안 되면 `agent_cleanup_unconfirmed`와 `calling` 상태로 남아 재호출을 막습니다. 실제 프로세스가 중지했는지 확인한 뒤 `recover --confirm-stopped`로 복구해야 합니다. 프로세스 그룹을 벗어나 분리된 자식까지 강제로 격리하는 OS 보장은 없습니다. 자동 재시도는 없습니다.

이 제한은 신뢰하는 설치 실행 파일과 Codex가 준수하는 설정에 의존합니다. 관리 설정의 영향을 포함해 임의 바이너리의 모든 OS 접근을 차단한다고 보장하지 않습니다. 도구 이벤트 거부는 응답 검증이며 이미 발생한 외부 동작을 되돌리는 기능이 아닙니다. 기존 Codex 인증을 사용하며 로컬 명령 호출이라도 모델 서비스에 맥락을 전송하고 요금이 발생할 수 있습니다. 키 값이나 원시 오류 출력을 연구 기록에 복사하지 않습니다. 사용량이 제공되지 않으면 미확인으로 남기며 출력 토큰·금액 한도를 보장하지 않습니다.

`start`만으로 Codex를 호출하지 않습니다. 아래와 동일하게 `advance --send`로 전송에 동의하고, 제안을 검토하여 `approve --token` 후 명시적 `run`으로 실험을 실행합니다. 관측 이후 해석·`decide --token`·기억 순서도 유지합니다. Codex의 자체 승인 설정은 이 zar 승인 절차를 대체하지 않습니다. **실제 Codex 모델 호출과 실제 API 검증은 후속으로 남겨 두었으며, 현재 근거는 모의 실행 파일 검증입니다.**

호출·설정 기준은 Codex 공식 [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode), [CLI 옵션](https://learn.chatgpt.com/docs/developer-commands?surface=cli), [설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)를 따릅니다.

## 원본 실행으로 기준 확보하기

선택된 실험이 없는 프로젝트에서는 `start`의 기본 모드가 `baseline`입니다. `--mode baseline`으로 명시할 수도 있습니다. 대화형 `setup`에서는 `experiment_mode` 질문을 확인합니다. 이 모드는 현재 작업 파일을 원본으로 실행하여 기준을 측정하며 모델이 제안한 코드 변경을 허용하지 않습니다. Git의 과거 원본을 복원하거나 데이터·평가 타당성을 자동 인증하는 기능은 아닙니다. 설정한 명령 자체는 파일을 쓸 수 있으므로 명령과 입력을 먼저 확인하세요.

기준 실험에도 전송 동의, 계획 검토, 새 승인과 명시적인 `run`이 필요합니다. 실제 프로세스가 남긴 로그·지표만 관측값으로 사용합니다. 실패·unknown·지표 누락은 유효한 기준으로 승격하지 않습니다. 성공 후 해석·근거를 확인하여 유효한 keep 판단을 확정하고 현재 기준으로 선택하려면 `decide ... --select`를 사용합니다. 모델의 pass나 실행 성공만으로 keep·선택을 자동 수행하지 않습니다.

`--mode candidate`는 현재 선택된 유효한 keep 실험을 비교 기준으로 사용합니다. 비교 조건·환경·scope·예산 프로토콜이 맞아야 하며, 선택된 기준이 없거나 비교가 불가능하면 후보 계획을 시작하지 않습니다. 선택된 실험이 있으면 기본 모드는 `candidate`입니다. 기준을 새로 측정할 목적이라면 `baseline`을 명시하고 비교 조건 변경에 필요한 새 비교 ID도 준비하세요. 이전 버전에서 생성되어 모드가 없는 세션을 원본 무변경 기준 실험으로 소급 인증하지 않습니다.

## 제안부터 실행까지

`start`는 세션을 저장할 뿐 API·Codex 호출이나 실험을 실행하지 않습니다. 출력의 세션 ID, 전송 대상·파일·프로젝트 설정·제한된 기록 범위를 확인합니다. 아래 `SESSION_ID`, `TOKEN`은 실제 출력 값으로 바꿉니다.

```sh
zar research status SESSION_ID --project ./my-ml-project --json
zar research advance SESSION_ID --send --project ./my-ml-project --json
```

`--send`가 선택한 API 또는 Codex 모델 서비스로의 전송 동의입니다. 분석 → 평가 검토 → 설계 → 구현 제안 → 변경 검토를 각각 별도 호출합니다. 누락 설정이나 hold/invalid 판정은 차단합니다. 정상적으로 끝나면 `awaiting_approval`과 실제 diff, 명령, 승인 토큰을 반환합니다. 같은 모델의 재검토는 독립적인 코드 검증이 아닙니다.

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

마지막 호출은 기억 제안과 한계를 세션에 저장하고 `complete`로 끝납니다. 이후 세션은 최근 완료 세션 최대 5개의 기억 제안을 참고합니다. 이는 canonical 실패 기억 레코드를 자동 등록하는 기능이 아닙니다. 검증된 실패 기억을 별도로 관리하려면 기존 `memory add` 계약을 사용합니다. `next_action=continue`도 자동 반복 실행 권한은 아닙니다. 다음 실험은 새 세션·새 승인·새 지표 경로로 시작합니다. 아래 `next`는 이 준비 과정을 연결합니다.

## 완료된 실험에서 다음 실험으로 이어가기

```sh
zar research next COMPLETED_SESSION_ID --project ./my-ml-project
```

`next`는 대화형 터미널에서 `complete` 세션의 연결 프로필·파일 범위·실행 조건을 기본값으로 설정 질문을 다시 엽니다. 다음 목표와 실험 모드를 검토하고 **아직 존재하지 않는 새 지표 경로**를 지정합니다. 프로그램이 그 경로에 실제로 출력하도록 명령 인자도 확인하세요. CLI가 임의 명령의 인자를 자동 변경하지 않습니다. baseline은 모델 코드 변경을 허용하지 않으므로 원본 프로그램의 출력 경로 옵션을 사용하세요. 저장과 모델 전송은 각각 확인하고 새 계획에서 새 승인을 받습니다. 자동 반복·실행은 하지 않습니다.

이전 완료 세션과 실제 실험의 관측·확정 판단·기억 제안을 제한된 맥락으로 전달합니다. 부모 세션과 비교 기준은 서로 다릅니다. 직전 후보를 discard/hold했다면 그 후보가 자동 기준이 되지 않으며 현재 선택된 유효한 keep 실험이 비교 기준입니다. 연결은 이전 완료 기록을 수정하거나 승인을 재사용하지 않습니다. 기억 제안은 canonical 실패 기억으로 자동 등록하지 않습니다.

`complete` 이전 세션은 먼저 기존 판단·기억 또는 복구 절차를 마쳐야 합니다. unknown 실행을 새 세션으로 우회하지 않습니다. discard는 코드를 되돌리지 않고 선택도 작업 파일을 체크아웃하지 않으므로, 다음 계획 전에 현재 작업 파일이 의도한 시작 상태인지 직접 확인하세요. 비교 조건이 바뀌면 새로운 기준을 마련합니다. 비대화형 도구는 TTY를 흉내 내지 말고 명시적 `research start`를 사용합니다.

## 중단과 재개

먼저 `research status`와 실제 프로세스·파일·로그를 확인합니다. 저장 중 프로세스를 강제 종료하면 기존 `.autoresearch/.lock`이 남을 수 있습니다. 이 경우 잠금 파일의 PID와 실제 실행 상태를 확인하여 해당 프로젝트를 사용하는 CLI가 모두 종료됐음을 확인한 뒤에만 남은 잠금 파일을 수동 정리하고 복구 명령을 실행합니다. PID 존재 여부만으로 종료를 단정하거나 실행 중인 잠금을 지우지 마세요. 자동 잠금 해제는 제공하지 않습니다.

| 저장 상태 | 처리 |
|---|---|
| planning / observed / remembering | 입력과 남은 예산이 유효하면 `advance --send` |
| awaiting_approval / approved | 구체적 승인 확인 후 approve 또는 run |
| awaiting_decision | 판단 내용 확인 후 decide |
| blocked / rejected | 실행 전 수정 가능 조건을 확인한 뒤 revise; 실행 이력이 있으면 실제 근거 확인 |
| superseded_by가 있는 이전 세션 | 연결된 새 세션의 status 확인; 이전 세션 실행·승인 재사용 불가 |
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

`setup`은 정해진 질문으로 설정을 수집합니다. 자유로운 자연어 대화로 평가 방식·학습 코드를 자동 구성하는 기능, Claude Code 실행 어댑터와 무인 연속 실험은 후속 범위입니다. Codex 연결은 위 제한으로 구현했으며 모의 에이전트로 검증합니다. 역할별 API 주입은 구현되어 있지만 실제 공급자 연결 검증과 실사용 효용 비교가 끝난 것으로 표시하지 않습니다. [설계와 검증 범위](llm-experiment-cli.md)를 참고하세요.

## 비용 없이 전체 흐름 확인하기

개발 소스의 `examples/api-loop.py`는 로컬 모의 HTTP API와 고정된 실험 코드를 사용합니다. 설치된 개발 패키지의 Python으로 실행하고 `--output`에는 존재하지 않는 새 경로를 지정하세요.

```sh
python examples/api-loop.py --output ./api-loop-demo
```

예제는 알려진 합성 프로그램의 무변경 기준 실행과 명령만 자동 승인합니다. 일반 사용자 프로젝트의 승인을 대신하는 예시가 아닙니다. 7개 역할 호출, 승인 전 미실행, 실제 프로세스의 0.25 관측값, keep·선택·기억 완료를 확인하고 `events.json`과 `summary.json`을 남깁니다. API 비용과 실제 ML 학습은 발생하지 않습니다.

## 호출 효율과 측정 범위

역할별 JSON 맥락은 내용 손실 없이 공백을 줄여 전송하고, 호출 전 검사에서 읽은 기록을 같은 잠금 구간의 맥락 생성에 재사용합니다. 모델 응답 후에는 신선도를 다시 확인합니다. 7개 역할 호출과 승인 경계는 유지하며 실제 공급자 지연·토큰 비용은 아직 측정하지 않았습니다. [모의 루프 측정 결과와 재현 방법](research-loop-performance.md)을 참고하세요.


### 역할별 호출 측정 조회

개발 소스에서는 새 호출 시도마다 로컬 소요 시간·메시지 바이트·공급자가 보고한 토큰 수를 기록합니다. 조회는 기록만 읽으며 모델 호출이나 세션 변경을 하지 않습니다.

```sh
zar research metrics SESSION_ID --project ./my-ml-project --json
```

JSON 결과의 `data`는 `view: "research_metrics"`, `session_id`, `state`, `version: 1`, 세션 전체 `total`과 역할별 `roles`를 포함합니다. 각 집계에는 `attempts`, `measured_attempts`, `unmeasured_attempts`와 다음 측정값이 있습니다.

| 필드 | 단위와 범위 |
|---|---|
| `call_seconds` | 로컬 호출 함수의 경과 초. 공급자 대기와 Codex 사전 확인·종료 정리를 포함하며 맥락 준비·역할 응답 검증은 제외 |
| `input_message_bytes` | 호출을 위해 준비한 system/user 메시지 본문의 UTF-8 바이트 합. HTTP/프로세스 포장·헤더를 제외하며 실제 전송 완료를 입증하지 않음 |
| `output_text_bytes` | 어댑터가 반환한 assistant 본문의 UTF-8 바이트. 원시 공급자 응답·헤더·Codex 이벤트 전체 크기가 아님 |
| `tokens.input_tokens` / `output_tokens` / `total_tokens` / `cached_input_tokens` | 공급자가 보고한 해당 토큰 수. HTTP의 prompt/completion 및 Codex의 input/output 항목을 공통 이름으로 정규화 |

각 측정값은 `{ "value": 합계 또는 null, "observations": 관측 수 }`입니다. 예를 들어 시도 3회 중 입력 토큰이 2회만 보고되면 그 두 값만 합산하고 `observations: 2`로 표시합니다. 관측이 전혀 없으면 `value: null`, `observations: 0`이며 실제 보고된 0은 `value: 0`입니다. `measured_attempts`는 측정 레코드가 있는 시도 수로, 모든 항목을 관측했다는 뜻이 아닙니다. 합계를 비교할 때는 반드시 항목별 관측 수를 함께 확인하세요.

토큰은 유효한 비음수 정수만 집계합니다. 현재 HTTP 어댑터는 중첩된 캐시 사용량을 전달하지 않으므로 `cached_input_tokens`는 미확인으로 남으며, Codex가 보고한 캐시 입력 토큰은 집계합니다. 공급자가 `total_tokens`를 생략해도 입력·출력의 합으로 채우지 않으며 캐시 토큰을 입력에서 빼지 않습니다. 토큰 없는 응답, 실패·타임아웃, 역할 형식이 잘못된 응답도 확보한 측정만 남깁니다. 재시도는 별도 시도로 집계합니다. 과거 기록은 소급 측정하지 않고, 호출 시도 수는 저장했으나 trace를 남기기 전에 중단된 경우 세션 전체의 `unmeasured_attempts`에 차이가 남습니다. 역할을 알 수 없는 누락은 역할별 합계에 배분하지 않습니다.

개별 측정은 기존 세션 trace의 `measurement`에 버전 1과 함께 저장되고 `research status`에서도 확인할 수 있습니다. 측정을 위해 인증 헤더·원시 오류 본문·새 비밀정보를 저장하지 않습니다. 이 수치는 청구 금액이나 순수 모델 생성 시간, 실제 전체 실험 시간의 측정이 아닙니다. 기존 7개 역할·승인·호출 및 시간 예산은 유지합니다. 모의 공급자로 검증하며 실제 API·Codex 추론의 사용량·지연 검증은 후속입니다.
