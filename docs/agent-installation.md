# 에이전트에 설치하고 사용하기

CLI는 기록과 검증을 담당하고 스킬은 에이전트가 이를 사용하는 절차를 제공합니다. **`--agent` 설치와 `skill guidance`는 개발 소스의 미배포 기능이며 공개 v0.2.1에는 없습니다.** 현재 공개 버전은 [수동 추출](uv-installation.md#스킬을-지정-폴더에-설치)로 사용할 수 있습니다.

## 개발 소스로 먼저 사용하기

이 저장소의 원하는 개발 커밋을 체크아웃한 뒤 그 폴더를 지정하여 설치합니다. Python 3.11 이상과 uv가 필요합니다. 아래 경로는 실제 저장소 경로로 바꾸세요. `--force`는 기존 CLI 설치를 이 로컬 소스로 교체하므로 개발 버전을 사용할 때만 선택합니다. 이미 추출한 스킬은 교체하지 않습니다.

```sh
uv tool install --force /absolute/path/to/zihoAutoResearch
zar --help
```

향후 이 기능이 포함된 버전이 공개되면 PyPI 설치로 사용할 수 있습니다. 현재 `uv tool upgrade`만 실행해 이 기능이 생긴다고 가정하지 마세요.

## 프로젝트에 설치

아래 명령 중 사용하는 에이전트 하나를 선택하세요. 대상 ML 프로젝트 폴더는 이미 있어야 합니다. `--project` 생략 시 현재 폴더를 사용하고 상위 Git 루트를 추측하지 않습니다.

```sh
zar skill install --agent codex --project /absolute/path/to/ml-project
zar skill install --agent claude --project /absolute/path/to/ml-project
```

| 에이전트 | 프로젝트 설치 위치 | 명시적 호출 |
|---|---|---|
| Codex | `<프로젝트>/.agents/skills/ziho-autoresearch/` | `$ziho-autoresearch` |
| Claude Code | `<프로젝트>/.claude/skills/ziho-autoresearch/` | `/ziho-autoresearch` |

설치 결과에 실제 경로와 다음 행동을 출력합니다. 대상 프로젝트를 연 에이전트에서 해당 스킬을 선택하고 “학습 실행 없이 코드·데이터·평가 방식을 점검하고 첫 실험 계획을 제안해줘”라고 요청하세요. 이후 실행을 맡길 때 목표·수정 경로·환경·횟수·시간 한도를 지정합니다. CLI는 학습을 시작하지 않습니다.

예를 들어 에이전트에게 설치부터 부탁할 때는 다음처럼 요청할 수 있습니다.

> 이 개발 소스의 ziho-autoresearch CLI를 설치하고, 내 ML 프로젝트에 Codex용 스킬을 프로젝트 범위로 설치해줘. 기존 스킬이나 지침은 보존해줘. 설치 후 스킬을 읽고 학습 실행 없이 프로젝트를 점검해줘.

실제로 사용하는 에이전트와 소스·프로젝트 경로를 함께 전달하세요. 자동으로 스킬을 발견할 수 있는 환경에서는 AGENTS.md에 별도로 연결할 필요가 없습니다. 프로젝트별 상시 규칙은 기존 지침에서 유지합니다.

## 범위 선택과 미리보기

기본 `--scope project`는 지정 프로젝트만 대상으로 합니다. 여러 프로젝트에서 사용할 때는 사용자 범위를 명시합니다.

```sh
zar skill install --agent codex --scope user --dry-run --json
zar skill install --agent codex --scope user
```

사용자 범위는 Codex의 `~/.agents/skills/ziho-autoresearch/`, Claude Code의 `~/.claude/skills/ziho-autoresearch/`에 설치합니다. 이때 `--project`는 사용하지 않습니다. 기본 홈 위치만 지원하며 별도 에이전트 프로필이나 사용자 설정 경로를 자동 탐지하지 않습니다. 사용자 정의 경로는 기존 `--dest` 추출을 사용하세요.

`--dry-run`은 경로·충돌을 검사하고 미리보기를 반환하지만 파일을 쓰지 않습니다. 쓰기 권한이나 이후 에이전트 인식까지 검증하지 않으며 실제 설치 시 경로를 다시 검사합니다. `--scope`와 `--dry-run`은 `--agent`에만 사용할 수 있습니다. `--dest`와 `--agent`는 동시에 사용할 수 없습니다.

## 기존 설치와 업데이트

기존 목적지의 파일·폴더·심볼릭 링크가 있으면 충돌로 중단합니다. 에이전트 설정 폴더와 그 아래 skills 폴더가 심볼릭 링크나 Windows reparse point(junction 포함)인 경우도 따라가지 않습니다. 필요한 두 상위 폴더만 생성하며, 실패하면 이번 실행이 만든 빈 상위 폴더를 정리하고 기존 파일은 보존합니다. AGENTS.md, CLAUDE.md, 에이전트 설정, `.autoresearch/`는 수정하지 않습니다.

동일 이름의 스킬을 프로젝트와 사용자 범위에 중복 설치하면 선택이 혼동될 수 있으므로 필요한 한 범위를 선택하세요. CLI 업데이트로 기존 스킬이 갱신되지는 않습니다. 새 CLI에서 `zar skill install --dest <새 폴더>`로 추출해 차이를 확인하고, 기존 스킬을 발견 경로 밖에 백업한 뒤 원하는 범위로 다시 설치합니다. 자동 덮어쓰기·업데이트·제거 기능은 없습니다.

## 인식되지 않을 때

1. 출력된 설치 경로에 SKILL.md와 references가 있는지 확인합니다.
2. 에이전트에서 해당 ML 프로젝트를 열었는지 확인하고 스킬 목록을 갱신하거나 재시작합니다.
3. 스킬 비활성화, 프로젝트 신뢰 설정, 조직 정책, 다른 범위의 동일 이름 스킬을 확인합니다. 설치 명령은 이를 바꾸지 않습니다.
4. 에이전트의 터미널에서 `zar --help --json`을 확인합니다. 원격·컨테이너는 로컬 CLI와 홈 폴더를 공유하지 않을 수 있으므로 실제 실행 환경에 CLI와 스킬을 설치합니다.
5. 그래도 발견하지 못하면 설치된 SKILL.md의 절대 경로를 직접 전달합니다. 파일 읽기와 터미널 실행을 지원하지 않는 일반 채팅 환경은 지원 대상이 아닙니다.

설치 테스트는 경로, 파일 내용, 오류 처리와 실행 안내를 검증합니다. 실제 에이전트 세션에서 자동 발견·스킬 선택·ML 실행이 성공했다고 주장하지 않습니다.

## 설치 경로의 근거

2026-10-14 확인: [Codex 공식 스킬 문서](https://learn.chatgpt.com/docs/build-skills), [Claude Code 공식 스킬 문서](https://code.claude.com/docs/en/skills). 이 기능은 로컬 파일 기반 스킬 설치이며 마켓플레이스 등록·클라우드 계정 업로드는 수행하지 않습니다.
