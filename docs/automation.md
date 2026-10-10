# 문서 기반 구현 기준과 GitHub 자동화

제품 범위는 [제품 정의](product-direction.md), 파일·명령·완료 조건은 [v1 계약](cli-and-file-contract.md)이 기준이다. 자동화는 이 문서의 요구를 회귀 검사로 확인한다. 별도 점수나 임의 가중치로 구현 합격 여부를 판단하지 않는다.

## 계약과 검증의 연결

| 기준 | 자동 검사 | 리뷰에서 확인할 내용 |
| --- | --- | --- |
| 기존 에이전트가 연구 판단·실행, CLI는 기록·검사 담당 | `scripts/check_contract.py`: 런타임 의존성 없음; `tests/test_mock_cycle.py`: 학습 sentinel 미실행 | 새 실행기·LLM 호출·자동 가중치가 범위를 넓히지 않는가 |
| JSON 원본 보존, 원자적 저장, 상태 전이 | `tests/test_experiments.py`, `tests/test_records.py`, `tests/test_review_fixes.py` | 실패 후 원본과 선택 상태가 유지되는가 |
| 비교 조건·불명확한 근거·선택 분리 | `tests/test_comparisons.py`, `tests/test_reviews.py` | 숫자 개선만으로 유효성을 주장하지 않는가 |
| 제한된 재개 맥락과 원문 근거 조회 | `tests/test_context.py`, `tests/test_evidence.py` | [조회 계약](context-and-evidence.md)의 경고·페이지·스냅샷 의미를 유지하는가 |
| 제출 기록과 실제 외부 제출 분리 | `tests/test_submissions.py` | artifact identity와 correction 연결을 보존하는가 |
| 보고서 원본 필드·경로·덮어쓰기 계약 | `tests/test_reports.py` | [필드 매핑](report-field-mapping.md)에 없는 추론을 사실처럼 쓰지 않는가 |
| 설치된 CLI에서도 전체 모의 흐름 동작 | `scripts/verify_package.py`: wheel 설치 후 sdist 예제 두 시나리오 | 실제 ML·비용·성능 검증과 혼동하지 않는가 |
| 문서·배포 지침 동기화 | `scripts/check_contract.py`: 로컬 링크, CLI 명령 언급, program 템플릿 일치, 스킬 기본 메타데이터 | 설명의 의미와 구현이 일치하는가 |

이 표는 주요 요구의 추적표이며 CI는 표의 일부 검사만 선택하지 않고 전체 unittest를 실행한다. 링크 검사는 파일 존재를 확인하며 Markdown anchor나 설명의 진위를 증명하지 않는다. 스킬 검사는 기본 필수 메타데이터만 검사하고 완전한 YAML/스킬 실행 검증을 대체하지 않는다.

## PR 검사와 머지 조건

[Contract CI](../.github/workflows/ci.yml)는 PR, dev/main push, merge group, 수동 실행 및 릴리스 재사용 호출에서 실행된다. 경로 필터 없이 문서 변경에도 같은 기준을 적용한다.

- Linux Python 3.11/3.14, Windows Python 3.14, macOS Python 3.14에서 전체 테스트 실행.
- Linux에서 문서 계약 검사와 wheel/sdist 빌드·격리 설치 검사.
- 모든 작업이 성공해야 `Contract gate` 성공. 실패·취소·건너뛴 선행 작업은 성공으로 처리하지 않는다.
- PR 워크플로는 읽기 권한만 사용하고 배포 비밀정보를 전달받지 않는다. Actions는 커밋 SHA로 고정한다.

저장소의 dev 보호 규칙에는 실제 성공한 `Contract gate`를 필수 상태 검사로 지정한다. 워크플로 파일만 추가한다고 보호 규칙이 자동 생성되지는 않는다. 자동 머지는 설정하지 않는다. 의미·설계·문서 불일치는 [PR 양식](../.github/pull_request_template.md)과 [리뷰 지침](../.github/copilot-instructions.md)을 따라 검토한다. 지침 파일 자체는 AI 리뷰 활성화가 아니며 Copilot 이용 권한과 별도 자동 리뷰 설정이 필요하다.

## 릴리스

[Draft release](../.github/workflows/release.yml)는 `v*` 태그에서 같은 CI를 통과한 뒤 태그가 `pyproject.toml` 버전과 일치하고 해당 커밋이 dev 이력에 포함되는지 확인한다. 최종 wheel/sdist를 다시 빌드·격리 검증하고 SHA256SUMS와 함께 GitHub **초안 릴리스**를 만든다. 유지관리자가 내용을 검토해 공개한다. 자동 PyPI 업로드, 서비스 배포, 모델 학습 또는 외부 대회 제출은 포함하지 않는다.

태그 생성·공개는 별도 릴리스 행위다. 워크플로 설정 검증만으로 실제 릴리스 성공을 주장하지 않는다. 빌드 도구는 개발 의존성이며 제품 런타임에는 추가되지 않는다.

## 로컬 재현

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_contract.py
python3 -m pip install build
python3 -m build
python3 scripts/verify_package.py --dist dist
```

Windows에서는 `python3` 대신 설치된 `python`을 사용한다. 테스트에서 플랫폼별로 지원하지 않는 권한 검사는 skip될 수 있으므로 작업 로그의 skip 사유도 확인한다. 실제 실행 결과와 남은 제한은 [작업 기록](../tasks/todo.md)에 남긴다. 모의 검증은 실데이터 모델 선택·데이터 누수 판정·대표 성능·비용 절감을 입증하지 않는다.
