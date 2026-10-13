# uv로 설치·업데이트하고 스킬 사용하기

아래 고정 버전·wheel URL 예시는 v0.3.0 기준입니다. 배포 파일과 공개 상태는 [PyPI](https://pypi.org/project/ziho-autoresearch/)와 [GitHub Release](https://github.com/ziholee/zihoAutoResearch/releases)에서 확인합니다. uv는 설치·환경 관리 도구이며 zar의 런타임 의존성은 아닙니다. Python 3.11 이상이 필요합니다.

## GitHub wheel 설치

[uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 준비한 뒤 실행합니다.

```sh
uv tool install https://github.com/ziholee/zihoAutoResearch/releases/download/v0.3.0/ziho_autoresearch-0.3.0-py3-none-any.whl
zar --help
uv tool list
```

CLI 경로가 PATH에 없다는 안내가 나오면 `uv tool update-shell`을 실행하고 터미널을 다시 여세요. 사용 중인 ML 프로젝트의 가상환경에 라이브러리를 추가할 필요는 없습니다. 사전에 파일을 내려받아 체크섬을 확인하려면 [배포 파일 검증 안내](releasing.md)를 따른 뒤 `uv tool install ./ziho_autoresearch-0.3.0-py3-none-any.whl`로 설치합니다.

v0.3.0 wheel에는 스킬과 설치 명령이 포함됩니다. 고정 wheel URL로 설치한 도구는 `uv tool upgrade`만으로 다른 릴리스 URL이나 PyPI 설치로 바뀌지 않습니다. 새 버전의 URL을 명시하거나 아래 PyPI 설치 방식으로 전환하세요.

## PyPI 설치·업데이트

유지관리자의 배포 절차는 [PyPI 배포 설정](pypi-publishing.md)을 참고하세요. 패키지명은 `ziho-autoresearch`, 실행 명령은 `zar`입니다.

```sh
# 최초 설치 / 이후 업데이트
uv tool install ziho-autoresearch
uv tool upgrade ziho-autoresearch

# 한 버전에 고정 설치
uv tool install 'ziho-autoresearch==0.3.0'

# 일회성 격리 실행 (패키지와 명령 이름이 다르므로 --from 지정)
uvx --from 'ziho-autoresearch==0.3.0' zar --help
```

고정 버전으로 설치하면 upgrade도 그 제약을 지킵니다. 기존 고정 버전이나 URL 설치를 최신 PyPI 패키지로 전환할 때는 `uv tool install --force ziho-autoresearch`를 명시적으로 사용합니다. CLI 설치 버전은 `uv tool list`로 확인하고 제거는 `uv tool uninstall ziho-autoresearch`로 수행합니다.

## 에이전트 발견 경로에 설치

v0.3.0부터 `zar skill install --agent codex` 또는 `zar skill install --agent claude`로 프로젝트 스킬 폴더에 설치할 수 있습니다. 사용자 범위·미리보기·호출·업데이트 절차는 [에이전트 설치 안내](agent-installation.md)를 참고하세요. 이전 버전이나 다른 에이전트는 다음 수동 추출 방식을 사용합니다.

## 스킬을 지정 폴더에 설치

이 명령은 0.2.0부터 지원하며, 설치한 CLI와 같은 버전의 스킬을 추출합니다. PyPI 설치에서도 같은 명령을 사용할 수 있습니다. wheel에 스킬과 references 전체가 포함되므로 소스 배포본을 별도로 풀 필요가 없습니다.

```sh
zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json
```

`--dest`는 스킬 파일이 들어갈 **새 폴더 자체**입니다. 상위 폴더는 미리 존재해야 합니다. 이미 존재하는 파일·폴더·심볼릭 링크는 덮어쓰지 않습니다. ML 프로젝트의 초기화 없이 실행할 수 있으며 프로젝트 기록이나 에이전트의 전역 설정을 바꾸지 않습니다.

반환된 폴더의 `SKILL.md` 절대 경로를 에이전트에 알려주세요.

> `/absolute/path/to/ziho-autoresearch-skill-0.3.0/SKILL.md`를 읽고 `/absolute/path/to/ml-project`를 점검해줘. 우선 실행 없이 프로젝트 해석과 누락 정보를 정리해줘.

CLI 업데이트는 이미 복사한 스킬을 수정하지 않습니다. 업데이트 후에는 새 폴더에 스킬을 설치하고 차이를 확인한 뒤 에이전트가 읽을 경로를 바꾸세요. 기존 스킬에 적용한 사용자 수정도 자동으로 병합하거나 삭제하지 않습니다. 에이전트별 자동 검색·등록 방식은 별도이므로 이 명령의 성공을 자동 등록 완료로 해석하지 않습니다.

uv의 설치·격리·업데이트·버전 고정 의미는 [공식 도구 가이드](https://docs.astral.sh/uv/guides/tools/)를 기준으로 합니다.


## 프로젝트 지침에 연결

`SKILL.md`는 재사용할 실험 절차, 대상 ML 프로젝트의 `AGENTS.md`는 적용 조건과 프로젝트 규칙, `.autoresearch/program.md`는 프로젝트 해석을 담습니다. 도구 개발 저장소의 지침을 사용자 프로젝트에 그대로 복사하지 마세요. 지침 파일을 읽는 방식은 에이전트마다 다르며, 파일을 추가하는 것만으로 자동 등록이나 실행 권한이 생기지는 않습니다.

아래 예시를 기존 프로젝트 지침에 수동 병합할 수 있습니다. 경로는 실제 추출한 스킬의 경로로 바꾸세요.

```markdown
## ML 실험 관리

- 실험 계획·실행·기록·재개 시 `/absolute/path/to/skill/SKILL.md`를 읽고 프로젝트 규칙과 함께 따른다.
- 대상 프로젝트에서 zar context --json과 zar status --json을 확인하고 실제 작업 상태도 점검한다.
- unknown 실험은 실제 프로세스·로그로 상태를 확인하기 전 재실행하지 않는다.
- 사용자가 허용한 변경 경로·환경·횟수·시간 한도를 지킨다. 스킬 연결만으로 학습이나 외부 제출을 승인하지 않는다.
- 중요한 판단에 기록된 근거를 사용하기 전 zar check --json을 실행한다. 형식 검증은 ML 타당성 검증을 대신하지 않는다.
```

### 연결 문구 생성 명령

`zar skill guidance`는 v0.3.0부터 지원합니다.

```sh
zar skill guidance --skill-dir ./ziho-autoresearch-skill-0.3.0
zar skill guidance --skill-dir ./ziho-autoresearch-skill-0.3.0 --json
```

`--skill-dir`는 이미 추출한 스킬 폴더이며 상대 경로는 현재 작업 폴더 기준입니다. `~`를 확장한 절대 `SKILL.md` 경로로 문구를 만듭니다. 파일 존재만 확인하며 스킬 내용의 신뢰성·버전 일치·에이전트 호환성을 검증하지 않습니다. 경로의 공백·한글·백틱은 출력에서 보존하고 제어 문자가 있는 경로는 거절합니다.

기본 출력은 병합할 Markdown이며 JSON 결과의 `data`에는 `view: "skill_guidance"`, `skill_file`, `markdown`이 있습니다. 이 명령은 프로젝트 초기화 없이 동작하며 `--project`를 읽거나 수정하지 않습니다. 어떤 파일도 쓰지 않고 에이전트 설정도 바꾸지 않습니다. 출력은 화면에서 검토한 뒤 기존 `AGENTS.md`에 병합하세요. `> AGENTS.md`는 셸에 의한 덮어쓰기를 일으킬 수 있습니다.

생성 문구는 로컬 절대 경로를 포함합니다. 공유 저장소에 올릴 때는 개인 경로 공개 여부와 다른 사용자의 접근 가능성을 확인하고, 팀에서 합의한 경로로 조정하세요. 스킬을 이동하거나 업데이트하면 연결 경로도 수정합니다. 원본 절차는 `SKILL.md`에서 관리하고 프로젝트 지침에는 연결만 유지합니다.
