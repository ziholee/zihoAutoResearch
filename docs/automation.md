# 문서 기반 구현 기준과 GitHub 자동화

제품 범위는 [제품 정의](product-direction.md), 파일·명령·완료 조건은 [v1 계약](cli-and-file-contract.md)이 기준이다. 자동화는 이 문서의 요구를 회귀 검사로 확인한다. 별도 점수나 임의 가중치로 구현 합격 여부를 판단하지 않는다.

## 계약과 검증의 연결

| 기준 | 자동 검사 | 리뷰에서 확인할 내용 |
| --- | --- | --- |
| 기존 에이전트가 연구 판단·실행, CLI는 기록·검사 담당 | `scripts/check_contract.py`: 런타임 의존성 없음; `tests/test_mock_cycle.py`: 학습 sentinel 미실행 | 새 실행기·LLM 호출·자동 가중치가 범위를 넓히지 않는가 |
| JSON 원본 보존, 원자적 저장, 상태 전이 | `tests/test_experiments.py`, `tests/test_records.py`, `tests/test_review_fixes.py` | 실패 후 원본과 선택 상태가 유지되는가 |
| 비교 조건·불명확한 근거·선택 분리 | `tests/test_comparisons.py`, `tests/test_reviews.py` | 숫자 개선만으로 유효성을 주장하지 않는가 |
| 제한된 재개 맥락과 원문 근거 조회 | `tests/test_context.py`, `tests/test_evidence.py` | [조회 계약](context-and-evidence.md)의 경고·페이지·스냅샷 의미를 유지하는가 |
| 실패 기억 원본·근거·조건·정정·폐기와 제한 재조회 | `tests/test_memories.py`, `tests/test_memory_core.py` | [실패 기억 계약](failure-memory.md)의 조건 일치와 실제 해결 검증을 혼동하지 않는가 |
| 후보 근거·선택 이유·예측과 관측 분리 | `tests/test_candidates.py`, `tests/test_candidate_core.py` | [후보 기록 계약](candidate-rationale.md)의 원본 버전·재평가·예산을 지키고 예측을 실측으로 오인하지 않는가 |
| 실험 부모·비교 기준·정정의 읽기 전용 계보 | `tests/test_lineage.py`, `tests/test_lineage_core.py` | [계보 계약](experiment-lineage.md)의 원본 참조·정정 집계를 보존하고 Git 조상·실행 횟수를 추론하지 않는가 |
| 제출 기록과 실제 외부 제출 분리 | `tests/test_submissions.py` | artifact identity와 correction 연결을 보존하는가 |
| 보고서 원본 필드·경로·덮어쓰기 계약 | `tests/test_reports.py` | [필드 매핑](report-field-mapping.md)에 없는 추론을 사실처럼 쓰지 않는가 |
| 깊은 계보의 참조 검증 비용과 기존 진단 의미 | `tests/test_validation_scale.py`: 작은 그래프 전수 대조, overlay·원본 보존, 깊은 계보의 작업 횟수 상한 | [성능 측정](record-scale-performance.md)의 조건·수치·남은 비용을 구분하는가 |
| 스킬의 독립 설치·원본 일치·덮어쓰기 거부 | `tests/test_skill_install.py`, `scripts/verify_package.py`: wheel/sdist/export 바이트와 로컬 링크 확인 | 프로젝트 기록이나 기존 스킬을 수정하지 않는가 |
| 공개 릴리스 파일만 PyPI로 전달 | `tests/test_release_assets.py`: 릴리스 상태·체크섬·소스 불일치 거부 | 활성화·환경 보호·OIDC 설정과 실제 업로드 검증을 구분하는가 |
| 설치된 CLI에서도 전체 모의 흐름 동작 | `scripts/verify_package.py`: wheel 설치 후 sdist 연구 예제 두 시나리오·실패 기억·후보 근거·계보·full/proxy 중단 재개 예제 | 실제 ML·비용·성능 검증과 혼동하지 않는가 |
| 문서·배포 지침 동기화 | `scripts/check_contract.py`: 로컬 링크, CLI 명령 언급, program 템플릿 일치, 스킬 기본 메타데이터 | 설명의 의미와 구현이 일치하는가 |

