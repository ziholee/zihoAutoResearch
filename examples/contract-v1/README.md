# v1 계약 예제

모든 값·로그·제출 결과는 모의 데이터입니다. 실제 ML 학습이나 외부 제출을 수행하지 않았습니다. train.py와 python 명령은 기록 예시이며 이 폴더에서 실행할 명령이 아닙니다.

- [project.json](project.json): 설정과 현재 선택한 기준
- [review.json](review.json): 제한된 범위의 모의 점검 근거
- [baseline.json](baseline.json): 성공한 기준과 keep 판단
- [candidate.json](candidate.json): 더 낮은 모의 RMSE와 hold 판단
- [submission.json](submission.json): 후보 파일과 연결된 모의 public 점수

이 파일들은 **저장 완료 형태의 예제**입니다. 생성 명령의 입력 형식은 [CLI 계약](../../docs/cli-and-file-contract.md)을 따릅니다. 생성 입력에서는 CLI가 채우는 schema_version/revision/created_at/updated_at과 생성 전용 기본값을 제외합니다. 수정 입력은 현재 저장된 파일을 읽어 revision을 유지한 수정본을 제공합니다.

예제의 경로 기준은 이 폴더입니다. CLI의 실제 저장 배치에서는 JSON이 .autoresearch 하위에 들어가도 근거 경로는 프로젝트 루트 기준입니다. logs/와 submission-example.txt는 이 모의 프로젝트의 근거 파일입니다.

기대 해석: 로컬 RMSE는 1.2 → 1.1로 개선 폭 약 0.1이지만 자동 채택하지 않습니다. 현재 선택은 exp-baseline이고 후보는 hold입니다. 제출 점수 1.15는 로컬 점수와 따로 표시합니다. 이 예제는 CLI 실행 테스트 결과가 아닙니다.

revision 예시: 기준은 create(1) → 결과 update(2) → decide(3), 후보는 이 과정 후 제출 artifact 추가 update(4)입니다. 제출의 submitted_at/observed_at은 생성 입력에 포함합니다.
