# 실패 기억: 원본·조건·근거의 보존

갱신: 2026-10-11 · [v1 계약](cli-and-file-contract.md) · [맥락·근거 조회](context-and-evidence.md)

실패 기억은 작성자가 확인한 실패 관측과 원인 설명·대응·적용 한계를 원본 실험에 연결하는 불변 JSON입니다. 자동 원인 분석, 해결책 생성, LLM 호출, 재실행을 하지 않습니다. 선언 조건이 같거나 성공한 해결 실험이 연결되었다는 사실만으로 인과관계·일반성·현재 작업 폴더 상태를 검증하지 않습니다.

## 기록 입력

```sh
zar memory add --project /path/to/project --file memory-draft.json --json
zar context --project /path/to/project --memories --experiment exp-candidate --json
zar evidence read --project /path/to/project --kind memory --id memory-failure-1 --pointer /evidence/0 --revision 1 --json
```

memory add 입력에는 아래 필드만 넣습니다. 예시 ID와 설명을 실제 관측으로 바꾸며 존재하지 않는 실험·근거를 만들어내지 않습니다.

| 필드 | 의미 |
|---|---|
| id | 새 기억 ID |
| supersedes_id | 정정·폐기할 기억 ID 또는 새 계보이면 null |
| status | active 또는 retired |
| cause | 비어 있지 않은 작성자의 실패 원인 설명 |
| remedy | 작성자의 대응 설명 또는 null. 활성 기억에 해결 실험을 연결하면 필수 |
| limitation | 비어 있지 않은 적용 한계·미확인 사항 |
| evidence | 비어 있지 않은 Evidence 배열. 원본 실패 근거를 최소 1개 그대로 보존 |
| failure_experiment_id | 실패·중단 또는 현재/과거 decision_history에 폐기 판단이 있는 원본 실험 |
| resolution_experiment_id | 성공한 별도 해결 실험 ID 또는 null. 지정하면 그 실행 근거도 최소 1개 그대로 보존 |

CLI가 schema_version/revision=1, created_at/updated_at과 conditions를 생성합니다. conditions는 실패 실험의 environment/comparison/code_ref/config_ref 사본입니다. 현재 프로젝트 설정이나 해결 실험의 조건을 실패 당시 값으로 쓰지 않습니다. 해결 실험은 실패와 선언된 환경·비교 조건 및 알려진 실행 범위·예산 조건이 맞아야 합니다. 코드·설정 변화 자체는 복구 작업일 수 있으므로 허용하며 seed 차이도 해결 연결을 막지 않습니다. 과거 discard 근거는 이후 hold/keep으로 재판정되어도 기억의 근거로 보존됩니다. 미확인 조건은 검증된 일치로 승격하지 않습니다. Evidence의 kind/ref/locator/sha256 계약과 전체 근거 검사는 기존 기록과 같습니다.

## 정정과 폐기

`.autoresearch/memories/<id>.json`은 생성 후 수정하지 않습니다. 정정은 활성 끝점을 supersedes_id로 가리키는 새 active 기록을 추가합니다. 실패 실험 ID와 조건은 유지하고 설명·대응·한계·해결 연결을 근거에 맞게 정정합니다. 폐기는 같은 방식으로 새 retired 기록을 추가하고 cause/limitation에 폐기 이유와 한계를 남깁니다. retired는 계보의 종점이며 후속 정정·재활성화는 거부됩니다. 분기·순환·중복 ID도 거부됩니다.

원본 기억과 실험은 보존합니다. 실험 관측이 나중에 정정되더라도 기억의 참조 ID를 정정 끝점으로 자동 변경하지 않습니다. 원본 대체 경고와 context의 stale_source를 확인하고 관측을 재평가합니다. 잘못된 원인 설명을 폐기하더라도 실패 기록 자체를 삭제하지 않습니다.

## 제한된 재조회

기본 context는 기억이 있을 때 total/active/retired/superseded 집계와 별도 조회 안내를 제공합니다. `--memories`는 대체되지 않은 active 기억만 카드로 제공합니다. 전체 applicability는 matched → unknown → mismatch 순이며 같은 그룹에서 created_at·ID 역순입니다. 조건 대조는 강조 실험 또는 현재 선택에 기록된 환경·비교·코드·설정·run_context를 사용합니다. 알려진 불일치 또는 대체된 원본 참조는 mismatch, 정보 부족은 unknown입니다. 해결 실험의 scope/budget이 미기록이면 resolution_scope는 unknown이며, 다른 알려진 불일치가 없을 때 전체 applicability도 unknown입니다. 일부 필드가 미기록이어도 다른 필드의 알려진 불일치는 mismatch로 유지합니다. 강조 실험과의 run_context 대조는 seed까지 포함하며 해결 연결의 scope/budget 검사와 구분합니다.

카드의 resolution_state는 recorded/unresolved이며 verified 상태는 없습니다. evidence_checked와 workspace_verified는 false입니다. 긴 설명은 160문자 미리보기, 근거는 최대 3개 핸들과 누락 수로 표시합니다. 전체 원문·해결 근거·한계는 source와 evidence read로 확인합니다. 일반 context와 동일한 limit/offset/max-bytes/snapshot 계약이며 전체 JSON envelope 바이트 상한을 지킵니다. 페이지 종류를 바꾸면 offset 0에서 시작합니다. 출력 제한은 원본 삭제나 중요성 판정이 아닙니다.

## 호환성과 검증 범위

기존 프로젝트에 memories 폴더가 없어도 읽기·검사할 수 있으며 자동 마이그레이션하지 않습니다. 새 init은 폴더를 준비하고 첫 memory add는 필요한 폴더를 생성합니다. 기존 program.md는 덮어쓰지 않습니다. 새 지침이 필요한 기존 프로젝트는 소유한 지침에 이 절차를 반영합니다. 구버전 CLI가 확장을 완전히 검사한다고 가정하지 말고 memory 명령을 지원하는 버전으로 관리합니다.

보고서는 기억의 원본 필드·근거·정정 계보와 retired 기록도 표시합니다. 회귀 검증은 모의 실험으로 입력·참조·조건 검사, 원본 보존, 정정·폐기, 제한 조회·페이지·근거 재조회를 확인합니다. 실제 실패 복구 성공률, 비용 절감, ML 타당성은 별도 실험 전 주장하지 않습니다.

설치된 CLI로 실패 기억의 모의 전체 흐름을 재현하려면 저장소 또는 소스 배포본에서 실행합니다. 출력 경로는 존재하지 않아야 하며 상위 폴더는 존재해야 합니다. Windows에서는 해당 환경의 임시 경로를 지정합니다.

```sh
python examples/mock-memory.py --output /tmp/zar-mock-memory
```

예제는 합성 실패·해결 관측으로 등록 → 재조회·근거 해시 확인 → 정정 → 폐기 → 보고서·검사를 수행하고 원본 보존·학습 미실행을 확인합니다. 실제 모델 학습이나 인과 검증은 하지 않습니다.
