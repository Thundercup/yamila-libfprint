# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fixed vendor identity; assets are always siblings of installed runtime code."""
import hashlib
import os
from pathlib import Path

DLL_NAME = 'YmlWbioEngineAdapter.dll'
DLL_SHA = 'f745baf9c94488473e98472a5e779c120abfa72a2058af3b9c61c80affc7a9c1'
DLL_SIZE = 2867104


def validate_dll(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('vendor DLL missing or not a regular file: ' + path.name)
    if path.stat().st_size != DLL_SIZE:
        raise ValueError('vendor DLL size mismatch: ' + path.name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != DLL_SHA:
        raise ValueError('vendor DLL SHA-256 mismatch: ' + path.name)
    return dict(name=DLL_NAME, size=DLL_SIZE, sha256=DLL_SHA)


def check_runtime(directory):
    directory = Path(directory)
    result = validate_dll(directory/'vendor'/DLL_NAME)
    for name in ('engine-guard', 'native-worker'):
        path = directory/name
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('runtime ELF missing or not executable: ' + name)
        with path.open('rb') as f:
            if f.read(4) != b'\x7fELF':
                raise ValueError('runtime ELF header mismatch: ' + name)
    return dict(vendor=result, runtime='linux-pe', ipc='YML1')
