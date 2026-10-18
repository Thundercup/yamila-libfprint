#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspect package metadata and confined payload; never install or run scripts."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import stat
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from assets import validate_dll
sys.path.insert(0,str(ROOT/'tools'))
from privacy_check import scan


def output(*args):return subprocess.run(list(args),capture_output=True,text=True,check=True).stdout


def inspect(package,denied=()):
    package=Path(package).resolve(strict=True)
    identity=output('rpm','-qp','--qf','%{NAME} %{VERSION} %{RELEASE} %{ARCH}',str(package)).split()
    if identity[0]!='yamila-libfprint' or identity[3]!='x86_64':raise ValueError('unexpected package identity')
    if scan(output('rpm','-qp','--scripts',str(package)),denied):raise ValueError('private marker in RPM scripts')
    provides=output('rpm','-qp','--provides',str(package))
    if 'libfprint-2.so.2' in provides or any(x in provides for x in ('user(yamila-fprint)','group(yamila-fprint)')):raise ValueError('unexpected global ABI or automatic pre-gate account creation')
    entries=output('rpm','-qp','--qf','[%{FILENAMES}\t%{FILELINKTOS}\t%{FILEMODES}\n]',str(package))
    prefixes=('/usr/lib64/yamila-fprint','/usr/libexec/yamila-fprint','/usr/share/doc/yamila-libfprint','/usr/share/licenses/yamila-libfprint')
    exact={'/usr/share/selinux/packages/yamila_libfprint.pp','/usr/lib/systemd/system/fprintd.service.d/20-yamila-libfprint.conf','/usr/lib/sysusers.d/yamila-fprint.conf','/usr/lib/udev/rules.d/70-yamila-fprint.rules'}
    links={'/usr/lib64/yamila-fprint/libfprint-2.so.2':'libfprint-2.so.2.0.0','/usr/lib64/yamila-fprint/libfprint-2.so':'libfprint-2.so.2'}
    for line in entries.splitlines():
        name,target,mode=line.split('\t');parts=PurePosixPath(name).parts
        if '..' in parts or not name.startswith('/'):raise ValueError('unsafe RPM path')
        if not any(name==p or name.startswith(p+'/') for p in prefixes) and name not in exact:raise ValueError('unexpected RPM member: '+name)
        if target and links.get(name)!=target:raise ValueError('unsafe RPM symlink')
        if not stat.S_ISLNK(int(mode)) and int(mode) & 0o6022:raise ValueError('unsafe RPM file permissions')
        if stat.S_IFMT(int(mode)) not in (stat.S_IFREG,stat.S_IFDIR,stat.S_IFLNK):raise ValueError('special RPM file type')
    with tempfile.TemporaryDirectory(prefix='yamila-rpm-inspect-') as tmp:
        # Complete conversion before cpio: it can stop at the archive trailer
        # while rpm2cpio still has padding to write, causing a false SIGPIPE.
        with tempfile.TemporaryFile() as payload:
            subprocess.run(['rpm2cpio',str(package)],stdout=payload,check=True)
            payload.seek(0)
            subprocess.run(['cpio','-idm','--quiet','--no-preserve-owner','--no-absolute-filenames'],stdin=payload,cwd=tmp,check=True)
        root=Path(tmp)
        vendor=validate_dll(root/'usr/libexec/yamila-fprint/vendor/YmlWbioEngineAdapter.dll')
        for name in ('usr/lib64/yamila-fprint/libfprint-2.so.2.0.0','usr/libexec/yamila-fprint/native-worker','usr/libexec/yamila-fprint/engine-guard'):
            dynamic=output('readelf','-d',str(root/name))
            if 'RPATH' in dynamic or 'RUNPATH' in dynamic:raise ValueError('build path remains in ELF RUNPATH')
        for file in root.rglob('*'):
            if file.is_file() and not file.is_symlink() and file.name!='YmlWbioEngineAdapter.dll':
                if scan(file.read_bytes().decode('utf-8',errors='replace'),denied):raise ValueError('private marker in RPM payload: '+str(file.relative_to(root)))
        dropin=(root/'usr/lib/systemd/system/fprintd.service.d/20-yamila-libfprint.conf').read_text()
        if dropin!='[Service]\nEnvironment=LD_LIBRARY_PATH=/usr/lib64/yamila-fprint\nLimitCORE=0\n':raise ValueError('unexpected fprintd integration')
    return dict(identity='-'.join(identity),sha256=hashlib.sha256(package.read_bytes()).hexdigest(),vendor=vendor,
                private_library=True,host_install=False,rpm_digests=output('rpm','-K',str(package)).strip())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('rpm',type=Path);parser.add_argument('--deny-text',action='append',default=[]);args=parser.parse_args()
    print(json.dumps(inspect(args.rpm,args.deny_text),indent=2))
