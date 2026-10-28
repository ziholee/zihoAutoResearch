"""Bounded local fixed-input hashes; never read file contents into model context."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

MAX_FILES = 128
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
_WINDOWS = os.name == 'nt'
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def _require(condition, message):
    if not condition: raise ValueError(message)


def _name(value):
    _require(isinstance(value, str) and 0 < len(value) <= 1024
             and not any(ord(c) < 32 or ord(c) == 127 for c in value)
             and '\\' not in value and ':' not in value
             and not any(part in ('', '.', '..') or part.startswith('.') for part in value.split('/')),
             'Fixed-input paths must be canonical, non-hidden project-relative file paths.')


def validate_policy(policy, editable_paths):
    _require(isinstance(policy, dict) and set(policy) == {'version','evaluation_paths','provenance_paths'}
             and type(policy['version']) is int and policy['version'] == 1,
             'Unsupported file contract; expected version 1 and both path lists.')
    names = []
    for key in ('evaluation_paths','provenance_paths'):
        values = policy[key]
        _require(isinstance(values,list), 'File contract paths must be lists.')
        _require(key != 'evaluation_paths' or bool(values), 'At least one evaluation path is required.')
        for value in values: _name(value)
        names.extend(values)
    _require(len(names) <= MAX_FILES and len(names) == len(set(names)), 'Fixed-input paths must be distinct and within the file count limit.')
    _require(isinstance(editable_paths,list), 'Editable paths must be a list.')
    editable = {PurePosixPath(name).as_posix() for name in editable_paths if isinstance(name,str)}
    _require(not set(names) & editable, 'Fixed evaluation/provenance paths cannot be editable.')


def validate_manifest(manifest):
    _require(isinstance(manifest,dict) and set(manifest)=={'version','files'}
             and type(manifest['version']) is int and manifest['version']==1,
             'Unsupported file manifest.')
    files=manifest['files']
    _require(isinstance(files,dict) and 0 < len(files) <= MAX_FILES, 'Invalid file manifest count.')
    total=0; evaluation=False
    for name, item in files.items():
        _name(name)
        _require(isinstance(item,dict) and set(item)=={'role','size_bytes','sha256'}, 'Invalid file manifest entry.')
        _require(item['role'] in ('evaluation','input'), 'Invalid fixed-input role.')
        evaluation |= item['role']=='evaluation'
        size=item['size_bytes']; sha=item['sha256']
        _require(type(size) is int and 0 <= size <= MAX_FILE_BYTES, 'File manifest exceeds per-file limit.')
        _require(isinstance(sha,str) and bool(_HASH.fullmatch(sha)), 'Invalid file SHA-256.')
        total += size
    _require(evaluation and total <= MAX_TOTAL_BYTES, 'Manifest needs evaluation files within the total byte limit.')


def _path(root, name, *, allow_missing=False):
    _name(name)
    current=root
    for part in name.split('/'):
        current=current/part
        try:info=current.lstat()
        except FileNotFoundError:
            if allow_missing:continue
            raise
        _require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                 'Redirected fixed-input paths are not allowed.')
    return current


def validate_paths(root, policy, editable_paths):
    """Reject actual file aliases before a protected file can be edited.

    Missing editable targets are allowed for future approved files. The checks
    observe current paths; they do not lock the OS namespace against other writers.
    """
    validate_policy(policy,editable_paths)
    root=Path(root).resolve()
    fixed=[]
    try:
        for name in policy['evaluation_paths']+policy['provenance_paths']:
            info=_path(root,name).lstat()
            _require(stat.S_ISREG(info.st_mode), 'Fixed inputs must be ordinary files.')
            _require(not any(os.path.samestat(info,other) for other in fixed),
                     'Fixed-input paths alias the same file.')
            fixed.append(info)
        for name in editable_paths:
            path=_path(root,name,allow_missing=True)
            try:info=path.lstat()
            except FileNotFoundError:continue
            _require(stat.S_ISREG(info.st_mode), 'Existing editable inputs must be ordinary files.')
            _require(not any(os.path.samestat(info,other) for other in fixed),
                     'Editable path aliases a fixed evaluation/provenance input.')
    except OSError as exc:
        raise ValueError('File contract path is missing, unreadable or redirected.') from exc


def _identity(info, *, cross_api=False):
    identity = (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns)
    # Windows path stat may expose birth time as ctime while fstat exposes
    # change time (CPython #157671). Retain ctime for same-API comparisons.
    return identity if cross_api and _WINDOWS else identity+(info.st_ctime_ns,)


def snapshot(root, policy):
    """Read fixed ordinary files in bounded chunks and detect observed read races.

    This is not an OS snapshot or a defense against writers that restore bytes
    between checks. Path lists and hashes do not authenticate a local operator.
    """
    validate_paths(root,policy,[])
    root=Path(root).resolve()
    files={};total=0
    try:
        for key,role in (('evaluation_paths','evaluation'),('provenance_paths','input')):
            for name in sorted(policy[key]):
                path=_path(root,name); before=path.lstat()
                _require(stat.S_ISREG(before.st_mode), 'Fixed inputs must be ordinary files.')
                _require(before.st_size <= MAX_FILE_BYTES and total+before.st_size <= MAX_TOTAL_BYTES,
                         'Fixed inputs exceed the byte limit.')
                flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0)
                descriptor=os.open(path,flags)
                try:
                    opened=os.fstat(descriptor)
                    _require(_identity(opened,cross_api=True)==_identity(before,cross_api=True), 'Fixed input changed before reading.')
                    hasher=hashlib.sha256();size=0
                    while True:
                        chunk=os.read(descriptor,CHUNK_BYTES)
                        if not chunk:break
                        size+=len(chunk)
                        _require(size<=MAX_FILE_BYTES and total+size<=MAX_TOTAL_BYTES, 'Fixed inputs exceed the byte limit.')
                        hasher.update(chunk)
                    after=os.fstat(descriptor)
                    current=_path(root,name).lstat()
                    _require(size==before.st_size and _identity(opened)==_identity(after)
                             and _identity(before)==_identity(current)
                             and _identity(after,cross_api=True)==_identity(current,cross_api=True),
                             'Fixed input changed during reading.')
                finally:os.close(descriptor)
                files[name]=dict(role=role,size_bytes=size,sha256=hasher.hexdigest())
                total+=size
    except OSError as exc:
        raise ValueError('Fixed input is missing, unreadable or redirected.') from exc
    result=dict(version=1,files=files)
    validate_manifest(result)
    return result


def assert_current(root, policy, manifest):
    validate_manifest(manifest)
    _require(snapshot(root,policy)==manifest, 'Fixed evaluation or provenance inputs changed; obtain new evidence.')
