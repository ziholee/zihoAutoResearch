# uv로 설치·업데이트하고 스킬 사용하기

현재 공개 버전은 GitHub Release의 v0.1.1입니다. **0.2.0과 PyPI 배포는 아직 공개하지 않았습니다.** 아래에서 현재 사용 가능한 설치와 향후 PyPI 공개 후 사용을 구분합니다. uv는 설치·환경 관리 도구이며 zar의 런타임 의존성은 아닙니다. Python 3.11 이상이 필요합니다.

## 현재: 공개 GitHub wheel 설치

[uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 준비한 뒤 실행합니다.

```sh
uv tool install https://github.com/ziholee/zihoAutoResearch/releases/download/v0.1.1/ziho_autoresearch-0.1.1-py3-none-any.whl
zar --help
uv tool list
```

CLI 경로가 PATH에 없다는 안내가 나오면 `uv tool update-shell`을 실행하고 터미널을 다시 여세요. 사용 중인 ML 프로젝트의 가상환경에 라이브러리를 추가할 필요는 없습니다. 사전에 파일을 내려받아 체크섬을 확인하려면 [배포 파일 검증 안내](releasing.md)를 따른 뒤 `uv tool install ./ziho_autoresearch-0.1.1-py3-none-any.whl`로 설치합니다.

v0.1.1의 wheel에는 스킬 설치 명령이 없으므로 같은 릴리스의 소스 배포본에서 `skills/ziho-autoresearch/` 전체 폴더를 사용합니다. 고정 wheel URL로 설치한 도구는 `uv tool upgrade`만으로 다른 릴리스 URL이나 PyPI 설치로 바뀌지 않습니다. 새 버전의 URL을 명시하거나 아래 PyPI 설치 방식으로 전환하세요.

## 향후: PyPI 공개 확인 후

[PyPI 배포 설정](pypi-publishing.md)을 완료하고 해당 버전의 실제 공개를 확인한 후에만 사용합니다. 패키지명은 `ziho-autoresearch`, 실행 명령은 `zar`입니다.

```sh
# 최초 설치 / 이후 업데이트
uv tool install ziho-autoresearch
uv tool upgrade ziho-autoresearch

# 한 버전에 고정 설치
uv tool install 'ziho-autoresearch==0.2.0'

# 일회성 격리 실행 (패키지와 명령 이름이 다르므로 --from 지정)
uvx --from 'ziho-autoresearch==0.2.0' zar --help
```

고정 버전으로 설치하면 upgrade도 그 제약을 지킵니다. 기존 고정 버전이나 URL 설치를 최신 PyPI 패키지로 전환할 때는 `uv tool install --force ziho-autoresearch`를 명시적으로 사용합니다. CLI 설치 버전은 `uv tool list`로 확인하고 제거는 `uv tool uninstall ziho-autoresearch`로 수행합니다.

## 0.2.0 개발본: 스킬을 지정 폴더에 설치

이 명령은 0.2.0 개발 wheel 또는 이 변경이 포함된 소스 설치에서 사용할 수 있습니다. PyPI에 공개됐다고 가정하지 않습니다. wheel에 스킬과 references 전체가 포함되므로 소스 배포본을 별도로 풀 필요가 없습니다.

```sh
zar skill install --dest ./ziho-autoresearch-skill-0.2.0 --json
```

`--dest`는 스킬 파일이 들어갈 **새 폴더 자체**입니다. 상위 폴더는 미리 존재해야 합니다. 이미 존재하는 파일·폴더·심볼릭 링크는 덮어쓰지 않습니다. ML 프로젝트의 초기화 없이 실행할 수 있으며 프로젝트 기록이나 에이전트의 전역 설정을 바꾸지 않습니다.

반환된 폴더의 `SKILL.md` 절대 경로를 에이전트에 알려주세요.

> `/absolute/path/to/ziho-autoresearch-skill-0.2.0/SKILL.md`를 읽고 `/absolute/path/to/ml-project`를 점검해줘. 우선 실행 없이 프로젝트 해석과 누락 정보를 정리해줘.

CLI 업데이트는 이미 복사한 스킬을 수정하지 않습니다. 업데이트 후에는 새 폴더에 스킬을 설치하고 차이를 확인한 뒤 에이전트가 읽을 경로를 바꾸세요. 기존 스킬에 적용한 사용자 수정도 자동으로 병합하거나 삭제하지 않습니다. 에이전트별 자동 검색·등록 방식은 별도이므로 이 명령의 성공을 자동 등록 완료로 해석하지 않습니다.

uv의 설치·격리·업데이트·버전 고정 의미는 [공식 도구 가이드](https://docs.astral.sh/uv/guides/tools/)를 기준으로 합니다.
