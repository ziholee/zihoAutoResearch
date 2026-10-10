"""Deterministic, read-only Markdown rendering of canonical research records."""

from datetime import datetime
from hashlib import sha256
import re

from .codec import dumps
from .comparisons import compare


def _text(value):
    """Render data as inert table text, never executable Markdown or HTML."""
    if value is None:
        return '미기록'
    if not isinstance(value, str):
        value = dumps(value).rstrip('\n')
    # Encoding punctuation also protects fences, links, autolinks and table cells.
    return ''.join(char if char.isalnum() or char in ' ./:-=+,' else
                   '<br>' if char == '\n' else f'&#{ord(char)};' for char in value)


def _anchor(kind, identifier):
    return kind + '-' + sha256(identifier.encode('utf-8')).hexdigest()


def _reference(kind, identifier, records):
    if identifier is None:
        return '미기록'
    if identifier not in records[kind]:
        return _text(identifier) + ' (연결 원본 미기록)'
    return f'[{_text(identifier)}](#{_anchor(kind, identifier)})'


def _table(value, prefix=''):
    """Flatten without dropping empty containers, nulls or array positions."""
    rows = ['| JSON 경로 | 기록값 |', '|---|---|']

    def visit(item, path):
        if isinstance(item, dict) and item:
            for key, child in item.items():
                visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(item, list) and item:
            for index, child in enumerate(item):
                visit(child, path + '/' + str(index))
        else:
            rendered = _text(item)
            if path.endswith('/execution/status') and item == 'unknown':
                rendered = '상태 불명 (unknown)'
            rows.append(f'| {_text(path or "/")} | {rendered} |')

    visit(value, prefix)
    return '\n'.join(rows)


def _replacements(kind, group):
    result = {}
    for identifier, doc in group.items():
        previous = ((doc.get('correction') or {}).get('supersedes_id')
                    if kind == 'experiment' else doc.get('supersedes_id'))
        if previous:
            result.setdefault(previous, []).append(identifier)
    return {key: sorted(values) for key, values in result.items()}


def _elapsed(execution):
    start, finish = execution.get('started_at'), execution.get('finished_at')
    if start is None or finish is None:
        return '미기록'
    def parts(stamp):
        body = stamp.removesuffix('Z').removesuffix('+00:00')
        whole, _, fraction = body.partition('.')
        return datetime.fromisoformat(whole), fraction
    start_time, start_fraction = parts(start)
    end_time, end_fraction = parts(finish)
    delta = end_time - start_time
    places = max(len(start_fraction), len(end_fraction))
    scale = 10 ** places
    units = ((delta.days * 86400 + delta.seconds) * scale
             + int(end_fraction.ljust(places, '0') or '0')
             - int(start_fraction.ljust(places, '0') or '0'))
    sign = '-' if units < 0 else ''
    seconds, fractional = divmod(abs(units), scale)
    suffix = ('.' + str(fractional).zfill(places).rstrip('0')) if fractional else ''
    return f'{sign}{seconds}{suffix} 초'


