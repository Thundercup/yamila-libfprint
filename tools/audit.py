#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Strict public file allowlist; exclude build/cache and Git metadata."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from assets import DLL_NAME,validate_dll
MANIFEST = 'PUBLIC-MANIFEST.json'


def inventory(root):
    result = set()
    for p in root.rglob('*'):
        rel = p.relative_to(root)
        if rel.parts[0] in ('build','.cache','.git'):
            continue
        if p.is_symlink():
            raise ValueError('source symlink forbidden: '+str(rel))
        if p.is_file():result.add(rel.as_posix())
    return result


def selected(root):
    items=json.loads((root/'public-files.json').read_text())['files']
    paths=[item['path'] for item in items]
    if len(paths)!=len(set(paths)):
        raise ValueError('duplicate allowlist entry')
    for name in paths:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or p.as_posix()!=name or p.parts[0] in ('build','.cache','.git'):
            raise ValueError('invalid allowlist path')
        if not (root/name).resolve().is_relative_to(root.resolve()):
            raise ValueError('source escape')
    return items


def scan_file(root,name):
    path=root/name
    data=path.read_bytes()
    if name=='vendor/'+DLL_NAME:
        validate_dll(path)
    else:
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:raise ValueError('unexpected binary: '+name)
        if data.startswith((b'\x7fELF',b'MZ')):
            raise ValueError('unexpected executable: '+name)
        # Public files cannot contain developer-home paths or original capture
        # directory names. These tokens are split so this auditor audits itself.
        forbidden=('/ho'+'me/','windows-'+'run-','private-'+'data/','/var/lib/yamila-'+'bridge')
        if any(token in text for token in forbidden):
            raise ValueError('private/developer path in '+name)
    if path.suffix.lower() in ('.png','.pgm','.raw','.raw16','.pcap','.pcapng','.ymlt','.key','.sqlite'):
        raise ValueError('forbidden public data type: '+name)
    return dict(path=name,size=len(data),sha256=hashlib.sha256(data).hexdigest())


def audit(root=ROOT,write=False):
    items=selected(root)
    expected={item['path'] for item in items}
    actual=inventory(root)-{MANIFEST}
    if actual!=expected:
        raise ValueError('public allowlist mismatch: missing='+repr(sorted(expected-actual))+' extra='+repr(sorted(actual-expected)))
    records=[{**scan_file(root,item['path']), 'origin':item['origin'], 'license':item['license']} for item in items]
    result=dict(schema=1,files=records)
    if write:
        (root/MANIFEST).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    elif json.loads((root/MANIFEST).read_text())!=result:
        raise ValueError('public source digest mismatch')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest',action='store_true',help='refresh digests only for the predeclared allowlist')
    args=parser.parse_args()
    try:
        result=audit(write=args.write_manifest)
        print('Public allowlist/digests OK: '+str(len(result['files']))+' files')
    except (OSError,ValueError,KeyError) as error:sys.exit(str(error))