이 표는 주요 요구의 추적표이며 CI는 표의 일부 검사만 선택하지 않고 전체 unittest를 실행한다. 링크 검사는 파일 존재를 확인하며 Markdown anchor나 설명의 진위를 증명하지 않는다. 스킬 검사는 기본 필수 메타데이터만 검사하고 완전한 YAML/스킬 실행 검증을 대체하지 않는다.

## PR 검사와 머지 조건

[Contract CI](../.github/workflows/ci.yml)는 PR, dev/main push, merge group, 수동 실행 및 릴리스 재사용 호출에서 실행된다. 경로 필터 없이 문서 변경에도 같은 기준을 적용한다.

- Linux Python 3.11/3.14, Windows Python 3.14, macOS Python 3.14에서 전체 테스트 실행.
- Linux에서 문서 계약 검사와 wheel/sdist 빌드·격리 설치 검사.
- 모든 작업이 성공해야 `Contract gate` 성공. 실패·취소·건너뛴 선행 작업은 성공으로 처리하지 않는다.
- PR 워크플로는 읽기 권한만 사용하고 배포 비밀정보를 전달받지 않는다. Actions는 커밋 SHA로 고정한다.

저장소의 dev 보호 규칙에는 실제 성공한 `Contract gate`를 필수 상태 검사로 지정한다. 워크플로 파일만 추가한다고 보호 규칙이 자동 생성되지는 않는다. 설정 원본은 [dev 규칙 JSON](../.github/dev-ruleset.json)이다. PR 경유·대화 해결·최신 dev 기준 검사를 요구하고 강제 push·삭제를 막는다. 단독 유지관리자의 PR이 타인 승인 부재로 막히지 않도록 필수 승인 수는 0이며, 이는 AI 리뷰나 의미 검증 통과를 뜻하지 않는다. 자동 머지는 설정하지 않는다. 의미·설계·문서 불일치는 [PR 양식](../.github/pull_request_template.md)과 [리뷰 지침](../.github/copilot-instructions.md)을 따라 검토한다. 지침 파일 자체는 AI 리뷰 활성화가 아니며 Copilot 이용 권한과 별도 자동 리뷰 설정이 필요하다.

## 릴리스

최초 v0.1.0의 파일 구성·설치·체크섬 확인·초안 공개 절차는 [배포 안내](releasing.md), 사용자 변경 내역은 [CHANGELOG](../CHANGELOG.md)를 따른다.

[Draft release](../.github/workflows/release.yml)는 `v*` 태그에서 같은 CI를 통과한 뒤 태그가 `pyproject.toml` 버전과 일치하고 해당 커밋이 dev 이력에 포함되는지 확인한다. 최종 wheel/sdist를 다시 빌드·격리 검증하고 SHA256SUMS와 함께 GitHub **초안 릴리스**를 만든다. 유지관리자가 내용을 검토해 공개한다. Draft release 자체에는 PyPI 업로드, 서비스 배포 또는 외부 대회 제출이 없다. 검증 단계의 작은 합성 회귀 학습 예제를 제외한 사용자 모델 학습은 실행하지 않는다. 별도 [PyPI 발행 설정](pypi-publishing.md)은 공개된 정식 릴리스 첨부 파일을 검증한 후 OIDC로 발행한다. 기본 비활성 상태이며 신뢰 발행자·환경·활성화 변수 설정이 필요하다. 2026-10-13 KST에 v0.2.0의 실제 OIDC 발행·PyPI 파일 해시·격리 uv 설치·스킬 추출을 확인했다.

태그 생성·공개는 별도 릴리스 행위다. 워크플로 설정 검증만으로 실제 릴리스 성공을 주장하지 않는다. 빌드 도구는 개발 의존성이며 제품 런타임에는 추가되지 않는다.

