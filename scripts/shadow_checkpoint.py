"""Pack or restore both dedicated ledgers as a single private checkpoint."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.repository import Repository

NAMES = ('shadow.sqlite', 'sources.sqlite')
MAX_LEDGER_BYTES = 256 * 1024 * 1024


def verified(path):
    with closing(Repository(path, read_only=True)) as repo:
        if not repo.verify():
            raise ValueError('checkpoint ledger integrity failed')


def pack(directory, archive):
    with TemporaryDirectory() as work:
        data = {}
        for name in NAMES:
            original = directory / name
            destination = Path(work) / name
            with closing(Repository(original, read_only=True)) as repo, closing(sqlite3.connect(destination)) as copy:
                repo.db.backup(copy)
            verified(destination)
            if destination.stat().st_size > MAX_LEDGER_BYTES:
                raise ValueError('checkpoint ledger exceeds byte limit')
            data[name] = destination.read_bytes()
    manifest = {name: sha256(content).hexdigest() for name, content in data.items()}
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as bundle:
        for name, content in data.items():
            bundle.writestr(name, content)
        bundle.writestr('sha256.json', json.dumps(manifest, sort_keys=True))


def restore(directory, archive):
    if directory.exists():
        raise ValueError('restore needs a fresh directory')
    directory.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as bundle, TemporaryDirectory(dir=directory.parent) as work:
        entries = bundle.infolist()
        if {entry.filename for entry in entries} != {*NAMES, 'sha256.json'} or len(entries) != 3:
            raise ValueError('unexpected checkpoint contents')
        if any(e.file_size > (1024 if e.filename == 'sha256.json' else MAX_LEDGER_BYTES) for e in entries):
            raise ValueError('checkpoint member exceeds byte limit')
        manifest = json.loads(bundle.read('sha256.json'))
        stage = Path(work) / 'verified'
        stage.mkdir()
        for name in NAMES:
            content = bundle.read(name)
            if sha256(content).hexdigest() != manifest.get(name):
                raise ValueError('checkpoint content hash mismatch')
            destination = stage / name
            destination.write_bytes(content)
            verified(destination)
        stage.rename(directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('pack', 'restore'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    (pack if args.action == 'pack' else restore)(args.directory, args.archive)
