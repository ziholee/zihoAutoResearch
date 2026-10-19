# v0.3.0 설치와 배포

아래 설치 예시는 v0.3.0 배포 파일 기준입니다. 실제 공개 상태와 검증 결과는 [GitHub 릴리스](https://github.com/ziholee/zihoAutoResearch/releases/tag/v0.3.0)에서 확인합니다. [변경 내역](../CHANGELOG.md), [자동화 계약](automation.md), [공개 파일 점검](public-content-audit.md)을 함께 확인합니다. 내부 계획·승인 진단·교훈은 Git에서 제외한 로컬 `tasks/`에만 기록하고, 공개 검증 근거는 PR·CI와 사용자 문서에 남깁니다.

## 배포 형태

| 파일 | 포함 내용 |
|---|---|
| ziho_autoresearch-0.3.0-py3-none-any.whl | CLI, program 템플릿, 스킬과 references, 패키지 메타데이터, LICENSE |
| ziho_autoresearch-0.3.0.tar.gz | CLI 소스, 스킬과 references, 문서, 예제, 템플릿, CHANGELOG, LICENSE |
| SHA256SUMS | 위 두 배포 파일의 SHA-256; 릴리스 워크플로가 생성 |

GitHub가 자동 제공하는 Source code 압축파일과 워크플로가 빌드해 첨부한 `.tar.gz`는 구분합니다. 아래 절차에는 릴리스 첨부 파일을 사용합니다. 공개 완료 후 GitHub Release와 [PyPI](https://pypi.org/project/ziho-autoresearch/)에서 설치할 수 있습니다. [uv 설치 안내](uv-installation.md)와 [PyPI 자동화 설정](pypi-publishing.md)을 참고하세요. v0.3.0 wheel에는 스킬과 references도 포함됩니다.

Python 3.11 이상이 필요합니다. CLI 런타임 의존성은 없습니다. `git status`, `experiment create --git-head` 및 Git 계보 모의 예제에는 Git 실행 파일이 필요합니다. Mermaid 출력의 렌더링은 별도 도구가 담당합니다.

## 내려받은 패키지 확인과 설치

공개 후 동일한 릴리스에서 wheel, 소스 배포본, SHA256SUMS를 내려받아 빈 작업 폴더에 둡니다. 그 폴더에서 다음 Python 코드로 두 파일의 체크섬을 확인합니다. 저장한 해시는 파일 일치 확인이며 서명이나 독립적인 출처 인증은 아닙니다.

```python
from hashlib import sha256
from pathlib import Path

expected_names = {
    "ziho_autoresearch-0.3.0-py3-none-any.whl",
    "ziho_autoresearch-0.3.0.tar.gz",
}
seen = set()
for line in Path("SHA256SUMS").read_text(encoding="utf-8").splitlines():
    expected, name = line.split("  ", 1)
    if name not in expected_names or name in seen:
        raise SystemExit("Unexpected checksum entry: " + name)
    seen.add(name)
    if sha256(Path(name).read_bytes()).hexdigest() != expected:
        raise SystemExit("Checksum mismatch: " + name)
if seen != expected_names:
    raise SystemExit("Missing checksum entries")
print("Both release files match SHA256SUMS")
```

가상환경 생성·활성화 후 wheel을 설치합니다. Windows에서 `python`이 Python 3.11 이상을 가리키는지 확인합니다.

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --no-index --no-deps ./ziho_autoresearch-0.3.0-py3-none-any.whl
python -m pip show ziho-autoresearch
zar --help
```

`zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json`으로 스킬을 새 폴더에 추출합니다. 소스 배포본의 `skills/ziho-autoresearch/` 폴더 전체를 직접 사용해도 됩니다. wheel 설치만으로 스킬이 에이전트에 자동 등록되지는 않습니다. `zar skill install --agent codex --project <ML 프로젝트>` 또는 `--agent claude`로 발견 경로에 설치할 수도 있습니다. 수동 추출한 경우 에이전트에 해당 `SKILL.md`의 절대 경로와 대상 ML 프로젝트 경로를 알려줍니다. 스킬 사용법은 [README](../README.md)의 안내를 따릅니다.

압축 해제한 소스 폴더에서 `python examples/mock-cycle.py --output <새 출력 경로>`로 학습 없이 기록 흐름을 확인할 수 있습니다. 출력 경로는 기존 상위 폴더 아래의 존재하지 않는 경로여야 합니다. 소스 자체를 설치하려면 `python -m pip install .`을 사용할 수 있지만, 이때 빌드용 setuptools를 준비해야 합니다. 일반 사용자는 검증된 wheel을 우선 사용합니다.

## 유지관리자: 배포 전 게이트

1. 배포 준비 PR을 dev에 머지하고 해당 커밋의 Contract CI 성공을 확인합니다. 이전 PR의 통과만으로 새 배포 커밋을 승인하지 않습니다.
2. [변경 내역](../CHANGELOG.md)의 준비 중 표시를 실제 배포 상태에 맞게 갱신합니다. 이 최종 문서 변경도 PR과 CI를 거쳐 dev에 통합하고 해당 최종 커밋의 성공을 확인합니다. 기능 변경과 함께 태그를 만들지 않고 검증된 커밋을 지정합니다.
3. `pyproject.toml`의 현재 버전과 새 태그 `v<version>`이 일치하고 그 태그가 아직 없는지 확인합니다. 일반 배포에서는 기존 태그를 이동하거나 강제 푸시하지 않습니다. 개인정보 제거를 위해 승인된 이력 재작성은 별도 백업·참조 검증·기존 clone 안내를 포함하는 유지관리 작업입니다.
4. 새 출력 디렉터리에 wheel/sdist를 빌드하고 `python scripts/verify_package.py --dist <빌드 디렉터리>`를 실행합니다. 라이선스·메타데이터·문서 포함 및 설치된 CLI의 합성 시나리오를 확인합니다. 설치 검증에는 기존 5개와 별도 프로세스 재개 2개의 합성 기록 시나리오, 모의 LLM을 사용하는 실제 합성 회귀 학습·평가·재개 예제를 포함합니다. Linux/macOS에서는 실제 CLI 종료와 근거 기반 장애 복구 예제도 실행합니다. 동일 조건의 직접 실행+Git/zar 비교도 한 쌍 실행해 산출물을 검사하며 시간 우위는 요구하지 않습니다.
5. 실제 태그 생성과 공개를 진행할 때는 유지관리자의 실행 승인을 기준으로 합니다. 이 배포 준비 작업 자체는 태그·릴리스를 만들지 않습니다.

## 태그부터 초안 공개까지

승인 후 확정된 dev 커밋에 해당 버전의 새 태그를 만들어 원격에 푸시합니다. [Draft release 워크플로](../.github/workflows/release.yml)는 같은 Contract CI를 다시 실행하고 다음을 수행합니다.

- 태그와 패키지 버전 일치, 태그 커밋의 dev 포함 여부 확인.
- wheel/sdist 빌드와 격리 설치 검증.
- SHA256SUMS 생성 후 세 파일을 GitHub 초안 릴리스에 첨부.

유지관리자는 생성된 초안의 변경 내역과 세 첨부 파일을 확인합니다. 자동 생성 노트에 [CHANGELOG](../CHANGELOG.md)의 기능·설치 방법·한계를 반영하고 공개합니다. Draft release 워크플로는 자동 공개나 PyPI 업로드를 하지 않습니다. 별도 PyPI 워크플로는 명시적 활성화와 신뢰 발행자 설정 이후 정식 릴리스 공개 시 검증된 첨부 파일을 올립니다. v0.2.0은 실제 발행까지 확인했으며, 새 버전도 업로드 성공과 설치 검증을 별도로 확인합니다.

실패하면 실행 로그와 태그/버전/권한을 먼저 확인합니다. 태그가 이미 있거나 초안이 일부 생성된 상태에서 맹목적으로 재실행하지 말고 기존 결과를 확인합니다. 검증 전 파일을 수동 공개하거나 기존 태그를 새 코드로 덮어쓰지 않습니다.

## 라이선스와 검증 한계

프로젝트는 [MIT License](../LICENSE)를 채택합니다. 짧은 고지 조건으로 사용·수정·배포할 수 있어 기존 프로젝트에 가볍게 도입하는 목적에 맞습니다. 표준 조건은 [OSI MIT 원문](https://opensource.org/license/mit)을 따릅니다. 참고 연구와 저장소 링크는 설계 근거이며, 그 자료의 코드나 데이터에 이 라이선스를 다시 적용하는 것은 아닙니다.

현재 문서·소스의 표기 검사에서 별도 vendored 코드나 타사 저작권 고지는 발견하지 않았습니다. 이는 외부 코드와의 전수 유사도 검사 또는 모든 권리의 인증은 아닙니다. 향후 외부 코드를 포함하면 출처와 해당 고지 조건을 별도로 검토합니다.

합성 검증과 CI는 소프트웨어 계약의 확인입니다. 실제 ML 품질·데이터 누수 판단·비용 절감·과거 실행 진실성은 이번 릴리스에서 입증한 결과가 아닙니다. 전체 이력 로딩과 report/lineage 출력은 크기 제한이 없으며, 재개 입력에는 제한된 context를 사용합니다.
