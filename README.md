# zihoAutoResearch

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

[![PyPI version](https://img.shields.io/pypi/v/ziho-autoresearch?logo=pypi&logoColor=white)](https://pypi.org/project/ziho-autoresearch/)
[![Python 3.11 이상](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![Contract CI](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml/badge.svg?branch=dev&event=push)](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml?query=branch%3Adev)
[![Agent Skills: Codex / Claude Code](https://img.shields.io/badge/Agent%20Skills-Codex%20%2F%20Claude%20Code-5865F2)](docs/agent-installation.md)

**기존 ML 프로젝트의 실험 근거·결과·판단을 로컬에 기록하고, 다음 세션에서 이어가는 가벼운 CLI와 에이전트 스킬입니다.**

전처리, 모델, 손실 함수, 최적화 방법을 바꿀 때 “왜 시도했는지, 어떤 조건에서 비교했는지, 무엇을 채택했는지”를 함께 남깁니다. 데이터나 학습 환경을 새 플랫폼으로 옮길 필요 없이 기존 프로젝트에서 사용합니다.

배지는 최신 PyPI 버전, 지원 Python 버전, 라이선스, `dev` 브랜치의 CI 상태와 지원 에이전트를 안내합니다. 각 배지를 클릭하면 상세 정보를 확인할 수 있습니다.

[PyPI](https://pypi.org/project/ziho-autoresearch/) · [GitHub 릴리스](https://github.com/ziholee/zihoAutoResearch/releases) · [변경 내역](CHANGELOG.md) · [문제 제보](https://github.com/ziholee/zihoAutoResearch/issues)

## 어떤 도구인가요?

- **CLI (`zar`)**: 실험 계획·관측·비교·판단을 JSON으로 저장하고 형식·참조·근거 파일을 검사합니다.
- **에이전트 스킬**: 사용 중인 코딩 에이전트가 프로젝트를 읽고, 허용된 범위 안에서 연구 절차를 따르도록 안내합니다.
- **재개와 보고서**: 미완료 실험, 실패 기억, 후보 근거, 실험 계보를 조회하고 Markdown 보고서를 만듭니다.

공개 v0.3.0의 기록 명령은 LLM 호출이나 학습을 실행하지 않습니다. **개발 브랜치에는 미배포 `research` 명령을 추가했습니다.** 원하는 OpenAI 호환 API 또는 설치된 Codex에 역할별 지침을 전달하고, 사용자 승인 후 로컬 실험 한 번을 실행·기록합니다. [API 연구 세션 사용법](docs/research-api.md)에서 연결·승인·재개 절차와 검증 범위를 확인하세요. 실제 클라우드 API 연결은 아직 검증하지 않았으며, 자동 코드 복구·대회 제출은 제공하지 않습니다. `check` 통과도 데이터 누수나 모델 품질의 자동 판정을 뜻하지 않습니다.

**개발 소스 전용:** `zar research setup --project ./my-ml-project`를 터미널에서 실행하면 질문에 답해 JSON 수동 편집 없이 설정부터 첫 실험 계획까지 진행합니다. 저장과 모델 전송은 따로 확인하며 계획의 승인 대기에서 멈춥니다. 기존 학습 코드·평가 조건은 사용자가 준비합니다. [대화형 설정 안내](docs/research-api.md#질문에-답해-첫-계획-만들기)를 참고하세요. 실행 전 계획이 막혔거나 수정이 필요하면 `zar research revise SESSION_ID --project ./my-ml-project`로 추가 질문에 답하고 새 계획을 만들 수 있습니다. `research status`는 다음 행동을 안내하며, 수정된 계획에는 새 승인이 필요합니다.

첫 기준은 `baseline` 모드로 모델 변경 없이 현재 원본을 실행해 확보합니다. 후보 계획에는 비교 가능한 선택된 유효 keep 실험이 필요합니다. 완료 후 `zar research next SESSION_ID --project ./my-ml-project`로 설정·판단·기억 맥락을 이어 다음 계획을 준비하며, 새 지표 경로와 새 전송 동의·승인이 필요합니다. 자동 코드 복원이나 반복 실행은 하지 않습니다.

개발 소스에서는 `research start --provider codex --codex-command codex --model <모델>`로 설치된 Codex를 선택하거나 `research setup`에서 연결 방식을 고를 수 있습니다. 신뢰하는 Codex CLI 0.162.1 이상과 macOS/Linux가 필요합니다. 기존 Codex 인증을 사용하며 모델 서비스 전송·요금이 발생할 수 있습니다. Codex는 제안을 반환하고 기존 zar 전송·실행·판단 승인 절차를 그대로 따릅니다. 모의 에이전트로 검증했으며 실제 Codex 인증·추론은 미검증입니다. [지원 범위와 연결 안내](docs/research-api.md#설치된-codex로-연결하기)를 확인하세요.

개발 소스의 세션 기억은 모델 제안과 CLI의 관찰 근거를 분리합니다. 근거 부족·효과 혼재·단일 비교의 일반화는 보류하며, 기존 세션 재개와 승인 절차를 유지합니다. [세션 기억의 근거와 한계](docs/session-memory-evidence.md)를 확인하세요. 새 세션은 [관련성 기반 선택](docs/session-memory-relevance.md)으로 조건이 맞는 과거 기억을 우선하며, 조건 일치를 효과 입증으로 간주하지 않습니다.

개발 소스의 `zar research metrics SESSION_ID --project ./my-ml-project --json`으로 역할별 호출 시간·메시지 바이트·보고된 토큰을 조회할 수 있습니다. 누락값과 부분 관측을 구분하며 실제 전송량·요금을 추정하지 않습니다. [측정 범위](docs/research-api.md#역할별-호출-측정-조회)를 확인하세요. 입력의 지침·소스·기록·누적 응답 크기와 필수 근거를 보존하는 중복 제거 범위는 [요청 맥락 효율화](docs/request-context-efficiency.md)에 설명합니다. 실제 API 품질·비용 검증은 후속입니다.

`zar`는 **zihoAutoResearch의 약칭이자 실행 명령어**입니다. 설치할 패키지 이름은 `ziho-autoresearch`이고, 설치 후에는 `zar init`, `zar status`처럼 사용합니다.

## 1. 설치

Python **3.11 이상**이 필요합니다. 런타임 외부 라이브러리 의존성은 없습니다. Git 연결 기능을 사용할 때만 Git 실행 파일이 필요합니다.

[uv](https://docs.astral.sh/uv/getting-started/installation/)가 있다면:

```sh
uv tool install ziho-autoresearch
zar --help
```

아래 버전 고정 예시는 v0.3.0 기준입니다. 현재 공개 상태는 [릴리스 목록](https://github.com/ziholee/zihoAutoResearch/releases)을 확인하세요.

`zar`를 찾지 못하면 `uv tool update-shell`을 실행하고 터미널을 다시 여세요. 버전 고정은 `uv tool install 'ziho-autoresearch==0.3.0'`, 업데이트는 `uv tool upgrade ziho-autoresearch`로 합니다. 고정 버전이나 URL 설치의 업데이트 방법은 [uv 안내](docs/uv-installation.md)를 참고하세요.

uv 없이 설치하려면:

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell에서는 위 줄 대신:
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
zar --help
```

## 2. 기존 프로젝트 연결

아래 `./my-ml-project`를 **이미 존재하는 ML 프로젝트 폴더**로 바꾸세요. Windows에서도 경로에 공백이 있으면 따옴표로 감싸면 됩니다.

```sh
zar init --project ./my-ml-project
zar status --project ./my-ml-project --json
```

프로젝트 안에 `.autoresearch/`가 생성됩니다. 기존 코드·루트 `program.md`·`AGENTS.md`는 보존합니다. `--project`를 생략하면 현재 폴더를 사용하며 상위 폴더를 자동 탐색하지 않습니다.

처음에는 `ready:false`가 정상입니다. 목표, 비교 지표, 데이터·코드 식별자, 실행 환경, 명령, 예산, 수정 허용 경로를 채워야 합니다. 다음 단계의 에이전트에 설정을 도와달라고 하거나 [처음 사용 안내](docs/first-run-and-resume.md)를 따라 직접 작성하세요.

## 3. 에이전트에서 스킬 사용

### Codex / Claude Code에 바로 설치

**v0.3.0부터 지원합니다.** 설치 방법과 전체 절차는 [에이전트 설치 안내](docs/agent-installation.md)를 참고하세요. CLI가 설치된 뒤 사용할 에이전트 하나를 선택합니다.

```sh
# Codex: 지정한 ML 프로젝트에만 설치
zar skill install --agent codex --project ./my-ml-project

# Claude Code를 사용하는 경우
zar skill install --agent claude --project ./my-ml-project
```

필요한 스킬 폴더를 만들고 번들 전체를 복사합니다. 기존 스킬은 덮어쓰지 않습니다. 대상 프로젝트를 에이전트에서 연 뒤, Codex에서는 `$ziho-autoresearch`, Claude Code에서는 `/ziho-autoresearch`를 선택하고 다음처럼 요청하세요.

> 이 프로젝트를 학습 실행 없이 점검하고 첫 실험 계획을 제안해줘.

목록에 나타나지 않으면 에이전트를 재시작하고 스킬 설정을 확인하세요. 에이전트의 실행 환경에서도 `zar --help`가 실행되어야 합니다. 발견 경로에 설치하므로 기본 사용에 `AGENTS.md` 수동 연결은 필수가 아닙니다. 설치가 학습 실행을 승인하거나 실제 인식을 검증하지는 않습니다.

### 다른 에이전트에서 수동 연결

ML 프로젝트 밖의 편한 작업 폴더에서 실행하세요. `--dest`는 **새로 만들 스킬 폴더**이며 상위 폴더는 이미 있어야 합니다.

```sh
zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json
```

wheel에 포함된 `SKILL.md`와 `references/` 전체를 추출합니다. 기존 폴더를 덮어쓰거나 에이전트에 자동 등록하지 않습니다. 출력된 절대 경로를 사용 중인 코딩 에이전트에 전달하세요.

> `<출력된 스킬 폴더>/SKILL.md`를 읽고 `<ML 프로젝트 절대 경로>`를 점검해줘. 우선 실행 없이 현재 코드·데이터·평가 방법과 누락된 설정을 정리하고, 첫 실험 계획을 제안해줘.

실험 실행까지 맡길 때는 **목표, 허용 변경 경로, 실행 환경, 횟수·시간 한도**도 지정하세요. 비밀 키나 원본 개인정보를 대화 또는 실험 근거에 붙여넣지 마세요. 스킬을 업데이트할 때는 새 폴더로 추출해 사용자 수정과 비교합니다.

### 프로젝트의 AGENTS.md에 연결하기

수동 연결을 유지하거나 프로젝트별 적용 조건을 명시하려면 **실험 대상 프로젝트**의 `AGENTS.md`에 스킬의 `SKILL.md` 경로와 적용 조건을 추가하세요. 기존 규칙은 유지하고, 스킬 전문이나 수시로 바뀌는 실험 상태를 복사하지 않습니다. 에이전트가 해당 지침 파일을 읽도록 설정되어 있는지는 사용하는 도구에서 확인하세요.

아래 연결 문구 생성 명령은 v0.3.0부터 지원합니다.

```sh
zar skill guidance --skill-dir ./ziho-autoresearch-skill-0.3.0
```

이 명령은 기존 스킬의 위치를 넣은 연결 문구를 화면에 출력합니다. 내용을 검토하고 대상 프로젝트의 기존 `AGENTS.md`에 필요한 부분만 병합하세요. 파일 생성·덮어쓰기·에이전트 자동 등록은 수행하지 않습니다. `> AGENTS.md`로 리디렉션하면 셸이 기존 파일을 지울 수 있으므로 사용하지 마세요. 공개 버전에서도 [수동 연결 예시](docs/uv-installation.md#프로젝트-지침에-연결)를 사용할 수 있습니다.

## 4. 기록 확인과 재개

```sh
zar status --project ./my-ml-project --json
zar context --project ./my-ml-project --max-bytes 16384 --json
zar check --project ./my-ml-project --json
```

- `status`: 설정 누락, 현재 선택, 미완료 실험과 예산 확인.
- `context`: 새 세션에 전달할 제한된 크기의 맥락 조회. 근거 파일의 존재·해시는 검사하지 않습니다.
- `check`: 기록과 근거 검사. 종료 코드뿐 아니라 경고 내용도 읽으세요. 초기 설정이 미완성이면 종료 코드 3이 나올 수 있습니다.

중단 후에는 에이전트에게 이렇게 요청할 수 있습니다.

> 같은 스킬과 프로젝트를 읽고 `context`와 `status`로 현재 상태를 확인해줘. `unknown` 실험은 실제 로그·프로세스 상태를 확인하기 전 재실행하지 말고, 새 근거로 상태를 정리해줘.

**기록상 채택과 실제 작업 폴더의 코드는 별개입니다.** `keep` 판단이나 선택 변경이 코드를 되돌리지 않습니다. 정확한 중단·재개 절차는 [처음 사용·재개 안내](docs/first-run-and-resume.md)를 참고하세요.

## 직접 기록할 때의 순서

JSON 입력을 직접 작성하거나 에이전트가 작성한 초안을 검토할 수 있습니다. [CLI 레시피](skills/ziho-autoresearch/references/cli-recipes.md)에 입력 예제가 있고, [파일 계약](docs/cli-and-file-contract.md)에 필수 필드와 상태 전이가 정리돼 있습니다.

| 목적 | 명령 | 안내 |
|---|---|---|
| 프로젝트 초기화 | `zar init` | 기존 프로젝트에 기록 폴더 생성 |
| 연결 문구 생성 | `zar skill guidance --skill-dir` | 기존 스킬 경로로 AGENTS.md용 문구 출력 |
| 에이전트 설치 | `zar skill install --agent` | Codex/Claude Code 발견 경로에 설치 |
| 스킬 추출 | `zar skill install` | 새 폴더로 스킬 복사 |
| 설정 저장 | `zar project set --file <json>` | 현재 project.json을 별도 초안으로 복사해 수정 |
| 실행 전 점검 | `zar review add --file <json>` | 확인한 근거와 미검증 항목 기록 |
| 다음 후보 기록 | `zar candidate add --file <json>` | [관측·예측·선택 이유](docs/candidate-rationale.md) |
| 실험 생성·결과 갱신 | `zar experiment create`, `zar experiment update` | [입력 예제](examples/experiment-create.json), 실제 관측만 기록 |
| 비교·판단 | `zar experiment compare`, `zar experiment decide` | proxy/full 등 비교 조건 확인; 자동 코드 채택 없음 |
| 완료 결과 정정 | `zar experiment correct` | 새 ID로 원본 보존 |
| 실패 기억 | `zar memory add --file <json>` | [실패 원인·대응과 한계](docs/failure-memory.md) |
| 확인된 외부 점수 | `zar submission add --file <json>` | 실제 제출은 별도 수행 |
| 근거 원문 조회 | `zar evidence read` | [해시·부분 조회](docs/context-and-evidence.md) |
| 실험 관계 조회 | `zar lineage` | [JSON·Mermaid 계보](docs/experiment-lineage.md) |
| 보고서 생성 | `zar report --output summary.md` | `.autoresearch/reports/summary.md`에 저장 |
| 코드 커밋 연결 | `zar git status`, `zar experiment create --git-head` | [Git 이력 사용법](docs/git-research-history.md) |

위 명령에도 `--project <프로젝트 경로>`를 붙일 수 있습니다. 자세한 인자는 `zar <명령> --help`로 확인하세요. JSON 입력은 원본과 다른 파일에 작성합니다. `.autoresearch/drafts/`를 쓴다면 먼저 직접 생성해야 합니다.

## 학습 없이 체험하기

예제는 wheel에 포함되지 않습니다. [소스 배포본](https://github.com/ziholee/zihoAutoResearch/releases/tag/v0.3.0)을 풀거나 이 저장소를 내려받고, CLI가 설치된 Python 환경에서 소스 폴더를 기준으로 실행하세요.

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell에서는 위 줄 대신:
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
python examples/mock-cycle.py --output ./demo-cycle
```

`demo-cycle`은 존재하지 않는 새 경로여야 합니다. 예제는 가짜 점수와 로그로 기록 → 비교 → 판단 → 보고서 흐름을 보여주며 학습하지 않습니다. uv tool의 Python 환경과 별도 Python 환경은 패키지를 공유하지 않으므로, 위 예제용 가상환경에도 패키지를 설치합니다. 두 세션의 재개 연습은 [재개 예제](docs/first-run-and-resume.md#학습-없는-두-세션-연습)를 참고하세요.

## 실제 학습·평가 루프 체험하기 (개발 소스)

[합성 회귀 학습 예제](docs/ml-loop-example.md)는 모의 LLM과 실제 로컬 학습으로 기준 실험 → 후보 비교 → 안전한 중단·재개를 확인합니다. 현재 개발 소스를 내려받아 위 가상환경에서 `python -m pip install .` 후 `python examples/ml-loop.py --output ./demo-ml`을 실행하세요. 출력 경로는 새 경로여야 합니다. 공개 v0.3.0에는 필요한 `research` 명령이 없으며, 클라우드 API나 유료 모델은 호출하지 않습니다.

Linux/macOS에서는 [실제 CLI 장애 복구 예제](docs/crash-recovery-validation.md)로 호출·실행 중 강제 종료 후 unknown 보존, 중복 실행 거부와 근거 기반 복구도 확인할 수 있습니다. 모의 공급자만 사용하며 Windows 프로세스 복구는 검증 범위 밖입니다.

[도구 효용 비교](docs/workflow-utility-comparison.md)는 같은 합성 작업을 직접 실행+Git과 zar로 수행해 기록·복구 결과와 실행 부가 비용을 대조합니다. 자동화된 시나리오이며 실제 사용자 시간·LLM 비용 절감을 입증하지 않습니다.

[로컬 루프 비용 분해](docs/local-loop-costs.md)는 CLI 시작·기록 로딩·검증·저장·Git·모의 서버 종료 시간을 구분합니다. 확인된 모의 서버 종료 대기만 줄였으며 제품의 승인·검토·저장·재개 절차는 유지합니다.

[CLI 시작 비용](docs/cli-startup-costs.md)은 Python 시작·import·명령 초기화·계측 준비를 구분합니다. 명령 정의와 연구 실행부를 분리해 일반 조회·도움말의 불필요한 import를 줄이고, 비계측 실행으로 효과를 확인합니다.

[기록·세션 규모별 연구 루프](docs/research-scale-costs.md)는 기록 100·1,000·10,000개와 완료 세션 수를 독립적으로 늘려 계획·조회·재개의 시간·메모리·출력을 비교합니다. 모의 공급자와 승인 대기까지의 동작을 검증하며 실제 API 성능을 뜻하지 않습니다.

[대규모 기록 처리 비용](docs/record-processing-costs.md)은 읽기·파싱·검증·직렬화·해시를 분해합니다. 매 역할의 변경 검사를 유지하면서 같은 `advance` 안에서 검증된 기록 요약의 중복 생성만 줄입니다.

[완료 세션 반복 조회](docs/completed-session-costs.md)는 매 역할의 경로 검사와 원문 읽기를 유지하면서 내용이 같은 과거 세션의 반복 파싱만 줄입니다.

[큰 기록 배치 검증](docs/large-record-batches.md)은 크기가 다른 기록을 63·64·65개 경계와 10,000개 혼합 조건에서 교차 측정합니다.

[기록 해시 일시 메모리](docs/record-digest-memory.md)는 기존 바이트·해시를 유지하는 분할 처리와 작은·혼합 조건의 교차 측정을 다룹니다.

[기록 직렬화 비용](docs/record-serialization-costs.md)은 바이트·해시를 유지하면서 검증된 키의 중복 타입 분기를 줄이고 시간·일시 할당을 분리해 측정합니다.

[혼합 규모 검증](docs/mixed-research-scale.md)은 대규모 기록과 큰 완료 세션을 함께 사용한 계획·조회·재개 및 변경 감지·승인 절차를 확인합니다.

[대규모 기록 메모리](docs/record-memory-costs.md)는 호출 전후 변경 감지를 유지하면서 전체 기록 스냅샷의 중복 보관 비용을 측정합니다.

[큰 세션·캐시 경계](docs/session-cache-boundaries.md)는 큰 응답과 2,048개·8MiB 경계의 시간·메모리·재개 비용 및 기억 선택을 검증합니다.

[macOS CI 비용 분해](docs/macos-ci-costs.md)는 검사 범위를 유지하면서 자식 프로세스·서버 종료·반복 준비·증거 검증 비용을 진단합니다.

## 기록을 공유하기 전에

`.autoresearch/`와 보고서에는 직접 기록한 명령, 파일 경로, 로그 발췌, 근거가 포함될 수 있습니다. 커밋·업로드 전에 비밀 키, 개인 데이터, 비공개 데이터셋·로그를 확인하세요. CLI의 JSON 검사는 비밀정보 탐지나 자동 익명화를 제공하지 않습니다. 원본 증거를 수정하면 저장된 해시와 달라질 수 있으므로 공개용 사본을 따로 만드세요.

잠금이 남아 있으면 실행 중인 CLI가 없는지 확인한 뒤 복구하세요. `.autoresearch/.lock`이나 프로젝트 루트의 `.autoresearch.init.lock`을 무조건 지우지 않습니다. 기록 이력이 크면 `context`를 먼저 사용하세요. `report`와 `lineage`의 전체 출력에는 크기 제한이 없습니다.

## 더 알아보기

- [에이전트 설치·호출·문제 해결](docs/agent-installation.md)
- [설치·업데이트·스킬 갱신](docs/uv-installation.md)
- [처음 설정부터 중단·재개까지](docs/first-run-and-resume.md)
- [연구 절차와 판단 규칙](docs/research-workflow.md)
- [프로젝트 연결·환경 설정](docs/project-adapter-and-environment.md)
- [기록 규모별 성능 측정과 한계](docs/record-scale-performance.md)
- [제품 방향과 참고 연구](docs/product-direction.md)
- [배포 파일 검증](docs/releasing.md) · [기여·CI 기준](docs/automation.md)

소프트웨어 검증은 합성 기록 중심이며 실제 ML 품질이나 학습 비용 절감을 보장하지 않습니다. 라이선스는 [MIT](LICENSE)입니다.
