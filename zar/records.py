"""Canonical records loaded once for an operation, with no persistent cache.

Callers treat snapshots and their documents as immutable. Proposed updates must
use separate documents; validation copies mappings before applying an overlay.
"""
from dataclasses import dataclass
from pathlib import Path

from .codec import loads


@dataclass(frozen=True)
class RecordSnapshot:
    records: dict
    paths: dict
    diagnostics: list


def load_records(root, project):
    """Read ordinary canonical record files and validate their local contracts."""
    from .validation import diagnostic, validate_document

    store = Path(root) / '.autoresearch'
    records = {kind: {} for kind in ('review', 'experiment', 'submission')}
    paths = {}
    diagnostics = []
    project_id = project.get('id') if isinstance(project, dict) else None
    ids = {project_id} if isinstance(project_id, str) else set()
    if store.is_symlink() or not store.is_dir():
        diagnostics.append(diagnostic('io', store, 'Record store must be an existing ordinary directory'))
        return RecordSnapshot(records, paths, diagnostics)
    for kind, group in records.items():
        directory = store / (kind + 's')
        if directory.is_symlink() or not directory.is_dir():
            diagnostics.append(diagnostic('io', directory, 'Record directory must be an existing ordinary directory'))
            continue
        try:
            entries = sorted(directory.glob('*.json'))
        except OSError as exc:
            diagnostics.append(diagnostic('io', directory, str(exc)))
            continue
        for path in entries:
            if path.is_symlink() or not path.is_file():
                diagnostics.append(diagnostic('io', path, 'Record must be an ordinary file'))
                continue
            try:
                doc = loads(path.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError) as exc:
                diagnostics.append(diagnostic('json', path, str(exc)))
                continue
            except OSError as exc:
                diagnostics.append(diagnostic('io', path, str(exc)))
                continue
            errors = validate_document(doc, kind)
            for error in errors:
                error['path'] = str(path) + ':' + error['path']
            diagnostics.extend(errors)
            if errors:
                continue
            if path.stem != doc['id']:
                diagnostics.append(diagnostic('conflict', path, 'Filename does not match record ID'))
            if doc['id'] in ids:
                diagnostics.append(diagnostic('conflict', path, 'Duplicate record ID'))
            ids.add(doc['id'])
            group[doc['id']] = doc
            paths[doc['id']] = path
    return RecordSnapshot(records, paths, diagnostics)