def render_report(project, records, diagnostics, generated_at):
    """Render validated records; never read logs, mutate records or inspect Git.

    ``records`` is the review/experiment/submission mapping from RecordSnapshot.
    Diagnostics describe the caller's actual validation, not an inferred check.
    """
    replacements = {kind: _replacements(kind, group) for kind, group in records.items()}
    # Only the contract's safe ID alphabet can enter the machine marker.
    marker_id = project['id']
    if not re.fullmatch(r'[a-z0-9-]{1,64}', marker_id):
        raise ValueError('Invalid project ID for report marker')
    lines = [f'<!-- zar-report:v1 project_id={marker_id} -->',
             '# 연구 실험 보고서', '',
             f'생성 시각: {_text(generated_at)}. 생성 시각은 실행 관측 시각이 아닙니다.', '',
             'JSON 원본의 읽기용 보고서입니다. 배열 순서·정정 원본·정확한 숫자를 보존합니다. '
             'null 및 생략된 값은 미기록이며, 빈 배열/객체는 빈 기록으로 표시합니다. '
             '외부 문서·로그에서 사실을 추출하거나 현재 Git/프로세스 상태로 과거 사실을 보완하지 않습니다.', '',
             '## 현재 프로젝트와 선택', '',
             '출처: .autoresearch/project.json', '',
             '현재 기록상 선택: ' + _reference('experiment', project.get('selected_experiment_id'), records), '',
             '현재 프로젝트 다음 행동: ' + _text(project.get('next_action')), '',
             '현재 실제 작업 폴더 상태: 미기록. 기록상 선택은 실제 폴더 상태나 실행 당시 선택을 뜻하지 않습니다.', '']
    selected = records['experiment'].get(project.get('selected_experiment_id'))
    lines.extend(['선택 코드: ' + _text(selected.get('code_ref') if selected else None), '',
                  '선택 산출물 (원본 선택 ID 기준):', '',
                  _table(selected['execution']['artifacts'] if selected else None), '',
                  '### 프로젝트 원본 필드', '', _table(project), '',
                  '## 검증 진단과 한계', '',
                  '사용자 전달 근거는 독립 검증이 아닙니다. 해시 누락은 내용 일치 미확인이고, '
                  '파일 부재·해시 불일치 등 실제 검사 결과는 아래 진단을 따릅니다. '
                  '파일 검사는 근거의 의미적 진실성이나 과거 실행 일치를 보장하지 않습니다.', '',
                  _table(diagnostics) if diagnostics else '기록된 검증 진단 없음.', ''])

    for kind, title in (('experiment', '실험'), ('review', '점검'), ('submission', '제출')):
        group = records[kind]
        lines.extend([f'## {title} 기록', '', '활성 기록을 먼저 표시하며 대체된 원본도 보존합니다.', ''])
        if not group:
            lines.extend(['미기록', ''])
        for identifier in sorted(group, key=lambda key: (key in replacements[kind], key)):
            doc = group[identifier]
            replaced_by = replacements[kind].get(identifier, [])
            lines.extend([f'<a id="{_anchor(kind, identifier)}"></a>', '',
                          f'### {title}: {_text(identifier)}', '',
                          '출처: ' + _text(f'.autoresearch/{kind}s/{identifier}.json'), '',
                          ('대체됨: ' + ', '.join(_reference(kind, item, records) for item in replaced_by)
                           if replaced_by else '활성 기록 (대체 기록 없음)'), ''])
            if kind == 'experiment':
                execution = doc['execution']
                decision = doc.get('decision') or {}
                lines.extend(['가설과 예상 관측: ' + _text(doc.get('hypothesis')), '',
                              '부모: ' + _reference(kind, doc.get('parent_id'), records), '',
                              '비교 기준: ' + _reference(kind, doc.get('baseline_id'), records), '',
                              '실행 상태: ' + ('상태 불명 (unknown)' if execution['status'] == 'unknown' else _text(execution['status'])), '',
                              '기록된 경과 시간 (시각 차이로 파생, 자원 사용량 아님): ' + _elapsed(execution), '',
                              '실행 직전 코드 일치 판정: 미기록. code_ref는 기록된 식별자이며 실행 일치의 증명이 아닙니다.', '',
                              'command는 계획 명령입니다. 실제 실행·Git 밖 입력·과거 폴더 상태·보류 후보 위치는 '
                              'execution/decision의 근거·note/reason에 명시된 관측만 참조하며 별도 판정은 미기록입니다.', '',
                              '연결 점검 (기록된 ID 유지): ' + (', '.join(_reference('review', item, records) for item in doc['review_ids']) or '미기록'), '',
                              '실험 판단 당시 다음 행동: ' + _text(decision.get('next_action')), '',
                              '선택적 실행 조건 run_context:', '', _table(doc.get('run_context')), '',
                              '정정 correction:', '', _table(doc.get('correction')), ''])
                base = group.get(doc.get('baseline_id'))
                lines.extend(['#### 파생 비교 — 저장된 판단과 구분', '',
                              '기록된 조건에 compare 규칙을 적용한 결과입니다. 반복 통계는 명시적 confirmation '
                              '연결과 조건 일치에 한하며, mean/sample_variance는 정확한 분자·분모로 표시합니다. '
                              '실측 자원 사용량·실행 독립성은 추정하지 않습니다.', '',
                              _table(compare(base, doc, group)) if base else '미기록 (연결된 비교 기준 없음)', ''])
            elif kind == 'review':
                lines.extend(['점검 당시 코드·데이터를 기록합니다. 현재 상태와의 일치 및 최신성은 미확인입니다.', ''])
            else:
                original = records['experiment'].get(doc['experiment_id'])
                lines.extend(['연결 원본 실험: ' + _reference('experiment', doc['experiment_id'], records), '',
                              '연결 원본 코드: ' + _text(original.get('code_ref') if original else None), '',
                              '연결 원본 설정: ' + _text(original.get('config_ref') if original else None), '',
                              '연결 실험 대체 여부: ' + ('대체됨' if doc['experiment_id'] in replacements['experiment'] else '대체 기록 없음'), '',
                              '정정 끝점으로 연결을 이동하지 않습니다. 로컬 결과와 제출 결과의 차이에 대한 관측·해석은 '
                              '제출 evidence와 연결 실험 decision.evidence의 명시적 원문만 참조하며 인과관계는 미기록입니다.', ''])
            lines.extend(['#### 원본 필드와 근거', '', _table(doc), ''])
    return '\n'.join(lines).rstrip() + '\n'
