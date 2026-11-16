"""Shared atomic writes and backups for the offline pass (library module)."""
import json
import os
import shutil
import tempfile
from pathlib import Path


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n')


def backup_file(path):
    """Retain an immutable content-addressed sibling before replacing a record."""
    import hashlib
    path = Path(path)
    if not path.exists():
        return
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    dest = path.parent / '.song-qa-backups' / digest / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(path, dest)