## 로컬 재현

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_contract.py
python3 -m pip install build
python3 -m build
python3 scripts/verify_package.py --dist dist
```

Windows에서는 `python3` 대신 설치된 `python`을 사용한다. 테스트에서 플랫폼별로 지원하지 않는 권한 검사는 skip될 수 있으므로 작업 로그의 skip 사유도 확인한다. 실제 실행 결과와 남은 제한은 해당 PR과 CI에 남긴다. 내부 계획·승인 진단은 Git에서 제외한 로컬 `tasks/`에만 기록한다. 모의 검증은 실데이터 모델 선택·데이터 누수 판정·대표 성능·비용 절감을 입증하지 않는다.

## 적용 확인 — 2026-10-10

[PR #13](https://github.com/ziholee/zihoAutoResearch/pull/13)의 구현 커밋 `98b072d`에 대한 [GitHub 검사](https://github.com/ziholee/zihoAutoResearch/actions/runs/38060908959)가 모두 성공했다. Linux 3.11/3.14와 macOS 3.14는 각각 144개, Windows 3.14는 140개 성공·POSIX 전용 4개 skip이다. 설치 패키지의 모의 시나리오 두 개도 성공했다. 해시가 저장된 fixture는 `.gitattributes`로 checkout 줄바꿈 변환을 막고 원문 비교는 실제 바이트를 사용한다.

[dev 보호 규칙](https://github.com/ziholee/zihoAutoResearch/rules/24842957)은 활성화되었다. 이는 특정 커밋의 검증 기록이며 이후 PR은 새 검사 결과를 충족해야 한다. PR #13은 머지되었으며 워크플로는 기본 브랜치에 반영되었다. 실제 태그 릴리스와 AI 자동 리뷰 활성화는 아직 수행하지 않았다.

## 후속 구현 반영 — 2026-10-11

[PR #14](https://github.com/ziholee/zihoAutoResearch/pull/14)의 실패 기억과 [PR #15](https://github.com/ziholee/zihoAutoResearch/pull/15)의 후보 근거가 머지되어 관련 회귀 검사와 설치 예제가 추가되었다. 계보 조회 변경에서는 JSON·Mermaid 관계 표시, 원본 보존, 정정 중복 제외, 메타데이터 조회 범위를 검사하고 설치 패키지에서도 `examples/mock-lineage.py`를 실행한다. 위 PR #13의 검사 수는 당시 기록이며 현재 테스트 수를 뜻하지 않는다. 각 변경의 실제 실행 결과는 해당 PR과 CI를 기준으로 확인한다.

## 계보 통합 확인 — 2026-10-11

PR #16 머지 커밋 `784e35e`의 [dev CI](https://github.com/ziholee/zihoAutoResearch/actions/runs/38071425224)가 통과했다. 로컬 전체 테스트 196개와 설치 합성 시나리오 5개를 검증했으며, 계보까지 초기 기능 이슈가 모두 종료되었다. v0.1.0 배포 준비는 실제 태그 릴리스 성공을 뜻하지 않는다. 배포 검증은 wheel/sdist 메타데이터·라이선스·README·릴리스 문서 포함 여부도 검사한다.

## 공개 배포본 사용 경로 검증

[독립 검증 기록](public-onboarding-validation.md)과 [처음 사용·재개 안내](first-run-and-resume.md)를 따른다. `scripts/verify_package.py`는 설치된 CLI와 소스 배포본의 `examples/mock-resume.py`를 prepare/resume 별도 프로세스로 호출한다. 기존 5개에 full/proxy 재개 2개를 추가해 unknown 새 근거 요구, 변조 근거 진단, hold, 예산·선택·원본 보존을 확인한다. 실제 프로세스를 강제 종료하거나 학습하지 않는다.

## 합성 데이터의 실제 학습 예제

`tests/test_ml_loop.py`와 패키지 검증은 [ML 예제](ml-loop-example.md)의 기준 학습·후보 평가·안전한 경계에서의 중단과 별도 프로세스 재개를 확인한다. LLM만 모의이며 학습과 지표 계산은 실제로 실행한다. 기존 기록 전용 모의 예제와 구분하고, 실제 공급자 호환성·실데이터 일반화·사용자 효용 비교의 증거로 확대하지 않는다.

## 실제 CLI 장애 복구 통합 검증

`tests/test_crash_recovery.py`와 패키지 검증은 [장애 복구 예제](crash-recovery-validation.md)를 통해 실제 CLI 종료·새 CLI 조회·중복 실행 거부·새 근거 기반 복구를 확인한다. Linux/macOS의 프로세스 종료 확인 수단을 사용하며 Windows에서는 해당 통합 검사를 명시적으로 건너뛴다. 기존 플랫폼 공통 상태 전이·실행기 검사는 유지한다. 실제 API 호출이나 사용자의 학습 작업은 실행하지 않는다.
