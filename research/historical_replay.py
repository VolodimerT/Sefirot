"""Offline historical replay with the exact archived CORE; never rewrite a ledger.

Only reviewed, pinned local Git commits are executable. A decision's recorded
code hash chooses the build, and the archived build verifies itself again.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from sefirot.contracts import digest


PINNED_BUILDS = {
    'PR78': '72f8018e0719f05ec8aa74398e1a582a82d6d06d',
    'PR79': '84dce563fc8a444118276cdaa0f332e6a8e79b8c',
    'PR80': 'dbf32996c07ec9c1f1fca7fe1243ab4eaf033c86',
}

_CHILD = r'''
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src'))
from sefirot.identity import code_hash
from sefirot.contracts import VERSION
from sefirot.repository import Repository
from sefirot.service import Service
if code_hash()!=sys.argv[4] or VERSION!=sys.argv[5]:
    raise SystemExit('ARCHIVED_BUILD_MISMATCH')
repo=Repository(sys.argv[2],read_only=True)
try:
    if not repo.verify():
        raise SystemExit('HISTORICAL_LEDGER_INTEGRITY_FAILED')
    decision=repo.get('decisions',sys.argv[3])
    prediction=repo.get('predictions',decision['prediction_id'])
    if prediction['code_hash']!=sys.argv[4] or prediction['version']!=VERSION:
        raise SystemExit('HISTORICAL_SEAL_BUILD_MISMATCH')
    result=Service(repo).replay(sys.argv[3])
    print(json.dumps({'matches':result['matches'],'decision_id':result['id'],
                      'code_hash':code_hash(),'version':VERSION},sort_keys=True))
finally:
    repo.close()
'''


def _file_hash(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _recorded_build(ledger, decision_id):
    if not isinstance(decision_id, str) or not re.fullmatch(r'[0-9a-f]{64}', decision_id):
        raise ValueError('INVALID_DECISION_ID')
    try:
        with closing(sqlite3.connect(Path(ledger).as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT payload FROM decisions WHERE id=?', (decision_id,)).fetchone()
            if row is None:
                raise ValueError('DECISION_NOT_FOUND')
            decision = json.loads(row[0])
            row = db.execute('SELECT payload FROM predictions WHERE id=?',
                             (decision['prediction_id'],)).fetchone()
            if row is None:
                raise ValueError('PREDICTION_NOT_FOUND')
            prediction = json.loads(row[0])
        code, version = prediction['code_hash'], prediction['version']
    except (sqlite3.Error, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('INVALID_HISTORICAL_LEDGER') from None
    if not isinstance(code, str) or not re.fullmatch(r'[0-9a-f]{64}', code):
        raise ValueError('INVALID_RECORDED_CODE_HASH')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', version):
        raise ValueError('INVALID_RECORDED_VERSION')
    return code, version


def _extract_build(repo, commit, destination):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('INVALID_PINNED_COMMIT')
    try:
        archive = subprocess.run(['git', '-C', str(repo), 'archive', commit, 'src/sefirot'],
                                 capture_output=True, check=False)
    except OSError:
        raise ValueError('PINNED_BUILD_UNAVAILABLE') from None
    if archive.returncode or len(archive.stdout) > 20_000_000:
        raise ValueError('PINNED_BUILD_UNAVAILABLE')
    total = 0
    try:
        tar = tarfile.open(fileobj=BytesIO(archive.stdout))
    except tarfile.TarError:
        raise ValueError('INVALID_BUILD_ARCHIVE') from None
    with tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if member.isdir() and parts in (('src',), ('src', 'sefirot')):
                continue
            if parts[:2] != ('src', 'sefirot') or '..' in parts or member.issym() or member.islnk():
                raise ValueError('INVALID_BUILD_ARCHIVE')
            if member.isdir():
                continue
            if not member.isfile() or member.size > 1_000_000:
                raise ValueError('INVALID_BUILD_ARCHIVE')
            total += member.size
            if total > 10_000_000:
                raise ValueError('INVALID_BUILD_ARCHIVE')
            path = destination.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tar.extractfile(member).read())
    modules = destination/'src'/'sefirot'
    if not (modules/'identity.py').is_file():
        raise ValueError('INCOMPLETE_BUILD_ARCHIVE')
    return digest({p.name:p.read_text(encoding='utf-8') for p in sorted(modules.glob('*.py'))})


def replay_historical(ledger, decision_id, *, builds=PINNED_BUILDS, repo_root=None):
    """Route a read-only copy by sealed code_hash and version, never by a label alone."""
    path = Path(ledger)
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000_000
            or Path(str(path)+'-wal').exists() or Path(str(path)+'-shm').exists()):
        raise ValueError('CHECKPOINTED_REGULAR_LEDGER_REQUIRED')
    repo_root = Path(repo_root or Path(__file__).resolve().parents[1])
    original_hash = _file_hash(path)
    with TemporaryDirectory(prefix='sefirot-historical-replay-') as tmp:
        copied = Path(tmp)/'ledger.sqlite'
        shutil.copyfile(path, copied)
        if _file_hash(copied) != original_hash:
            raise ValueError('LEDGER_CHANGED_DURING_COPY')
        sealed_hash, version = _recorded_build(copied, decision_id)
        selected = None
        for label, commit in builds.items():
            if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', label):
                raise ValueError('INVALID_BUILD_LABEL')
            build_root = Path(tmp)/label
            build_root.mkdir()
            candidate_hash = _extract_build(repo_root, commit, build_root)
            if candidate_hash == sealed_hash:
                if selected is not None:
                    raise ValueError('AMBIGUOUS_HISTORICAL_BUILD')
                selected = (label, commit, build_root)
        if selected is None:
            raise ValueError('UNKNOWN_HISTORICAL_BUILD')
        label, commit, build_root = selected
        try:
            child = subprocess.run([sys.executable, '-I', '-c', _CHILD, str(build_root),
                                    str(copied), decision_id, sealed_hash, version],
                                   cwd=build_root, env={'PATH':os.environ.get('PATH',''),
                                       'PYTHONDONTWRITEBYTECODE':'1'},
                                   capture_output=True, text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError('ARCHIVED_REPLAY_TIMEOUT') from None
        if child.returncode:
            raise ValueError('ARCHIVED_REPLAY_FAILED')
        result = json.loads(child.stdout)
        if (result != {'matches':True,'decision_id':decision_id,
                       'code_hash':sealed_hash,'version':version}):
            raise ValueError('HISTORICAL_REPLAY_MISMATCH')
        if _file_hash(copied) != original_hash or _file_hash(path) != original_hash:
            raise ValueError('LEDGER_CHANGED_DURING_REPLAY')
        return {'status':'MATCH', 'build':label, 'commit':commit,
                'code_hash':sealed_hash, 'version':version,
                'decision_id':decision_id, 'ledger_sha256':original_hash,
                'original_unchanged':True, 'copy_unchanged':True}
