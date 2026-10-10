"""Pure projections of recorded experiment ancestry; never inspect Git or run code."""
from collections import Counter, deque


def build_lineage(project, records):
    """Build a deterministic graph from schema-valid canonical documents.

    Execution identities include planned and cancelled records. Corrections revise
    one identity rather than creating another execution. A status is an author's
    recorded observation, not independently verified execution evidence.
    """
    experiments = records['experiment']
    corrected_by = {}
    edges = []
    children = {identifier:set() for identifier in experiments}
    indegree = dict.fromkeys(experiments, 0)
    selected = project.get('selected_experiment_id')
    if selected is not None and selected not in experiments:
        raise ValueError(f'Missing selected experiment: {selected}')
    for identifier in sorted(experiments):
        doc = experiments[identifier]
        previous = (doc.get('correction') or {}).get('supersedes_id')
        for edge_type, ancestor in (('parent', doc['parent_id']),
                                    ('baseline', doc['baseline_id']), ('correction', previous)):
            if ancestor is None:
                continue
            if ancestor not in experiments:
                raise ValueError(f'Missing {edge_type} experiment {ancestor} referenced by {identifier}')
            if edge_type == 'correction':
                if ancestor in corrected_by:
                    raise ValueError(f'Ambiguous correction successors for {ancestor}')
                corrected_by[ancestor] = identifier
            edges.append(dict(type=edge_type, source=ancestor, target=identifier))
            if identifier not in children[ancestor]:
                children[ancestor].add(identifier)
                indegree[identifier] += 1
    # Iterative traversal handles histories beyond Python's recursion depth.
    queue = deque(identifier for identifier in sorted(experiments) if not indegree[identifier])
    order = []
    while queue:
        identifier = queue.popleft()
        order.append(identifier)
        for child in sorted(children[identifier]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(experiments):
        raise ValueError('Experiment lineage contains a cycle across parent, baseline or correction references')
    roots, active = {}, {}
    for identifier in order:
        previous = (experiments[identifier].get('correction') or {}).get('supersedes_id')
        roots[identifier] = roots[previous] if previous is not None else identifier
    for identifier in reversed(order):
        successor = corrected_by.get(identifier)
        active[identifier] = active[successor] if successor is not None else identifier
    nodes = []
    statuses = Counter()
    for identifier in sorted(experiments):
        doc = experiments[identifier]
        decision = doc.get('decision') or {}
        superseded = identifier in corrected_by
        if not superseded:
            statuses[doc['execution']['status']] += 1
        nodes.append(dict(id=identifier, revision=doc['revision'],
                          source=f'.autoresearch/experiments/{identifier}.json', kind=doc['kind'],
                          parent_id=doc['parent_id'], baseline_id=doc['baseline_id'],
                          correction_of=(doc.get('correction') or {}).get('supersedes_id'),
                          code_ref=doc['code_ref'], execution_status=doc['execution']['status'],
                          decision_status=decision.get('status'), decision_validity=decision.get('validity'),
                          superseded=superseded, corrected_by=corrected_by.get(identifier),
                          execution_id=roots[identifier], active_record_id=active[identifier],
                          selected=identifier == selected))
    for edge in edges:
        edge['source_superseded'] = edge['source'] in corrected_by
    edges.sort(key=lambda edge:(edge['source'], edge['target'], edge['type']))
    counts = dict(record_count=len(nodes), execution_count=len(nodes)-len(corrected_by),
                  correction_count=len(corrected_by), superseded_count=len(corrected_by),
                  cancelled_count=statuses.get('cancelled', 0), status_counts=dict(sorted(statuses.items())))
    return dict(view='experiment_lineage', project_id=project['id'], selected_experiment_id=selected,
                nodes=nodes, edges=edges, counts=counts, git_verified=False, evidence_checked=False,
                limitations=[
                    'Execution identities include planned and cancelled records; they do not count verified runs.',
                    'Corrections share one execution identity; status counts use only active correction endpoints.',
                    'References retain their original IDs even when superseded; no automatic retargeting occurs.',
                    'Code references are recorded opaque identifiers; Git objects and evidence are not verified.'])


def _label(value):
    # Mermaid numeric entities avoid raw quotes, directives, markup, newlines,
    # entity injection and Markdown fences. IDs and edges never use these values.
    return ''.join(character if character.isascii() and (character.isalnum() or character in ' ._/-:=')
                   else f'#{ord(character)};' for character in str(value))


def render_mermaid(data):
    """Render graph data with generated node IDs and inert encoded labels."""
    names = {node['id']:f'n{index}' for index, node in enumerate(data['nodes'])}
    lines = ['flowchart TD']
    for node in data['nodes']:
        decision = node['decision_status'] or 'none'
        state = 'superseded' if node['superseded'] else 'active'
        selection = ' / selected' if node['selected'] else ''
        validity = node['decision_validity'] or 'none'
        label = (f"{node['id']} / {node['execution_status']} / decision={decision} / validity={validity} / {state}{selection} / "
                 f"code_ref={node['code_ref']}")
        lines.append(f'  {names[node["id"]]}["{_label(label)}"]')
    for edge in data['edges']:
        lines.append(f'  {names[edge["source"]]} -->|{_label(edge["type"])}| {names[edge["target"]]}')
    return '\n'.join(lines) + '\n'
